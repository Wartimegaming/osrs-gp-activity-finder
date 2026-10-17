"""Engine results as JSON-ready dicts for the web UI."""

import urllib.parse

from backend.engine.market import Market
from backend.engine.model import PricedLeg, Result
from backend.engine.settings import Settings

WIKI = "https://oldschool.runescape.wiki"


def wiki_url(page: str | None) -> str | None:
    if not page:
        return None
    title, _, anchor = page.partition("#")
    url = f"{WIKI}/w/{urllib.parse.quote(title.replace(' ', '_'))}"
    return f"{url}#{urllib.parse.quote(anchor.replace(' ', '_'))}" if anchor else url


def icon_url(icon: str | None) -> str | None:
    return f"{WIKI}/images/{urllib.parse.quote(icon.replace(' ', '_'))}" if icon else None


def _leg(leg: PricedLeg, market: Market) -> dict:
    item = market.get(leg.item_id)
    return {
        "name": leg.name,
        "item_id": leg.item_id,
        "kind": leg.kind,
        "quantity": leg.quantity,
        "price": leg.price,
        "daily_volume": leg.daily_volume,
        "min_daily_volume": leg.min_daily_volume,
        "buy_limit": leg.buy_limit,
        "icon": icon_url(item.icon) if item else None,
        "day_avg_high": item.day_avg_high if item else None,
        "day_avg_low": item.day_avg_low if item else None,
    }


def result(r: Result, market: Market, settings: Settings) -> dict:
    spec = r.spec
    main = (r.outputs or r.inputs)[0]  # what the row is "about": the product, or the alched item
    main_item = market.get(main.item_id)
    return {
        "key": spec.key,
        "type": spec.type,
        "name": spec.name,
        "variant": spec.variant,
        "wiki_url": wiki_url(spec.wiki_page),
        "icon": icon_url(main_item.icon) if main_item else None,
        "skills": [{"skill": s, "level": lvl} for s, lvl in spec.skills if lvl],
        "f2p": r.f2p,
        "facilities": spec.facilities,
        "tools": spec.tools,
        "note": spec.note,
        "inputs": [_leg(leg, market) for leg in r.inputs],
        "outputs": [_leg(leg, market) for leg in r.outputs],
        "fixed_revenue": spec.fixed_revenue,
        "ticks": spec.ticks,
        "actions_per_trip": spec.actions_per_trip,
        "input_cost": r.input_cost,
        "gross_revenue": r.gross_revenue,
        "tax": r.tax,
        "profit": r.profit,
        "actions_per_hour": r.actions_per_hour,
        "effective_actions": r.effective_actions,
        "limiting_factor": r.limiting_factor,
        "gp_hr_raw": r.gp_hr_raw,
        "gp_hr": r.gp_hr,
        "gp_hr_risk_adjusted": r.gp_hr_risk_adjusted,
        "daily_volume": main.daily_volume,
        "daily_value": main.daily_volume * (main.price or 0),
        "capital_per_hour": r.capital_per_hour,
        "roi": r.roi,
        "breakeven_move": r.breakeven_move,
        "volatility": r.volatility,
        "risk": r.risk,
        "liquid": r.liquid,
        "price_age": r.price_age,
        "flags": sorted(r.flags),
        "day_profit": r.day_profit,
        "caps": [{"limit": c.limit, "actions_per_hour": c.actions_per_hour, "item": c.item} for c in r.caps],
        "assumptions": {
            "price_mode": settings.price_mode,
            "ticks_estimated": spec.ticks_estimated,
            "trip_overhead_ticks": spec.trip_overhead_ticks if spec.actions_per_trip else None,
            "efficiency": r.efficiency,
            "fixed_rate": spec.fixed_rate,
            "liquidity_share": settings.liquidity_share,
            "override_key": spec.wiki_page if spec.type == "recipe" else None,
        },
    }
