import type { Activity } from './api'
import { exact } from './format'

/** Daily potential: what the market and buy limits allow in a day, and the play time it takes. */

export function playTime(minutes: number): string {
  if (minutes < 1) return '<1 min'
  if (minutes < 90) return `${Math.round(minutes)} min`
  return `${(minutes / 60).toFixed(minutes < 600 ? 1 : 0)} h`
}

export function dailyHint(a: Activity): string {
  if (a.daily_units == null || a.daily_limit == null) return ''
  const why = a.daily_limit.limit === 'liquidity' ? `10% of ${a.daily_limit.item}'s daily GE volume`
    : a.daily_limit.limit === 'buy_limit' ? `${a.daily_limit.item}'s buy limit over six 4-hour windows`
    : 'playing all day'
  return `Up to ${exact(a.daily_units)} a day (${why})`
    + (a.active_minutes != null ? `, about ${playTime(a.active_minutes)} of play` : '')
}
