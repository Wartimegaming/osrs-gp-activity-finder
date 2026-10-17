"""The profit model (spec section 4): one evaluation for every activity type.

An activity buys `inputs`, sells `outputs` and may receive coins directly (`fixed_revenue`,
e.g. high alchemy). Its rate is limited by speed, GE buy limits and market liquidity.
"""

import math
from dataclasses import dataclass, field
from enum import StrEnum

from backend.engine.market import ItemMarket, Market
from backend.engine.settings import BUY_LIMIT_WINDOW_HOURS, TICKS_PER_HOUR, PriceMode, Settings


class Flag(StrEnum):
    STALE_PRICE = "stale_price"
    LOW_VOLUME = "low_volume"
    ILLIQUID = "illiquid"
    MARGIN_SPIKE = "margin_spike"
    ESTIMATED_RATE = "estimated_rate"  # ticks assumed, not from the wiki
    NO_RATE = "no_rate"  # ticks unknown, so no GP/hr
    MISSING_PRICE = "missing_price"


class Risk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Limit(StrEnum):
    SPEED = "speed"
    BUY_LIMIT = "buy_limit"
    LIQUIDITY = "liquidity"


@dataclass(frozen=True)
class Leg:
    """One item bought or sold per action."""
    name: str
    item_id: int | None
    quantity: float
    kind: str = "item"  # item | coins


@dataclass(frozen=True)
class ActivitySpec:
    key: str
    type: str  # recipe | alch
    name: str
    inputs: tuple[Leg, ...]
    outputs: tuple[Leg, ...] = ()
    fixed_revenue: float = 0.0  # coins received per action without selling anything
    ticks: int | None = None
    ticks_estimated: bool = False
    efficiency: float | None = None
    actions_per_trip: int | None = None  # None: nothing to bank, actions run back to back
    trip_overhead_ticks: int = 0  # banking and walking per trip
    fixed_rate: float | None = None  # actions/hour override; skips the tick model
    members: bool = True
    skills: tuple[tuple[str, int | None], ...] = ()
    variant: str | None = None
    facilities: str | None = None
    tools: str | None = None
    note: str | None = None


@dataclass
class PricedLeg:
    name: str
    item_id: int | None
    quantity: float
    kind: str
    price: float | None
    daily_volume: int
    min_daily_volume: int
    buy_limit: int | None = None

    @property
    def total(self) -> float | None:
        return None if self.price is None else self.price * self.quantity


@dataclass
class Result:
    spec: ActivitySpec
    inputs: list[PricedLeg]
    outputs: list[PricedLeg]
    f2p: bool
    input_cost: float | None = None
    gross_revenue: float | None = None
    tax: float | None = None
    profit: float | None = None
    actions_per_hour: float | None = None  # speed only
    effective_actions: float | None = None  # after buy-limit and liquidity caps
    limiting_factor: Limit | None = None
    gp_hr_raw: float | None = None
    gp_hr: float | None = None
    gp_hr_risk_adjusted: float | None = None
    capital_per_hour: float | None = None
    roi: float | None = None
    breakeven_move: float | None = None
    volatility: float | None = None
    risk: Risk | None = None
    liquid: bool = True
    price_age: int | None = None  # seconds since the oldest price used last traded
    flags: set[Flag] = field(default_factory=set)

    @property
    def ranked(self) -> bool:
        return self.gp_hr is not None


def ge_tax(price: float, settings: Settings) -> int:
    if price < settings.tax.exempt_below:
        return 0
    return min(math.floor(price * settings.tax.rate), settings.tax.cap)


def buy_price(item: ItemMarket, mode: PriceMode) -> tuple[float | None, int | None]:
    """Price paid per unit and when it last traded."""
    if mode is PriceMode.PATIENT:
        return item.low, item.low_time
    if mode is PriceMode.AVERAGE:
        return item.hour_avg_high, item.high_time
    return item.high, item.high_time


def sell_price(item: ItemMarket, mode: PriceMode) -> tuple[float | None, int | None]:
    if mode is PriceMode.PATIENT:
        return item.high, item.high_time
    if mode is PriceMode.AVERAGE:
        return item.hour_avg_low, item.low_time
    return item.low, item.low_time


def _day_price(item: ItemMarket, buying: bool, mode: PriceMode) -> float | None:
    """24h volume-weighted price on the same side of the book as `mode` uses."""
    use_high = buying != (mode is PriceMode.PATIENT)
    return item.day_avg_high if use_high else item.day_avg_low


def evaluate(spec: ActivitySpec, market: Market, settings: Settings) -> Result:
    mode = settings.price_mode
    inputs, outputs, trade_times = [], [], []
    day_cost = day_revenue = 0.0
    day_known = True
    item_members = []

    def price_leg(leg: Leg, buying: bool) -> PricedLeg:
        nonlocal day_cost, day_revenue, day_known
        if leg.kind == "coins":
            day_cost += leg.quantity
            return PricedLeg(leg.name, None, leg.quantity, "coins", 1.0, 0, 0)
        item = market.get(leg.item_id)
        if item is None:
            return PricedLeg(leg.name, leg.item_id, leg.quantity, leg.kind, None, 0, 0)
        item_members.append(item.members)
        price, traded = (buy_price if buying else sell_price)(item, mode)
        if traded:
            trade_times.append(traded)
        day = _day_price(item, buying, mode)
        if day is None:
            day_known = False
        elif buying:
            day_cost += day * leg.quantity
        else:
            day_revenue += (day - ge_tax(day, settings)) * leg.quantity
        return PricedLeg(
            leg.name, leg.item_id, leg.quantity, leg.kind, price, item.daily_volume,
            settings.min_daily_volume(price or 0), item.buy_limit,
        )

    inputs = [price_leg(leg, buying=True) for leg in spec.inputs]
    outputs = [price_leg(leg, buying=False) for leg in spec.outputs]
    result = Result(
        spec=spec, inputs=inputs, outputs=outputs,
        f2p=not spec.members and not any(item_members),
    )
    if trade_times:
        result.price_age = market.now - min(trade_times)
        if result.price_age > settings.stale_minutes * 60:
            result.flags.add(Flag.STALE_PRICE)

    if any(leg.price is None for leg in inputs + outputs):
        result.flags.add(Flag.MISSING_PRICE)
        return result

    # Per action
    result.input_cost = sum(leg.total for leg in inputs)
    result.tax = sum(ge_tax(leg.price, settings) * leg.quantity for leg in outputs)
    result.gross_revenue = sum(leg.total for leg in outputs) + spec.fixed_revenue
    result.profit = result.gross_revenue - result.tax - result.input_cost
    if result.input_cost > 0:
        result.roi = result.profit / result.input_cost
    if result.gross_revenue > 0:
        result.breakeven_move = result.profit / result.gross_revenue

    # Liquidity: every traded item must clear its volume threshold.
    item_legs = [leg for leg in inputs + outputs if leg.kind == "item"]
    result.liquid = all(leg.daily_volume >= leg.min_daily_volume for leg in item_legs)
    if not result.liquid:
        result.flags.add(Flag.ILLIQUID)
    elif any(leg.daily_volume < leg.min_daily_volume * settings.low_volume_margin for leg in item_legs):
        result.flags.add(Flag.LOW_VOLUME)

    # 24h comparison: is today's margin unusually wide?
    if day_known and result.profit > 0:
        day_profit = day_revenue + spec.fixed_revenue - day_cost
        if result.profit > settings.margin_spike_factor * max(day_profit, 0):
            result.flags.add(Flag.MARGIN_SPIKE)

    # Rate
    if spec.ticks_estimated:
        result.flags.add(Flag.ESTIMATED_RATE)
    result.actions_per_hour = actions_per_hour(spec, settings)
    if result.actions_per_hour is None:
        result.flags.add(Flag.NO_RATE)
        return result

    caps = [(result.actions_per_hour, Limit.SPEED)]
    for leg in inputs:
        if leg.kind == "item" and leg.buy_limit and leg.quantity > 0:
            caps.append((leg.buy_limit / BUY_LIMIT_WINDOW_HOURS / leg.quantity, Limit.BUY_LIMIT))
    for leg in item_legs:
        if leg.quantity > 0:
            hourly_volume = leg.daily_volume / 24
            caps.append((settings.liquidity_share * hourly_volume / leg.quantity, Limit.LIQUIDITY))
    result.effective_actions, result.limiting_factor = min(caps, key=lambda cap: cap[0])

    result.gp_hr_raw = result.profit * result.actions_per_hour
    result.gp_hr = result.profit * result.effective_actions
    result.capital_per_hour = result.input_cost * result.effective_actions

    # Risk (4.6). Volatility comes from what we sell; alching has none.
    sold = [market.get(leg.item_id) for leg in outputs]
    vols = [item.volatility for item in sold if item and item.volatility is not None]
    result.volatility = max(vols) if vols else None
    result.risk = _risk(result, settings)
    result.gp_hr_risk_adjusted = result.gp_hr
    if result.volatility and result.breakeven_move is not None and result.gp_hr > 0:
        result.gp_hr_risk_adjusted = result.gp_hr * max(0.0, min(1.0, result.breakeven_move / result.volatility))
    return result


def actions_per_hour(spec: ActivitySpec, settings: Settings) -> float | None:
    if spec.fixed_rate is not None:
        return spec.fixed_rate
    if not spec.ticks:
        return None
    efficiency = spec.efficiency if spec.efficiency is not None else settings.efficiency
    if spec.actions_per_trip is None:
        return TICKS_PER_HOUR / spec.ticks * efficiency
    trip_ticks = spec.actions_per_trip * spec.ticks + spec.trip_overhead_ticks
    return TICKS_PER_HOUR * spec.actions_per_trip / trip_ticks * efficiency


def _risk(result: Result, settings: Settings) -> Risk:
    roi, move, vol = result.roi, result.breakeven_move, result.volatility
    if result.profit <= 0:
        return Risk.HIGH
    if roi is not None and roi < settings.risk_roi_high:
        return Risk.HIGH
    if vol is not None and move is not None and move < vol:
        return Risk.HIGH
    if roi is not None and roi < settings.risk_roi_medium:
        return Risk.MEDIUM
    if vol is not None and move is not None and move < 2 * vol:
        return Risk.MEDIUM
    return Risk.LOW
