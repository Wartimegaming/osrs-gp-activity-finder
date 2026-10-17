"""Builds ActivitySpecs for each activity type from the database and market."""

import sqlite3
from collections import defaultdict

from backend.engine import inventory
from backend.engine.market import Market
from backend.engine.model import ActivitySpec, Leg
from backend.engine.settings import Settings
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
