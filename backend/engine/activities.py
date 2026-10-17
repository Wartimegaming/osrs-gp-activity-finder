"""Builds ActivitySpecs for each activity type from the database and market."""

import math
import re
import sqlite3
from collections import defaultdict

from backend.engine import inventory
from backend.engine.market import Market
from backend.engine.model import ActivitySpec, Leg
from backend.engine.settings import TICKS_PER_HOUR, PriceMode, Settings
from backend.ingest.recipes import Overrides


def recipe_specs(
    conn: sqlite3.Connection, settings: Settings, overrides: Overrides | None = None
) -> list[ActivitySpec]:
    """Every GE-viable, non-excluded recipe."""
    overrides = overrides or Overrides.load()

    def slots(name: str, quantity: float) -> float:
        stackable = inventory.is_stackable(name, overrides.stackable_add, overrides.stackable_remove)
        return 0 if stackable else quantity
    materials = defaultdict(list)
    for m in conn.execute(
        "SELECT m.* FROM recipe_materials m JOIN recipes r USING (recipe_key) "
        "WHERE r.ge_viable AND NOT r.excluded ORDER BY m.recipe_key, m.position"
    ):
        materials[m["recipe_key"]].append(Leg(m["name"], m["item_id"], m["quantity"], m["kind"]))
    skills = defaultdict(list)
    for s in conn.execute("SELECT recipe_key, skill, level FROM recipe_skills"):
        skills[s["recipe_key"]].append((s["skill"], s["level"]))

    specs = []
    for r in conn.execute("SELECT * FROM recipes WHERE ge_viable AND NOT excluded"):
        ticks, estimated = r["ticks"], False
        if ticks is None and r["ticks_source"] == "zero":
            ticks, estimated = settings.zero_tick_default, True
        recipe_skills = tuple(skills[r["recipe_key"]])
        if any(skill in settings.travel_skills for skill, _ in recipe_skills):
            ticks = None  # travel dominates; only an actions_per_hour override can rate it
        legs = materials[r["recipe_key"]]
        trip = inventory.actions_per_trip(
            input_slots=sum(slots(leg.name, leg.quantity) for leg in legs),
            output_slots=slots(r["output_name"], r["output_qty"]),
            tools=r["tools"],
        )
        overhead = settings.bank_ticks + settings.facility_trip_ticks.get(r["facilities"] or "", 0)
        specs.append(ActivitySpec(
            key=f"recipe:{r['recipe_key']}",
            type="recipe",
            name=r["output_name"],
            variant=r["variant"],
            wiki_page=r["page_name_sub"],
            inputs=tuple(legs),
            outputs=(Leg(r["output_name"], r["output_item_id"], r["output_qty"]),),
            ticks=ticks,
            ticks_estimated=estimated,
            efficiency=r["efficiency"],
            actions_per_trip=trip,
            trip_overhead_ticks=overhead,
            fixed_rate=r["actions_per_hour"],
            members=bool(r["members"]),
            skills=recipe_skills,
            facilities=r["facilities"],
            tools=r["tools"],
            note=r["note"],
        ))
    return specs


def alch_specs(market: Market, settings: Settings) -> list[ActivitySpec]:
    """Buy an item and cast High Level Alchemy on it (assumes a fire staff)."""
    nature = market.get(settings.nature_rune_id)
    if nature is None:
        return []
    specs = []
    for item in market.items.values():
        if not item.highalch or item.id == nature.id:
            continue
        specs.append(ActivitySpec(
            key=f"alch:{item.id}",
            type="alch",
            name=item.name,
            wiki_page=item.name,
            inputs=(Leg(item.name, item.id, 1), Leg(nature.name, nature.id, 1)),
            fixed_revenue=item.highalch,
            ticks=settings.alch_ticks,
            efficiency=settings.alch_efficiency,
            members=False,  # the spell is free-to-play; item membership is checked separately
            skills=(("Magic", 55),),
            tools="Staff of fire",
        ))
    return specs


def flip_specs(market: Market, settings: Settings) -> list[ActivitySpec]:
    """Buy with an offer at the instant-sell price, sell with an offer at the instant-buy price."""
    fresh_after = market.now - settings.stale_minutes * 60
    specs = []
    for item in market.items.values():
        if item.high is None or item.low is None or item.high <= item.low:
            continue
        # A margin is only real if both sides traded recently; one old price makes a fake spread.
        if min(item.high_time or 0, item.low_time or 0) < fresh_after:
            continue
        specs.append(ActivitySpec(
            key=f"flip:{item.id}",
            type="flip",
            name=item.name,
            wiki_page=item.name,
            inputs=(Leg(item.name, item.id, 1),),
            outputs=(Leg(item.name, item.id, 1),),
            passive=True,
            price_mode=PriceMode.PATIENT,
            members=False,  # GE trading is free-to-play; item membership is checked separately
            note="Buy and sell offers must fill; the margin can close before they do.",
        ))
    return specs


_DOSE = re.compile(r"^(?P<family>.+?) ?\((?P<dose>\d)\)$")


def potion_families(conn: sqlite3.Connection, overrides: Overrides) -> dict[str, dict[int, int]]:
    """Family name -> {dose: item id}, for potions Bob Barter can decant."""
    families: dict[str, dict[int, int]] = defaultdict(dict)
    is_potion: dict[str, bool] = defaultdict(bool)
    for row in conn.execute("SELECT id, name, examine FROM items"):
        match = _DOSE.match(row["name"])
        if not match:
            continue
        family = match["family"]
        families[family][int(match["dose"])] = row["id"]
        is_potion[family] |= "dose" in (row["examine"] or "").lower()
    return {
        family: doses for family, doses in families.items()
        if len(doses) > 1 and max(doses) <= 4
        and (is_potion[family] or family in overrides.decant_include)
        and family not in overrides.decant_exclude
        and not family.lower().endswith("mix")  # barbarian mixes can't be decanted
    }


def decant_specs(
    conn: sqlite3.Connection, market: Market, settings: Settings, overrides: Overrides | None = None
) -> list[ActivitySpec]:
    """Buy one dose size and have Bob Barter decant it into another, then sell."""
    overrides = overrides or Overrides.load()
    vial = market.get(settings.vial_id)
    specs = []
    for family, doses in potion_families(conn, overrides).items():
        for a, a_id in doses.items():
            for b, b_id in doses.items():
                if a == b or market.get(a_id) is None or market.get(b_id) is None:
                    continue
                total = math.lcm(a, b)  # doses per action
                bought, made = total // a, total // b
                inputs = [Leg(market.get(a_id).name, a_id, bought)]
                if made > bought and vial is not None:  # more potions out than in: supply the vials
                    inputs.append(Leg(vial.name, vial.id, made - bought))
                specs.append(ActivitySpec(
                    key=f"decant:{a_id}:{b_id}",
                    type="decant",
                    name=f"{family}({a}) → ({b})",
                    variant=f"{bought} × ({a}) → {made} × ({b})",
                    wiki_page="Bob Barter (herbs)",
                    inputs=tuple(inputs),
                    outputs=(Leg(market.get(b_id).name, b_id, made),),
                    passive=True,
                    members=False,
                    facilities="Bob Barter (Grand Exchange)",
                ))
    return specs


def set_specs(conn: sqlite3.Connection, market: Market) -> list[ActivitySpec]:
    """Exchange pieces for a set at the GE clerk, or a set for its pieces."""
    pieces = defaultdict(list)
    for row in conn.execute("SELECT * FROM item_sets ORDER BY set_id, position"):
        pieces[row["set_id"]].append(Leg(row["name"], row["item_id"], row["quantity"]))
    specs = []
    for set_id, legs in pieces.items():
        item = market.get(set_id)
        if item is None or any(leg.item_id is None for leg in legs):
            continue
        whole = (Leg(item.name, item.id, 1),)
        common = dict(wiki_page=item.name, passive=True, members=False, facilities="Grand Exchange clerk")
        specs.append(ActivitySpec(key=f"set:combine:{set_id}", type="set", name=item.name,
                                  variant="Combine pieces into the set", inputs=tuple(legs), outputs=whole, **common))
        specs.append(ActivitySpec(key=f"set:split:{set_id}", type="set", name=item.name,
                                  variant="Split the set into pieces", inputs=whole, outputs=tuple(legs), **common))
    return specs


def shop_units(price: int, value: int | None, delta: int, multiplier: int | None,
               stock: int | None, ge_net: float, cap: int) -> tuple[int, float]:
    """How many to buy per visit before the shop price stops being profitable, and their average cost.

    Shop prices rise as stock falls: each item bought adds `delta`/1000 of the item's value.
    """
    limit = min(stock, cap) if stock is not None else cap
    total, units = 0, 0
    for k in range(limit):
        if value and multiplier:
            unit = max(price, math.floor(value * (multiplier + delta * k) / 1000))
        else:
            unit = price + math.floor((value or 0) * delta * k / 1000)
        if unit >= ge_net:
            break
        total += unit
        units += 1
    return units, (total / units if units else 0.0)


def shop_specs(conn: sqlite3.Connection, market: Market, settings: Settings,
               overrides: Overrides | None = None) -> list[ActivitySpec]:
    """Buy from an NPC shop, hopping worlds when the price climbs, and sell on the GE."""
    from backend.engine.model import ge_tax, sell_price  # avoid a cycle at import time

    overrides = overrides or Overrides.load()
    values = {r["id"]: r["value"] for r in conn.execute("SELECT id, value FROM items")}
    specs = []
    for row in conn.execute("SELECT * FROM shop_items"):
        item = market.get(row["item_id"])
        if item is None or row["shop"] in overrides.shop_exclude or "reward" in row["shop"].lower():
            continue
        sell, _ = sell_price(item, settings.price_mode)
        if not sell:
            continue
        ge_net = sell - ge_tax(sell, settings, item.id)
        units, avg_cost = shop_units(row["price"], values.get(item.id), row["delta"], row["sell_multiplier"],
                                     row["stock"], ge_net, settings.shop_unlimited_cap)
        if units == 0:
            continue
        stackable = inventory.is_stackable(item.name, overrides.stackable_add, overrides.stackable_remove)
        hops = row["stock"] is not None  # a limited stock means hopping worlds to buy more
        if stackable:
            per_cycle = units
            cycle_ticks = (settings.shop_hop_ticks if hops else 0) + math.ceil(units / settings.shop_buy_per_tick)
            how = f"Buy {units} per world" if hops else f"Buy in batches of {units}"
        else:
            per_cycle = min(units, inventory.INVENTORY_SLOTS - 1)  # one slot for coins
            cycle_ticks = settings.shop_bank_ticks + (settings.shop_hop_ticks if hops else 0)
            how = f"Buy {per_cycle} per inventory" + (", hopping worlds each trip" if hops else "")
        rate = TICKS_PER_HOUR * per_cycle / max(1, cycle_ticks) * settings.efficiency
        specs.append(ActivitySpec(
            key=f"shop:{row['shop']}:{item.id}",
            type="shop",
            name=item.name,
            variant=row["shop"],
            wiki_page=row["shop"],
            inputs=(Leg("Coins", None, avg_cost, "coins"),),
            outputs=(Leg(item.name, item.id, 1),),
            fixed_rate=rate,
            ticks_estimated=True,
            members=bool(row["members"]),
            facilities=row["location"],
            note=f"{how} (avg {avg_cost:,.0f} gp each before the price climbs too far)."
                 + (f" Shop note: {row['notes'].strip('() ')}." if row["notes"] else ""),
        ))
    return specs
