"""Merchanting: margin flips (buy offer at the instant-sell price, sell offer at the
instant-buy price), with signals that say how likely the flip is to work.

Everything comes from data the app already stores: the latest prices, the hourly snapshots
(volume on each side of the book, and a week of price history) and GE buy limits.
"""

import bisect
import statistics
from dataclasses import asdict, dataclass, field

from backend.engine.history import Series
from backend.engine.market import ItemMarket, Market
from backend.engine.model import ge_tax
from backend.engine.settings import BUY_LIMIT_WINDOW_HOURS, Settings

MIN_DAILY_VOLUME = 24  # below about one trade an hour there's no market to flip in
THIN_SIDE_PER_HOUR = 5  # fewer trades than this per hour on either side fills slowly
DEEP_SIDE_PER_HOUR = 50
WIDE_MARGIN = 0.02  # 2% after tax
THIN_MARGIN = 0.005  # under 0.5% the smallest price move wipes it out
UNUSUAL_MARGIN = 2.5  # current margin over this × the week's median margin is unusual
STEADY = 0.8  # margin existed in at least this share of last week's hours
NEAR_LOW, NEAR_HIGH = 0.2, 0.8  # position of today's price within the 7-day range
TREND = 0.03  # 24h average this far from the 7-day average counts as a trend
ONE_SIDED = 3.0  # one side trading this many times faster than the other


@dataclass
class Signal:
    key: str
    label: str
    tone: str  # good | warn | bad
    detail: str


@dataclass
class Candidate:
    item_id: int
    name: str
    icon: str | None
    members: bool
    buy_limit: int | None
    buy_price: int  # place the buy offer here (latest instant-sell price)
    sell_price: int  # place the sell offer here (latest instant-buy price)
    buy_age: int | None  # seconds since each side last traded
    sell_age: int | None
    tax: int
    margin: int  # per item, after tax
    roi: float
    sellers_per_hour: float  # instant sells: these fill your buy offer
    buyers_per_hour: float  # instant buys: these fill your sell offer
    daily_volume: int
    units_per_window: int  # per 4-hour buy-limit window
    profit_per_window: float
    capital: float  # GP tied up for one window's buys
    adjusted_profit: float  # profit per window weighted by the signals below
    confidence: str  # high | medium | low
    week_low: float | None = None
    week_high: float | None = None
    week_avg: float | None = None
    position: float | None = None  # 0 = at the 7-day low, 1 = at the 7-day high
    trend_24h: float | None = None  # 24h average vs 7-day average
    margin_steady: float | None = None  # share of last week's hours with a positive margin
    median_margin: float | None = None
    signals: list[Signal] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _week(item_id: int, series: Series, settings: Settings) -> dict:
    hours = series.get(item_id, {})
    mids, margins = [], []
    for high, low in hours.values():
        if high is not None and low is not None:
            mids.append((high + low) / 2)
            margins.append(high - ge_tax(high, settings, item_id) - low)
        elif high is not None or low is not None:
            mids.append(high if high is not None else low)
    if len(mids) < 24:
        return {}
    ordered = sorted(mids)
    newest = sorted(hours)[-24:]
    day = [(h + l) / 2 for ts in newest for h, l in [hours[ts]] if h is not None and l is not None]
    return {
        "week_low": ordered[0],
        "week_high": ordered[-1],
        "week_avg": statistics.fmean(mids),
        "ordered": ordered,
        "day_avg": statistics.fmean(day) if day else None,
        "margin_steady": sum(m > 0 for m in margins) / len(margins) if margins else None,
        "median_margin": statistics.median(margins) if margins else None,
    }


def analyse(item: ItemMarket, market: Market, series: Series, settings: Settings) -> Candidate | None:
    if item.high is None or item.low is None or item.daily_volume < MIN_DAILY_VOLUME:
        return None
    tax = ge_tax(item.high, settings, item.id)
    margin = item.high - tax - item.low
    if margin <= 0:
        return None

    # Hourly trades on each side over the last day (the snapshots split volume by side).
    sellers = (item.daily_volume - _buyers_daily(item)) / 24
    buyers = _buyers_daily(item) / 24
    fill_per_hour = settings.liquidity_share * min(sellers, buyers)  # our share of the slower side
    window_units = fill_per_hour * BUY_LIMIT_WINDOW_HOURS
    if item.buy_limit:
        window_units = min(window_units, item.buy_limit)
    units = int(window_units)
    if units < 1:
        return None

    now = market.now
    c = Candidate(
        item_id=item.id, name=item.name, icon=f"/icons/{item.id}.png" if item.icon else None,
        members=item.members, buy_limit=item.buy_limit,
        buy_price=item.low, sell_price=item.high,
        buy_age=now - item.low_time if item.low_time else None,
        sell_age=now - item.high_time if item.high_time else None,
        tax=tax, margin=margin, roi=margin / item.low,
        sellers_per_hour=sellers, buyers_per_hour=buyers, daily_volume=item.daily_volume,
        units_per_window=units, profit_per_window=units * margin, capital=units * item.low,
        adjusted_profit=0, confidence="low",
    )

    week = _week(item.id, series, settings)
    if week:
        c.week_low, c.week_high, c.week_avg = week["week_low"], week["week_high"], week["week_avg"]
        mid = (item.high + item.low) / 2
        # Percentile of today's price among the week's hourly prices; ties count as halfway, so a
        # flat week puts today mid-range rather than "at the low".
        ordered = week["ordered"]
        c.position = (bisect.bisect_left(ordered, mid) + bisect.bisect_right(ordered, mid)) / 2 / len(ordered)
        if week["day_avg"] is not None:
            c.trend_24h = week["day_avg"] / week["week_avg"] - 1
        c.margin_steady, c.median_margin = week["margin_steady"], week["median_margin"]

    _signals(c, settings)
    return c


def _buyers_daily(item: ItemMarket) -> int:
    """Units bought instantly (at the high price) in the last day."""
    return item.daily_buy_volume if item.daily_buy_volume is not None else item.daily_volume // 2


def _signals(c: Candidate, settings: Settings) -> None:
    s = c.signals
    stale_after = settings.stale_minutes * 60
    fresh = all(age is not None and age <= stale_after for age in (c.buy_age, c.sell_age))
    slower = min(c.sellers_per_hour, c.buyers_per_hour)
    unusual = c.median_margin is not None and c.median_margin > 0 and c.margin > UNUSUAL_MARGIN * c.median_margin

    if not fresh:
        s.append(Signal("stale", "Stale quote", "bad",
                        "One side hasn't traded in the last 30 minutes, so this margin may not exist any more."))
    if c.roi >= WIDE_MARGIN:
        s.append(Signal("wide", "Wide margin", "good", f"{c.roi:.1%} after tax."))
    elif c.roi < THIN_MARGIN:
        s.append(Signal("thin_margin", "Thin margin", "warn",
                        f"Only {c.roi:.2%} after tax: a tiny price move erases it."))
    if slower < THIN_SIDE_PER_HOUR:
        s.append(Signal("thin", "Thin market", "bad",
                        f"Only ~{slower:.0f} trades an hour on the slower side; offers may take a long time to fill."))
    elif slower >= DEEP_SIDE_PER_HOUR:
        s.append(Signal("liquid", "Busy market", "good", f"~{slower:,.0f}+ trades an hour on each side."))
    if c.buy_limit and c.units_per_window >= c.buy_limit:
        s.append(Signal("limit", "Fills the buy limit", "good",
                        f"Enough volume to buy the full limit of {c.buy_limit:,} every 4 hours."))
    if min(c.sellers_per_hour, c.buyers_per_hour) > 0:
        ratio = max(c.sellers_per_hour, c.buyers_per_hour) / min(c.sellers_per_hour, c.buyers_per_hour)
        if ratio >= ONE_SIDED:
            busy = "buying" if c.buyers_per_hour > c.sellers_per_hour else "selling"
            s.append(Signal("one_sided", "One-sided", "warn",
                            f"Players are mostly {busy} right now ({ratio:.0f}× the other side), so one of your offers fills slowly."))
    if c.margin_steady is not None:
        if c.margin_steady >= STEADY:
            s.append(Signal("steady", "Steady margin", "good",
                            f"A positive margin in {c.margin_steady:.0%} of last week's hours."))
        elif c.margin_steady < 0.5:
            s.append(Signal("unreliable", "Unreliable margin", "warn",
                            f"A positive margin in only {c.margin_steady:.0%} of last week's hours."))
    if unusual:
        s.append(Signal("unusual", "Unusually wide", "warn",
                        f"Today's margin is {c.margin / c.median_margin:.1f}× the week's typical {c.median_margin:,.0f} gp; it may close quickly."))
    if c.position is not None:
        if c.position <= NEAR_LOW:
            s.append(Signal("low", "Near 7-day low", "good",
                            "The price is in the bottom fifth of its weekly range: a good time to buy."))
        elif c.position >= NEAR_HIGH:
            s.append(Signal("high", "Near 7-day high", "warn",
                            "The price is in the top fifth of its weekly range; if it falls back, sell offers may not fill."))
    if c.trend_24h is not None:
        if c.trend_24h <= -TREND:
            s.append(Signal("falling", "Falling", "warn", f"The last day averaged {c.trend_24h:.1%} below the week."))
        elif c.trend_24h >= TREND:
            s.append(Signal("rising", "Rising", "good", f"The last day averaged {c.trend_24h:+.1%} above the week."))

    # Confidence and an adjusted profit to rank by: the raw profit is what's on offer, the
    # weights are how likely you are to actually get it.
    steady = c.margin_steady if c.margin_steady is not None else 0.5
    weight = (steady * (1 if fresh else 0.3) * (0.5 if unusual else 1) * (0.6 if slower < THIN_SIDE_PER_HOUR else 1)
              * min(1.0, c.roi / THIN_MARGIN))
    if c.position is not None and c.position <= NEAR_LOW:
        weight *= 1.1
    c.adjusted_profit = c.profit_per_window * weight
    if fresh and steady >= STEADY and slower >= 20 and not unusual:
        c.confidence = "high"
    elif not fresh or steady < 0.5 or slower < THIN_SIDE_PER_HOUR:
        c.confidence = "low"
    else:
        c.confidence = "medium"


def candidates(market: Market, series: Series, settings: Settings) -> list[Candidate]:
    found = [analyse(item, market, series, settings) for item in market.items.values()]
    return sorted((c for c in found if c is not None), key=lambda c: c.adjusted_profit, reverse=True)
