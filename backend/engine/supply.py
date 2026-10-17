"""Recipes with an ingredient bought from an NPC shop instead of the GE.

Vials of water, thread, needles and the like are often far cheaper in shops. A variant swaps
one GE-bought ingredient for the cheapest useful shop and adds the time spent buying it (world
hops and bank trips, the same shop model as shop resales). Like chains, a variant is only
listed when it beats buying everything on the GE.
"""

from collections import defaultdict
from dataclasses import replace

from backend.engine import activities
from backend.engine.market import Market
from backend.engine.model import ActivitySpec, Result, actions_per_hour
from backend.engine.settings import Settings
from backend.ingest.recipes import Overrides

SHOPS_PER_INGREDIENT = 3  # the fastest few shops are worth evaluating; the rest rarely win


def build(results: list[Result], conn, market: Market, settings: Settings, overrides: Overrides) -> list[ActivitySpec]:
    rows_by_item = defaultdict(list)
    for row in activities.shop_rows(conn, overrides):
        rows_by_item[row["item_id"]].append(row)
    values = {r["id"]: r["value"] for r in conn.execute("SELECT id, value FROM items")}

    specs = []
    for r in results:
        if r.spec.type != "recipe" or r.profit is None:
            continue
        speed = actions_per_hour(r.spec, settings)
        if not speed:
            continue
        for index, (leg, priced) in enumerate(zip(r.spec.inputs, r.inputs)):
            if leg.kind != "item" or priced.price is None or leg.item_id not in rows_by_item:
                continue
            runs = []
            for row in rows_by_item[leg.item_id]:
                # Only buy while the shop is cheaper than the GE.
                run = activities.shop_run(row, leg.name, values.get(leg.item_id), priced.price, settings, overrides)
                if run is not None:
                    runs.append((row, run))
            runs.sort(key=lambda pair: pair[1].per_hour, reverse=True)
            for row, run in runs[:SHOPS_PER_INGREDIENT]:
                hours = 1 / speed + leg.quantity / run.per_hour  # make one, plus buying its ingredient
                inputs = list(r.spec.inputs)
                inputs[index] = activities.shop_leg(row, run, leg.quantity)
                shop = row["shop"].rstrip(".")
                specs.append(replace(
                    r.spec,
                    key=f"supply:{row['shop']}:{leg.item_id}>{r.spec.key}",
                    variant=" · ".join(filter(None, [r.spec.variant, f"{leg.name} from {shop}"])),
                    inputs=tuple(inputs),
                    fixed_rate=1 / hours,
                    ticks_estimated=True,
                    members=r.spec.members or bool(row["members"]),
                    note=" ".join(filter(None, [
                        r.spec.note,
                        f"Buys {leg.name} from {shop} ({row['location'] or 'location unknown'}) at "
                        f"~{run.avg_cost:,.0f} gp instead of {priced.price:,.0f} on the GE: {run.how.lower()}.",
                    ])),
                ))
    return specs


def keep_worthwhile(variants: list[Result], base: dict[str, Result]) -> list[Result]:
    """Keep a variant only if it beats the all-GE recipe, and only the best per (recipe, ingredient)."""
    best: dict[tuple, Result] = {}
    for v in variants:
        if not v.ranked or v.gp_hr <= 0:
            continue
        prefix, recipe_key = v.spec.key.split(">", 1)
        original = base.get(recipe_key)
        if original is not None and v.gp_hr <= (original.gp_hr or 0):
            continue
        group = (recipe_key, prefix.rsplit(":", 1)[1])  # recipe and ingredient item id
        if group not in best or v.gp_hr > best[group].gp_hr:
            best[group] = v
    return list(best.values())
