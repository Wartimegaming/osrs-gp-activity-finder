import type { Flag } from '../api'

export const FLAGS: Record<Flag, { label: string; hint: string; tone: 'warn' | 'bad' | 'info' }> = {
  margin_spike: { label: 'Spike', hint: 'Margin is far above its 24h average; may not last', tone: 'warn' },
  stale_price: { label: 'Stale', hint: 'A price used here last traded over 30 minutes ago', tone: 'warn' },
  low_volume: { label: 'Thin', hint: 'Daily volume is close to the minimum threshold', tone: 'warn' },
  illiquid: { label: 'Illiquid', hint: 'An item trades below the daily volume threshold', tone: 'bad' },
  estimated_rate: { label: 'Est. rate', hint: 'Speed is an estimate; open the method to see the assumptions', tone: 'info' },
  no_rate: { label: 'No rate', hint: 'No reliable actions/hour; add an override to rank it', tone: 'info' },
  missing_price: { label: 'No price', hint: 'An item has no recent price', tone: 'bad' },
  slow_sell: { label: 'Sells over time', hint: 'Steady price: one hour of output is sold over several hours, within your "sell within" window', tone: 'info' },
  implausible: { label: 'Check', hint: 'Return over 5,000%: usually a chance-based output in the wiki data or a bad price', tone: 'bad' },
}
