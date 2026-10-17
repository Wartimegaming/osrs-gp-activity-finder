# OSRS GP Activity Finder — Project Specification

**Status:** v1.0 (agreed 2026-10-17)
**Last updated:** 2026-10-17

## 1. Goal

A local application that finds Old School RuneScape money-making activities based on
**current Grand Exchange prices**, ranks them by estimated **GP per hour**, and shows them
in a web UI on `localhost`.

The focus is on "market" methods: processing items (buy materials → make product → sell),
and buying and selling on the GE. The main use case is finding obscure recipes whose product
currently sells for much more than its inputs.

### Non-goals

- Combat, bossing, slayer, raids, PvP money-making.
- Gathering methods whose income comes from drops or resources rather than the market
  (could be added later, but not in scope now).
- Automating any in-game action. This is an information tool only. No client
  integration, no botting.
- Hosting the app or supporting multiple users. It runs locally for one person.

## 2. Activity Types

Each activity is evaluated by the same model (Section 4): inputs bought, outputs sold,
time spent, constraints.

| # | Type | Example | Priority |
|---|------|---------|----------|
| A | **Recipe processing**: buy every input, craft, sell the output | Molten glass → Unpowered orb; unf potions; fletching; smithing; cooking | **MVP** |
| B | **Buy & high alch**: buy an item, cast High Level Alchemy | Rune items, battlestaves | MVP |
| C | **GE flipping**: buy at the instant-sell price, sell at the instant-buy price | Any liquid item with a wide margin | Phase 2 |
| D | **Zero-time conversions**: item sets, decanting, noting/un-noting | Armour sets ↔ pieces, potion (4) ↔ (3) | Phase 2 |
| E | **Shop → GE arbitrage**: buy from an NPC shop, sell on the GE | Feathers, runes, seeds | Phase 3 (needs shop data) |

Activities in a chain (e.g. sand + soda ash → molten glass → orb → battlestaff) are first
evaluated one step at a time. Multi-step chains come in Phase 3.

## 3. Data Sources

All data comes from the OSRS Wiki. Both APIs were verified working on 2026-10-17.

### 3.1 Live prices: `https://prices.runescape.wiki/api/v1/osrs/`

| Endpoint | Use | Refresh |
|----------|-----|---------|
| `/mapping` | Item id ↔ name, **GE buy limit**, high/low alch, members flag | Daily |
| `/latest` | Last instant-buy (`high`) and instant-sell (`low`) price and timestamp per item | Every 60 s |
| `/5m`, `/1h` | Average prices and **trade volume** per window, used for liquidity | 5 min / 1 h |
| `/24h` | Average prices and **daily trade volume** for every item in one call. Main liquidity input | Hourly |
| `/timeseries?id=&timestep=` | Price history for one item, used for detail charts | On demand |

**Wiki rules:** every request must send a descriptive `User-Agent` (project name and
contact). Fetch the bulk endpoints once and cache them. Never request item by item in a loop.

### 3.2 Recipes: OSRS Wiki Bucket API

`https://oldschool.runescape.wiki/api.php?action=bucket&format=json&query=bucket('recipe').select('page_name','production_json')...run()`

A sample record (`Unpowered orb`) contains:
- `materials[]` (name + quantity)
- `tools` (e.g. Glassblowing pipe)
- `facilities` (e.g. Furnace, Anvil)
- `skills[]` (name, level, xp, boostable)
- `ticks` (game ticks per action; sometimes missing or "Varies")
- `output` (name + quantity)
- `members`

Recipes are pulled in pages, matched to item ids by name using `/mapping`, and stored
locally. Refresh weekly, or by hand after game updates.

**Known gaps:** some recipes have no `ticks`, use non-tradeable inputs, or name items
that don't match `/mapping` exactly. These are handled by a hand-maintained
`overrides.toml` (ticks, actions/hour, exclusions, name aliases).

### 3.3 Hiscores (MVP)

`https://secure.runescape.com/m=hiscore_oldschool/index_lite.json?player=<name>` returns a
player's skill levels as JSON (verified 2026-10-17). The user enters their name in the UI and
the levels are cached locally (refresh on demand, at most every few minutes). Recipes above the
player's level are hidden by default; a toggle shows them greyed out with the missing levels.
If the lookup fails (name typo, hiscores down), the app falls back to showing everything.

## 4. Profit Model

### 4.1 Per action
```
input_cost   = Σ (material_qty × buy_price(material))
gross_output = output_qty × sell_price(output)
ge_tax       = min(floor(0.02 × sell_price), 5,000,000) per item, 0 if sell_price < 50
profit       = gross_output − output_qty × ge_tax − input_cost
```
Tax rule (2%, 5M cap, exempt under 50 gp) is kept in config because Jagex changes it.

### 4.2 Price modes (user-selectable)
- **Instant** (default, conservative): buy at `high`, sell at `low`.
- **Patient**: buy at `low`, sell at `high`. Higher profit, slower to fill.
- **Average**: use 1h average prices.

### 4.3 Rate and GP/hour
```
actions_per_hour = 6000 / ticks_per_action × efficiency   (6000 ticks per hour)
efficiency       = default 0.85 to cover banking; overridable per recipe
raw_gp_hr        = profit × actions_per_hour
```

### 4.4 Real-world limits (what keeps the ranking honest)
GP/hour is limited by whichever of these is smallest:
- **Buy limit**: max inputs you can buy per 4 hours (`/mapping.limit`) → max actions/hr.
- **Liquidity**: how much output the market absorbs. Selling is capped at a set share
  (default 10%) of the item's traded volume per hour (daily volume ÷ 24).

`effective_gp_hr = profit × min(actions_per_hour, buy_limit_cap, liquidity_cap)`

There is no bankroll cap. Capital is used as a **risk** measure instead (Section 4.6).

### 4.5 Volume filter (exclusion rule)

An item that trades once a day is not a real money maker, even with a big margin. The
**output** and **every input** must pass a daily-volume check, and the bar drops as unit
value rises:

| Output sell price | Minimum daily volume (units, from `/24h`) |
|-------------------|-------------------------------------------|
| < 10k | 500 |
| 10k – 100k | 50 |
| 100k – 1M | 10 |
| ≥ 1M | 3 |

The table lives in config so we can tune it. Activities that fail are **hidden by default**
and listed under a "Show illiquid" toggle with a red flag. Daily traded value
(`daily volume × price`) is shown next to volume so the user can judge it themselves.

### 4.7 Confidence flags
Shown next to every result:
- **Stale price**: last trade older than N minutes (default 30).
- **Low volume**: passes the 4.5 filter but is within 2× of the threshold.
- **Margin spike**: current margin far above the 24h average (could be manipulation).
- **Missing data**: ticks guessed, or no price for an input.

### 4.6 Capital and risk

Tying up a lot of GP for a small profit is risky: a small price move wipes out the profit.
For example, 100m invested to make 1m is a 1% return, so a 1% price drop loses everything.
For every activity we compute:

```
capital_per_hour = input_cost × effective_actions_per_hour     (GP tied up per hour)
roi              = profit / input_cost                          (return per action)
breakeven_move   = profit / gross_output                        (% the output price can fall
                                                                 before the action loses money)
volatility       = std-dev of output price over the last 7 days, as a %
                   (from hourly snapshots we store ourselves; /timeseries as fallback)
```

**Risk rating** (Low / Medium / High), configurable:
- **High** if `breakeven_move < volatility`, or ROI < 2%.
- **Medium** if ROI is 2–5%, or `breakeven_move < 2 × volatility`.
- **Low** otherwise.

The table shows ROI, capital per hour and the risk badge. It can sort on
**risk-adjusted GP/hr** (`effective_gp_hr × min(1, breakeven_move / volatility)`) as well as
raw GP/hr, so "100m to make 1m" methods drop down the list without being hidden.

## 5. Web UI (localhost)

### 5.1 Main table: ranked activities
Columns: Activity · Type · Skill/Level · **F2P tag** · Profit per action · Actions/hr ·
**Effective GP/hr** · Risk-adjusted GP/hr · Limiting factor (buy limit / liquidity / speed) ·
Daily volume · ROI · Capital per hour · **Risk badge** · Flags · Price age.

Controls:
- Search
- Player name box (loads hiscores, see 3.3) at the top of the page
- Filters: type, skill, "only what I can do" (on when a player is loaded), F2P only,
  risk level, show illiquid
- **Members is the default.** F2P methods are marked with an F2P tag (from the
  `members` flag on the recipe and on every input and output item); "F2P only" narrows to them.
- Price mode toggle
- Sorting on any column
- Price auto-refresh (60 s) with a "last updated" indicator

### 5.2 Detail view (click a row)
- Inputs and outputs with live prices
- Profit breakdown, including tax
- Price and volume chart (timeseries) for the output and main inputs
- Links to the wiki pages
- Assumptions used (ticks, efficiency, overrides)

### 5.3 Settings
- Default price mode, efficiency, liquidity share, staleness threshold
- Volume threshold table (4.5) and risk thresholds (4.6)
- Remembered player name
- Favourites and hidden activities

## 6. Proposed Architecture

```
┌──────────────┐   cron-like jobs   ┌──────────────────────┐
│ OSRS Wiki    │ ─────────────────▶ │ Ingest (Python)      │
│ prices + API │                    │  - prices (60s)      │
└──────────────┘                    │  - mapping (daily)   │
                                    │  - recipes (weekly)  │
                                    └─────────┬────────────┘
                                              ▼
                                    ┌──────────────────────┐
                                    │ SQLite (local cache) │
                                    └─────────┬────────────┘
                                              ▼
                                    ┌──────────────────────┐   JSON   ┌──────────────┐
                                    │ Engine + FastAPI     │ ───────▶ │ Web UI       │
                                    │ profit model, ranks  │          │ localhost    │
                                    └──────────────────────┘          └──────────────┘
```

**Recommended stack**
- **Backend:** Python 3.12, FastAPI, httpx, APScheduler (background refresh), SQLite (stdlib
  or SQLModel). Pydantic models shared by the API and the engine.
- **Frontend (decided):** React + Vite + TypeScript, TanStack Table (sortable, filterable grid),
  TanStack Query (polling and caching), and Recharts for price charts. During development
  Vite serves the UI and proxies `/api` to FastAPI. For normal use, FastAPI serves the built UI.
- **Run:** one command (`make dev` or `uv run app`) starts the API and serves the built UI
  on `http://localhost:8000`.
- **Tests:** pytest for the profit model (tax, limits, price modes), using fixed price
  snapshots so results are deterministic.

**Proposed repo layout**
```
backend/
  ingest/        prices.py, mapping.py, recipes.py
  engine/        model.py, activities/ (recipe.py, alch.py, flip.py, ...)
  api/           routes.py
  db.py, config.py
  overrides.toml
frontend/
  src/ ...
docs/
  PROJECT_SPEC.md
tests/
```

## 7. Milestones

| Milestone | Scope | Done when |
|-----------|-------|-----------|
| **M0: Spec** | This document | Spec agreed and open questions resolved |
| **M1: Data layer** | Ingest mapping, latest, 1h, 24h, recipes into SQLite; hourly price snapshots; name→id matching; overrides | `recipes` table populated; unmatched-items report < 5% |
| **M2: Engine** | Recipe and high-alch profit model, limits, volume filter, risk model, flags, unit tests | CLI prints top 25 activities by effective GP/hr with risk |
| **M3: Web UI MVP** | Ranked table, filters, F2P tag, price mode, auto-refresh, hiscores lookup | Usable at `localhost:8000` |
| **M4: Detail view** | Breakdown, charts, wiki links | Click-through works for every row |
| **M5: Phase 2** | GE flipping, item sets/decanting, favourites | |
| **M6: Phase 3** | Multi-step chains, shop arbitrage, historical "consistently profitable" score | |

## 8. Risks

- **Recipe data quality**: missing ticks and name mismatches. Mitigated by overrides and
  an unmatched-items report.
- **Ticks ≠ real rate**: banking, run time and tool switching. Mitigated by the efficiency
  factor and per-recipe overrides. Each result shows whether its rate is estimated.
- **Thin markets**: obscure items show huge margins on one or two trades. Mitigated by
  the liquidity cap, volume flags and a minimum-volume filter.
- **API etiquette**: follow the wiki's User-Agent and caching rules to avoid being blocked.

## 9. Decisions

| # | Topic | Decision (2026-10-17) |
|---|-------|------------------------|
| 1 | Frontend | React + Vite + TypeScript |
| 2 | Accounts | Members by default, with an F2P tag and an "F2P only" filter. Regular accounts only (ironmen can't use the GE) |
| 3 | Low volume | Exclude by default using a daily-volume threshold that drops as item value rises (4.5) |
| 4 | Bankroll | No bankroll cap. Capital is a risk input instead: ROI, break-even move and volatility (4.6) |
| 5 | Hiscores | In the MVP (3.3) |
| 6 | Default price mode | Instant (buy at instant-buy, sell at instant-sell) |

## 10. Open Questions

1. **Threshold defaults:** the starting values for the volume table (4.5) and risk table (4.6)
   will be tuned once real data is flowing.
