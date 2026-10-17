"""Tunable assumptions for the profit model (spec sections 4.2–4.7)."""

from dataclasses import dataclass, field
from enum import StrEnum

TICKS_PER_HOUR = 6000  # 0.6 s per tick
BUY_LIMIT_WINDOW_HOURS = 4


class PriceMode(StrEnum):
    INSTANT = "instant"  # buy at instant-buy (high), sell at instant-sell (low)
    PATIENT = "patient"  # buy at low, sell at high
    AVERAGE = "average"  # instant prices averaged over the latest hour


@dataclass(frozen=True)
class TaxRule:
    rate: float = 0.02
    cap: int = 5_000_000
    exempt_below: int = 50  # items selling under this price pay no tax
    exempt_items: frozenset[int] = frozenset({13190})  # Old school bond


@dataclass(frozen=True)
class VolumeTier:
    min_price: int  # tier applies to items priced at or above this
    min_daily_volume: int


@dataclass(frozen=True)
class Settings:
    price_mode: PriceMode = PriceMode.INSTANT
    efficiency: float = 0.9  # share of the hour spent acting; banking is modelled separately
    zero_tick_default: int = 2  # ticks assumed when the wiki lists 0
    bank_ticks: int = 10  # one bank trip with a preset, in ticks (~6 s)
    # Extra ticks per trip at facilities that are a walk from a bank.
    facility_trip_ticks: dict[str, int] = field(default_factory=lambda: {"Sawmill": 40})
    # Skills whose real rate is set by travel, not ticks: unranked unless overridden.
    travel_skills: frozenset[str] = frozenset({"Runecraft"})
    liquidity_share: float = 0.10  # most of an item's hourly volume we expect to trade
    # Hours you're willing to take to sell one hour's output. Above 1, sales of steady-priced
    # items may be spread over this window instead of being capped to what sells in an hour.
    sell_window_hours: float = 1.0
    slow_sell_min_consistency: float = 0.8  # profitable in at least this share of last week's hours
    slow_sell_margin_cover: float = 2.0  # and the margin covers this many times the product's weekly price swing
    stale_minutes: int = 30
    tax: TaxRule = TaxRule()
    # Checked against each item's own price; highest matching tier wins.
    volume_tiers: tuple[VolumeTier, ...] = (
        VolumeTier(0, 500),
        VolumeTier(10_000, 50),
        VolumeTier(100_000, 10),
        VolumeTier(1_000_000, 3),
    )
    low_volume_margin: float = 2.0  # flag "low volume" when below this × the threshold
    risk_roi_high: float = 0.02  # ROI under this is high risk
    risk_roi_medium: float = 0.05
    implausible_roi: float = 50.0  # flag returns above 5,000%
    margin_spike_factor: float = 2.0  # profit above this × the 24h-average profit is a spike
    # High alchemy
    alch_ticks: int = 5
    alch_efficiency: float = 1.0  # no banking needed
    nature_rune_id: int = 561
    vial_id: int = 229  # empty vial, needed when decanting into more potions
    # NPC shops (estimates: travel varies a lot by shop)
    shop_hop_ticks: int = 40  # world hop, reopen the shop and buy, ~24 s per cycle
    shop_bank_ticks: int = 100  # walk to a bank and back, ~60 s
    shop_buy_per_tick: int = 50  # "Buy 50" clicks
    shop_unlimited_cap: int = 1000  # units considered per visit when stock is unlimited
    extra: dict = field(default_factory=dict)

    def min_daily_volume(self, price: float) -> int:
        threshold = self.volume_tiers[0].min_daily_volume
        for tier in self.volume_tiers:
            if price >= tier.min_price:
                threshold = tier.min_daily_volume
        return threshold
