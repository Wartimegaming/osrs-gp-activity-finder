"""Inventory-trip rate model: how many actions fit in one inventory before banking.

The wiki doesn't record stackability, so it is inferred from item names, with
corrections from the [stackable] section of overrides.toml.
"""

import math
import re

INVENTORY_SLOTS = 28

_STACKABLE = re.compile(
    r"( rune$|^coins$|arrows?\b|bolts?\b|darts?\b|javelins?\b|knife\b|knives\b|"
    r"\bfeathers?\b|\bseeds?\b|\(tablet\)|cannonballs?\b|\bnails\b|chinchompas?\b|"
    r"\btips\b|\barrowtips\b|\bshafts?\b|\btokkul\b|\bthrownaxe\b)",
    re.IGNORECASE,
)


def is_stackable(name: str, add: set[str] = frozenset(), remove: set[str] = frozenset()) -> bool:
    if name in add:
        return True
    if name in remove:
        return False
    return bool(_STACKABLE.search(name))


def actions_per_trip(input_slots: float, output_slots: float, tools: str | None) -> int | None:
    """Actions per inventory, or None when nothing takes space (no banking needed)."""
    slots = max(input_slots, output_slots)
    if slots <= 0:
        return None
    tool_count = len([t for t in (tools or "").split(",") if t.strip()])
    free = INVENTORY_SLOTS - tool_count
    return max(1, math.floor(free / slots))
