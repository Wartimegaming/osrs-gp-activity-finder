"""Recipes from the OSRS Wiki `recipe` bucket, matched to GE item ids.

Only recipes that produce an item are kept (the bucket also holds things like agility
obstacles). Each recipe is marked `ge_viable` when its output and every material can be
traded on the GE (coins count as tradeable at 1 gp each).
"""

import hashlib
import json
import sqlite3
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from backend import config, db, http


@dataclass
class Overrides:
    aliases: dict[str, str] = field(default_factory=dict)
    recipes: dict[str, dict] = field(default_factory=dict)  # page_name_sub -> fields
    stackable_add: set[str] = field(default_factory=set)
    stackable_remove: set[str] = field(default_factory=set)

    @classmethod
    def load(cls, path: Path = config.OVERRIDES_PATH) -> "Overrides":
        if not path.exists():
            return cls()
        with path.open("rb") as f:
            raw = tomllib.load(f)
        stackable = raw.get("stackable", {})
        return cls(
            aliases=raw.get("aliases", {}),
            recipes={r["key"]: r for r in raw.get("recipe", [])},
            stackable_add=set(stackable.get("add", [])),
            stackable_remove=set(stackable.get("remove", [])),
        )


@dataclass
class Material:
    name: str
    quantity: float
    item_id: int | None
    kind: str  # item | coins | untradeable


@dataclass
class Skill:
    name: str
    level: int | None
    experience: float | None
    boostable: bool


@dataclass
class Recipe:
    recipe_key: str
    page_name: str
    page_name_sub: str
    variant: str | None
    output_name: str
    output_item_id: int | None
    output_qty: float
    ticks: int | None
    ticks_source: str
    ticks_raw: str | None
    members: bool
    f2p: bool
    ge_viable: bool
    tools: str | None
    facilities: str | None
    materials: list[Material]
    skills: list[Skill]
    efficiency: float | None = None
    actions_per_hour: float | None = None
    excluded: bool = False
    note: str | None = None


def fetch_all(fetch: Callable = http.get_json) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        query = (
            "bucket('recipe').select('page_name','page_name_sub','production_json')"
            f".limit({config.BUCKET_PAGE_SIZE}).offset({offset}).run()"
        )
        payload = fetch(config.WIKI_API, {"action": "bucket", "format": "json", "query": query})
        if "error" in payload:
            raise RuntimeError(f"Wiki bucket query failed: {payload['error']}")
        page = payload.get("bucket", [])
        rows.extend(page)
        if len(page) < config.BUCKET_PAGE_SIZE:
            return rows
        offset += config.BUCKET_PAGE_SIZE


def parse_ticks(raw) -> tuple[int | None, str]:
    text = str(raw).strip() if raw is not None else ""
    if text.isdigit():
        ticks = int(text)
        return (ticks, "wiki") if ticks > 0 else (None, "zero")
    return None, "unknown"


def _to_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value) -> int | None:
    number = _to_float(value)
    return int(number) if number is not None else None


def parse_row(row: dict, items: dict[str, sqlite3.Row], overrides: Overrides) -> Recipe | None:
    """Turn one bucket row into a Recipe, or None when it doesn't produce an item."""
    production = json.loads(row["production_json"])
    output = production.get("output")
    if not isinstance(output, dict) or not output.get("name"):
        return None

    def resolve(name: str) -> sqlite3.Row | None:
        return items.get(overrides.aliases.get(name, name))

    materials = []
    for m in production.get("materials") or []:
        if m.get("name") == config.COINS_NAME:
            kind, item = "coins", None
        else:
            item = resolve(m["name"])
            kind = "item" if item else "untradeable"
        materials.append(
            Material(
                name=m["name"],
                quantity=_to_float(m.get("quantity")) or 0.0,
                item_id=item["id"] if item else None,
                kind=kind,
            )
        )

    skills = [
        Skill(
            name=s["name"],
            level=_to_int(s.get("level")),
            experience=_to_float(s.get("experience")),
            boostable=str(s.get("boostable", "")).lower() == "yes",
        )
        for s in production.get("skills") or []
        if s.get("name")
    ]

    output_item = resolve(output["name"])
    members = bool(production.get("members", True))
    item_rows = [output_item] + [items.get(overrides.aliases.get(m.name, m.name)) for m in materials]
    ge_viable = (
        output_item is not None
        and bool(materials)
        and all(m.kind != "untradeable" for m in materials)
    )
    f2p = ge_viable and not members and all(not r["members"] for r in item_rows if r is not None)

    ticks, ticks_source = parse_ticks(production.get("ticks"))
    digest = hashlib.sha1(row["production_json"].encode()).hexdigest()[:10]
    recipe = Recipe(
        recipe_key=f"{row['page_name_sub']}|{digest}",
        page_name=row["page_name"],
        page_name_sub=row["page_name_sub"],
        variant=output.get("subtxt") or None,
        output_name=output["name"],
        output_item_id=output_item["id"] if output_item else None,
        output_qty=_to_float(output.get("quantity")) or 1.0,
        ticks=ticks,
        ticks_source=ticks_source,
        ticks_raw=None if production.get("ticks") is None else str(production["ticks"]),
        members=members,
        f2p=f2p,
        ge_viable=ge_viable,
        tools=production.get("tools") or None,
        facilities=production.get("facilities") or None,
        materials=materials,
        skills=skills,
    )
    _apply_override(recipe, overrides.recipes.get(recipe.page_name_sub))
    return recipe


def _apply_override(recipe: Recipe, override: dict | None) -> None:
    if not override:
        return
    if "ticks" in override:
        recipe.ticks, recipe.ticks_source = int(override["ticks"]), "override"
    recipe.efficiency = override.get("efficiency", recipe.efficiency)
    recipe.actions_per_hour = override.get("actions_per_hour", recipe.actions_per_hour)
    recipe.excluded = bool(override.get("exclude", False))
    recipe.note = override.get("note")


def refresh(
    conn: sqlite3.Connection,
    fetch: Callable = http.get_json,
    overrides: Overrides | None = None,
) -> dict:
    overrides = overrides or Overrides.load()
    items = {r["name"]: r for r in conn.execute("SELECT id, name, members FROM items")}
    if not items:
        raise RuntimeError("No items loaded; run the mapping refresh first.")

    raw = fetch_all(fetch)
    recipes = {}
    for row in raw:
        recipe = parse_row(row, items, overrides)
        if recipe is not None:
            recipes.setdefault(recipe.recipe_key, recipe)  # identical duplicate rows collapse
    recipes = list(recipes.values())
    _store(conn, recipes)
    return {
        "bucket_rows": len(raw),
        "item_recipes": len(recipes),
        "ge_viable": sum(r.ge_viable for r in recipes),
    }


def _store(conn: sqlite3.Connection, recipes: list[Recipe]) -> None:
    with conn:
        conn.execute("DELETE FROM recipes")  # cascades to materials and skills
        conn.executemany(
            """
            INSERT INTO recipes (recipe_key, page_name, page_name_sub, variant, output_name,
                output_item_id, output_qty, ticks, ticks_source, ticks_raw, efficiency,
                actions_per_hour, members, f2p, ge_viable, excluded, tools, facilities, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (r.recipe_key, r.page_name, r.page_name_sub, r.variant, r.output_name,
                 r.output_item_id, r.output_qty, r.ticks, r.ticks_source, r.ticks_raw,
                 r.efficiency, r.actions_per_hour, int(r.members), int(r.f2p), int(r.ge_viable), int(r.excluded),
                 r.tools, r.facilities, r.note)
                for r in recipes
            ],
        )
        conn.executemany(
            "INSERT INTO recipe_materials (recipe_key, position, name, item_id, kind, quantity) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (r.recipe_key, i, m.name, m.item_id, m.kind, m.quantity)
                for r in recipes
                for i, m in enumerate(r.materials)
            ],
        )
        conn.executemany(
            "INSERT OR IGNORE INTO recipe_skills (recipe_key, skill, level, experience, boostable) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (r.recipe_key, s.name, s.level, s.experience, int(s.boostable))
                for r in recipes
                for s in r.skills
            ],
        )
        db.mark_refreshed(conn, "recipes")


def unmatched_names(conn: sqlite3.Connection, limit: int = 25) -> list[sqlite3.Row]:
    """Names used by recipes that aren't GE items, most used first.

    Almost all are genuinely untradeable. Anything that *should* be on the GE belongs
    in [aliases] in overrides.toml.
    """
    return conn.execute(
        """
        SELECT name, COUNT(*) AS uses FROM (
            SELECT output_name AS name FROM recipes WHERE output_item_id IS NULL
            UNION ALL
            SELECT name FROM recipe_materials WHERE kind = 'untradeable'
        ) GROUP BY name ORDER BY uses DESC, name LIMIT ?
        """,
        (limit,),
    ).fetchall()
