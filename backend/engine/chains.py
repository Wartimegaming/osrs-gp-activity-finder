"""Two-step chains: make an intermediate yourself instead of buying it.

Sand + soda ash -> molten glass -> unpowered orb. A chain is only worth listing when it beats
both of its steps done on their own (e.g. because the intermediate's buy limit or volume caps
the second step), so chains are built from evaluated recipes and filtered afterwards.
"""

from collections import defaultdict
from dataclasses import replace

from backend.engine.model import ActivitySpec, Leg, Result, actions_per_hour
from backend.engine.settings import Settings


def _merge(legs: list[Leg]) -> tuple[Leg, ...]:
    """Combine legs for the same item (or coins) so buy limits apply to the total."""
    merged: dict[tuple, Leg] = {}
    for leg in legs:
        key = (leg.kind, leg.item_id if leg.kind == "item" else leg.name)
        if key in merged:
            merged[key] = replace(merged[key], quantity=merged[key].quantity + leg.quantity)
        else:
            merged[key] = leg
    return tuple(merged.values())


def _skills(*specs: ActivitySpec) -> tuple[tuple[str, int | None], ...]:
    best: dict[str, int | None] = {}
    for spec in specs:
        for skill, level in spec.skills:
            best[skill] = max(best.get(skill) or 0, level or 0) or None
    return tuple(best.items())


def build(results: list[Result], settings: Settings) -> list[ActivitySpec]:
    """Chain specs for every recipe that uses another recipe's output, one per (recipe, intermediate)."""
    recipes = [r for r in results if r.spec.type == "recipe" and r.spec.outputs]
    producers: dict[int, list[Result]] = defaultdict(list)
    for r in recipes:
        if actions_per_hour(r.spec, settings):
            producers[r.spec.outputs[0].item_id].append(r)

    chains = []
    for second in recipes:
        speed2 = actions_per_hour(second.spec, settings)
        if not speed2:
            continue
        product = second.spec.outputs[0].item_id
        for leg in second.spec.inputs:
            if leg.kind != "item":
                continue
            for first in producers.get(leg.item_id, []):
                if first.spec.key == second.spec.key or any(l.item_id == product for l in first.spec.inputs):
                    continue  # no loops
                made = first.spec.outputs[0].quantity
                runs = leg.quantity / made  # first-step actions per second-step action
                speed1 = actions_per_hour(first.spec, settings)
                hours = runs / speed1 + 1 / speed2
                inputs = [replace(l, quantity=l.quantity * runs) for l in first.spec.inputs]
                inputs += [l for l in second.spec.inputs if l is not leg]
                via = first.spec.name + (f" ({first.spec.variant})" if first.spec.variant else "")
                chains.append(ActivitySpec(
                    key=f"chain:{first.spec.key}>{second.spec.key}",
                    type="chain",
                    name=second.spec.name,
                    variant=f"making {via} yourself",
                    wiki_page=second.spec.wiki_page,
                    inputs=_merge(inputs),
                    outputs=second.spec.outputs,
                    fixed_rate=1 / hours,
                    ticks_estimated=first.spec.ticks_estimated or second.spec.ticks_estimated,
                    members=first.spec.members or second.spec.members,
                    skills=_skills(first.spec, second.spec),
                    facilities=" then ".join(dict.fromkeys(filter(None, [first.spec.facilities, second.spec.facilities]))) or None,
                    tools=", ".join(dict.fromkeys(filter(None, [first.spec.tools, second.spec.tools]))) or None,
                    note=(f"Step 1: {via}, {made:g} per action "
                          f"({runs:.2g} actions per {second.spec.name}). Step 2: {second.spec.name}."),
                ))
    return chains


def keep_worthwhile(chains: list[Result], components: dict[str, Result]) -> list[Result]:
    """Keep chains that beat both steps alone, and only the best chain per (product, intermediate)."""
    best: dict[tuple, Result] = {}
    for chain in chains:
        if not chain.ranked or chain.gp_hr <= 0:
            continue
        first_key, second_key = chain.spec.key.removeprefix("chain:").split(">", 1)
        alone = [components[k].gp_hr or 0 for k in (first_key, second_key) if k in components]
        if chain.gp_hr <= max(alone, default=0):
            continue
        intermediate = components[first_key].spec.outputs[0].item_id if first_key in components else None
        group = (second_key, intermediate)
        if group not in best or chain.gp_hr > best[group].gp_hr:
            best[group] = chain
    return list(best.values())
