export type PriceMode = 'instant' | 'patient' | 'average'
export type ActivityType = 'recipe' | 'alch' | 'flip' | 'decant' | 'set' | 'shop' | 'chain'
export type Mark = 'favourite' | 'hidden'
export type Marks = Record<string, Mark>
export type Risk = 'low' | 'medium' | 'high'
export type Flag =
  | 'stale_price'
  | 'low_volume'
  | 'illiquid'
  | 'margin_spike'
  | 'estimated_rate'
  | 'no_rate'
  | 'missing_price'
  | 'implausible'
  | 'slow_sell'

export interface Leg {
  name: string
  item_id: number | null
  kind: 'item' | 'coins' | 'shop'
  quantity: number
  price: number | null
  daily_volume: number
  min_daily_volume: number
  buy_limit: number | null
  icon: string | null
  day_avg_high: number | null
  day_avg_low: number | null
  source: string | null // shop name, for items bought from an NPC shop
  stock: number | null // that shop's stock per world; null = unlimited
}

export type Limit = 'speed' | 'buy_limit' | 'liquidity'

export interface Cap {
  limit: Limit
  actions_per_hour: number
  item: string | null
  window_hours: number
}

export interface Activity {
  key: string
  type: ActivityType
  name: string
  variant: string | null
  wiki_url: string | null
  icon: string | null
  skills: { skill: string; level: number }[]
  f2p: boolean
  facilities: string | null
  tools: string | null
  note: string | null
  inputs: Leg[]
  outputs: Leg[]
  fixed_revenue: number
  ticks: number | null
  actions_per_trip: number | null
  input_cost: number
  gross_revenue: number
  tax: number
  profit: number
  actions_per_hour: number | null
  effective_actions: number | null
  limiting_factor: Limit | null
  gp_hr_raw: number | null
  gp_hr: number | null
  gp_hr_risk_adjusted: number | null
  daily_volume: number
  daily_value: number
  capital_per_hour: number | null
  roi: number | null
  breakeven_move: number | null
  volatility: number | null
  risk: Risk | null
  liquid: boolean
  price_age: number | null
  flags: Flag[]
  day_profit: number | null
  consistency: number | null
  median_profit_7d: number | null
  consistency_hours: number | null
  sell_hours: number | null
  daily_units: number | null
  daily_profit: number | null
  daily_limit: { limit: Limit; item: string | null } | null
  active_minutes: number | null // play time needed for daily_units; null for passive methods
  caps: Cap[]
  assumptions: {
    price_mode: PriceMode
    ticks_estimated: boolean
    trip_overhead_ticks: number | null
    efficiency: number | null
    fixed_rate: number | null
    liquidity_share: number
    sell_window_hours: number
    override_key: string | null
  }
}

export interface HistoryPoint {
  ts: number
  avg_high: number | null
  avg_low: number | null
  high_volume: number
  low_volume: number
}

export interface History {
  item_id: number
  hours: number
  newest: number | null
  points: HistoryPoint[]
}

export interface ActivitiesResponse {
  mode: PriceMode
  generated_at: number
  count: number
  activities: Activity[]
}

export interface Status {
  now: number
  refreshed: Record<string, number | null>
  intervals: Record<string, number>
  running: string[]
  errors: Record<string, string>
  snapshot_hours: { day: number; week: number }
}

export interface Player {
  name: string
  levels: Record<string, number>
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const detail = typeof body?.detail === 'string' ? body.detail : `Request failed (${response.status})`
    throw new Error(detail)
  }
  return response.json() as Promise<T>
}

export type SellHours = 1 | 4 | 12 | 24
export const fetchActivities = (mode: PriceMode, sellHours: SellHours) =>
  request<ActivitiesResponse>(`/api/activities?mode=${mode}&sell_hours=${sellHours}`)
export const fetchStatus = () => request<Status>('/api/status')

export interface MerchSignal {
  key: string
  label: string
  tone: 'good' | 'warn' | 'bad'
  detail: string
}

export interface MerchItem {
  item_id: number
  name: string
  icon: string | null
  members: boolean
  buy_limit: number | null
  buy_price: number
  sell_price: number
  buy_age: number | null
  sell_age: number | null
  tax: number
  margin: number
  roi: number
  sellers_per_hour: number
  buyers_per_hour: number
  daily_volume: number
  units_per_window: number
  profit_per_window: number
  capital: number
  adjusted_profit: number
  confidence: 'high' | 'medium' | 'low'
  week_low: number | null
  week_high: number | null
  week_avg: number | null
  position: number | null
  trend_24h: number | null
  trend_vs_market: number | null
  margin_steady: number | null
  median_margin: number | null
  signals: MerchSignal[]
}

export interface MarketSummary {
  items: number
  median_trend: number
  near_low_share: number
  near_high_share: number
  broad_dip: boolean
}

export const fetchMerch = () =>
  request<{ generated_at: number; count: number; items: MerchItem[]; market: MarketSummary | null }>('/api/merch')
export const fetchPlayer = (name: string) =>
  request<Player>(`/api/hiscores?name=${encodeURIComponent(name)}`)
export const fetchHistory = (itemId: number, hours = 168) =>
  request<History>(`/api/history/${itemId}?hours=${hours}`)
export const fetchMarks = () => request<Marks>('/api/marks')
export const saveMark = (key: string, mark: Mark | null) =>
  request<{ key: string; mark: Mark | null }>('/api/marks', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key, mark }),
  })
export const refreshPrices = () => request<{ ok: boolean; error: string | null }>('/api/refresh', { method: 'POST' })
