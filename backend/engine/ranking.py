"""Evaluate every activity against the current market and rank the results."""

import sqlite3
import time
from dataclasses import dataclass, replace
from enum import StrEnum

from backend.engine import activities, chains, history, market as market_mod
from backend.engine.model import Result, Risk, evaluate
from backend.engine.settings import Settings
from backend.ingest.recipes import Overrides


class SortKey(StrEnum):
    GP_HR = "gp_hr"
    RISK_ADJUSTED = "risk_adjusted"


@dataclass(frozen=True)
class Filters:
    types: frozenset[str] = frozenset()  # empty means all
    f2p_only: bool = False
    include_illiquid: bool = False
    max_risk: Risk | None = None
    player_levels: dict[str, int] | None = None  # from hiscores; None means no level filter
    search: str = ""
    min_consistency: float | None = None  # e.g. 0.8: profitable in at least 80% of the last week's hours


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
    results = [evaluate(spec, market, settings) for spec in specs]
    results = _best_shop_per_item(results)

    by_key = {r.spec.key: r for r in results}
    chain_results = [evaluate(spec, market, settings) for spec in chains.build(results, settings)]
    results += chains.keep_worthwhile(chain_results, by_key)

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
        group.sort(key=lambda r: r.gp_hr or 0, reverse=True)
        best = group[0]
        if len(group) > 1:
            also = ", ".join(r.spec.variant for r in group[1:4]) + (" …" if len(group) > 4 else "")
            best.spec = replace(best.spec, note=f"{best.spec.note} Also sold at {len(group) - 1} other shops: {also}.")
        others.append(best)
    return others


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
        return True

    attr = "gp_hr" if sort is SortKey.GP_HR else "gp_hr_risk_adjusted"
    return sorted(filter(keep, results), key=lambda r: getattr(r, attr), reverse=True)
