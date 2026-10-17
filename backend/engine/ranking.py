"""Evaluate every activity against the current market and rank the results."""

import sqlite3
import time
from dataclasses import dataclass, replace
from enum import StrEnum

from backend.engine import activities, chains, history, market as market_mod, supply
from backend.engine.model import Result, Risk, evaluate
from backend.engine.settings import Settings
from backend.ingest.recipes import Overrides


class SortKey(StrEnum):
    GP_HR = "gp_hr"
    RISK_ADJUSTED = "risk_adjusted"
    DAILY = "daily"


@dataclass(frozen=True)
class Filters:
    types: frozenset[str] = frozenset()  # empty means all
    f2p_only: bool = False
    include_illiquid: bool = False
    max_risk: Risk | None = None
    player_levels: dict[str, int] | None = None  # from hiscores; None means no level filter
    search: str = ""
    min_consistency: float | None = None  # e.g. 0.8: profitable in at least 80% of the last week's hours
    min_daily_volume: int | None = None  # the product's units traded on the GE in the last 24 hours


_RISK_ORDER = [Risk.LOW, Risk.MEDIUM, Risk.HIGH]


def meets_requirements(result: Result, levels: dict[str, int]) -> bool:
    return all(
        level is None or levels.get(skill.lower(), 1) >= level
        for skill, level in result.spec.skills
    )


def evaluate_all(
    conn: sqlite3.Connection,
    settings: Settings,
    now: int | None = None,
    market: market_mod.Market | None = None,
) -> list[Result]:
    market = market or market_mod.load(conn, now or int(time.time()))
    overrides = Overrides.load()
    specs = (
        activities.recipe_specs(conn, settings, overrides)
        + activities.alch_specs(market, settings)
        + activities.flip_specs(market, settings)
        + activities.decant_specs(conn, market, settings, overrides)
        + activities.set_specs(conn, market)
        + activities.shop_specs(conn, market, settings, overrides)
    )
    # Consistency comes first: steady methods may spread their sales over the sell window.
    def run(batch: list) -> list[Result]:
        scores = history.CACHE.scores(conn, batch, settings)
        return [evaluate(s, market, settings, getattr(scores.get(s.key), "share", None)) for s in batch]

    results = _best_shop_per_item(run(specs))
    by_key = {r.spec.key: r for r in results}
    results += chains.keep_worthwhile(run(chains.build(results, settings)), by_key)
    results += supply.keep_worthwhile(run(supply.build(results, conn, market, settings, overrides)), by_key)

    scores = history.CACHE.scores(conn, [r.spec for r in results], settings)
    for r in results:
        if (c := scores.get(r.spec.key)) is not None:
            r.consistency, r.median_profit_7d, r.consistency_hours = c.share, c.median_profit, c.hours
    return results


def _best_shop_per_item(results: list[Result]) -> list[Result]:
    """Many shops sell the same item at the same price; list the best one (members and F2P separately)."""
    shops: dict[tuple, list[Result]] = {}
    others = []
    for r in results:
        if r.spec.type == "shop":
            shops.setdefault((r.spec.outputs[0].item_id, r.f2p), []).append(r)
        else:
            others.append(r)
    for group in shops.values():
        # When volume caps make shops tie on GP/hr, prefer the one that's quickest to buy from.
        group.sort(key=lambda r: (r.gp_hr or 0, r.actions_per_hour or 0), reverse=True)
        best = group[0]
        if len(group) > 1:
            count = len(group) - 1
            names = ", ".join(r.spec.variant.rstrip(".") for r in group[1:4]) + (" …" if len(group) > 4 else "")
            label = "other shop" if count == 1 else "other shops"
            best.spec = replace(best.spec, note=f"{best.spec.note} Also sold at {count} {label}: {names}.")
        others.append(best)
    return others


def main_volume(r: Result) -> int:
    """Daily volume of what the method is about: the product, or the item alched/flipped."""
    legs = r.outputs or r.inputs
    return legs[0].daily_volume if legs else 0


def rank(results: list[Result], filters: Filters = Filters(), sort: SortKey = SortKey.GP_HR) -> list[Result]:
    def keep(r: Result) -> bool:
        if not r.ranked or r.gp_hr <= 0:
            return False
        if filters.types and r.spec.type not in filters.types:
            return False
        if filters.f2p_only and not r.f2p:
            return False
        if not filters.include_illiquid and not r.liquid:
            return False
        if filters.max_risk and _RISK_ORDER.index(r.risk) > _RISK_ORDER.index(filters.max_risk):
            return False
        if filters.player_levels is not None and not meets_requirements(r, filters.player_levels):
            return False
        if filters.search and filters.search.lower() not in r.spec.name.lower():
            return False
        if filters.min_consistency is not None and (r.consistency or 0) < filters.min_consistency:
            return False
        if filters.min_daily_volume is not None and main_volume(r) < filters.min_daily_volume:
            return False
        return True

    attr = {SortKey.GP_HR: "gp_hr", SortKey.RISK_ADJUSTED: "gp_hr_risk_adjusted", SortKey.DAILY: "daily_profit"}[sort]
    return sorted(filter(keep, results), key=lambda r: getattr(r, attr) or 0, reverse=True)
