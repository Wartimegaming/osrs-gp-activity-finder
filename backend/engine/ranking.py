"""Evaluate every activity against the current market and rank the results."""

import sqlite3
import time
from dataclasses import dataclass
from enum import StrEnum

from backend.engine import activities, market as market_mod
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
    )
    return [evaluate(spec, market, settings) for spec in specs]


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
        return True

    attr = "gp_hr" if sort is SortKey.GP_HR else "gp_hr_risk_adjusted"
    return sorted(filter(keep, results), key=lambda r: getattr(r, attr), reverse=True)
