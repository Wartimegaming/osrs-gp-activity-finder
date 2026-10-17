import type { Flag } from '../api'

export const FLAGS: Record<Flag, { label: string; hint: string; tone: 'warn' | 'bad' | 'info' }> = {
  margin_spike: { label: 'Spike', hint: 'Margin is far above its 24h average; may not last', tone: 'warn' },
  stale_price: { label: 'Stale', hint: 'A price used here last traded over 30 minutes ago', tone: 'warn' },
  low_volume: { label: 'Thin', hint: 'Daily volume is close to the minimum threshold', tone: 'warn' },
  illiquid: { label: 'Illiquid', hint: 'An item trades below the daily volume threshold', tone: 'bad' },
  estimated_rate: { label: 'Est. rate', hint: 'Speed assumed (wiki lists 0 ticks; 2 ticks used)', tone: 'info' },
  no_rate: { label: 'No rate', hint: 'No reliable actions/hour; add an override to rank it', tone: 'info' },
  missing_price: { label: 'No price', hint: 'An item has no recent price', tone: 'bad' },
}
