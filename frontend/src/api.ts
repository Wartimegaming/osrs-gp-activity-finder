export type PriceMode = 'instant' | 'patient' | 'average'
export type ActivityType = 'recipe' | 'alch' | 'flip' | 'decant' | 'set'
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

export interface Leg {
  name: string
  item_id: number | null
  kind: 'item' | 'coins'
  quantity: number
  price: number | null
  daily_volume: number
  min_daily_volume: number
  buy_limit: number | null
  icon: string | null
  day_avg_high: number | null
  day_avg_low: number | null
}

export type Limit = 'speed' | 'buy_limit' | 'liquidity'

export interface Cap {
  limit: Limit
  actions_per_hour: number
  item: string | null
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
  caps: Cap[]
  assumptions: {
    price_mode: PriceMode
    ticks_estimated: boolean
    trip_overhead_ticks: number | null
    efficiency: number | null
    fixed_rate: number | null
    liquidity_share: number
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

export const fetchActivities = (mode: PriceMode) =>
  request<ActivitiesResponse>(`/api/activities?mode=${mode}`)
export const fetchStatus = () => request<Status>('/api/status')
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
