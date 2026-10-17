import type { Activity, Cap } from '../../api'
import { exact, percent } from '../../format'

const LABEL = { speed: 'Speed', buy_limit: 'Buy limit', liquidity: 'Market volume' }

/** Every limit on actions/hour as a bar; the shortest bar is the one that applies. */
export default function RateCaps({ caps, activity }: { caps: Cap[]; activity: Activity }) {
  if (caps.length === 0) return null
  const binding = Math.min(...caps.map((c) => c.actions_per_hour))
  const max = Math.max(...caps.map((c) => c.actions_per_hour))
  const sorted = [...caps].sort((a, b) => a.actions_per_hour - b.actions_per_hour)
  const applying = sorted[0]
  const legs = [...activity.inputs, ...activity.outputs]
  // The GE side of the item: a shop-bought input has the same name but no GE volume.
  const volumeLeg = applying.limit === 'liquidity'
    ? legs.find((l) => l.name === applying.item && l.kind === 'item')
    : undefined
  return (
    <>
    {volumeLeg && (
      <p className="cap-explain">
        {volumeLeg.name} trades about {exact(volumeLeg.daily_volume / 24)} per hour on the GE. Sales are capped at{' '}
        {percent(activity.assumptions.liquidity_share)} of that
        {applying.window_hours > 1 ? ` over ${applying.window_hours} hours` : ''} ({exact(applying.actions_per_hour)}/hr)
        so your own trading doesn't move the price.
        {applying.window_hours <= 1 && activity.assumptions.sell_window_hours <= 1 && ' Choose a longer "Sell within" window to spread sales out.'}
        {applying.window_hours <= 1 && activity.assumptions.sell_window_hours > 1 &&
          ' This method isn\'t steady enough to sell over a longer window (it needs to be profitable in 80% of last week\'s hours, with a margin wider than twice its normal price swing).'}
      </p>
    )}
    {activity.sell_hours != null && activity.sell_hours > 1 && (
      <p className="cap-explain">
        One hour of output takes about {activity.sell_hours.toFixed(1)} hours to sell at this volume share.
      </p>
    )}
    {applying.limit === 'buy_limit' && (
      <p className="cap-explain">
        The GE buy limit on {applying.item} (per 4 hours) allows {exact(applying.actions_per_hour)} per hour on average.
      </p>
    )}
    <ul className="caps">
      {sorted.map((c, i) => {
        const applies = c.actions_per_hour === binding
        const pct = Math.max(1, (c.actions_per_hour / max) * 100)
        return (
          <li key={i} className={applies ? 'applies' : ''}>
            <div className="cap-label">
              <span>{LABEL[c.limit]}{c.item && <span className="muted"> · {c.item}</span>}</span>
              {applies && <span className="tag info">Applies</span>}
            </div>
            <div className="cap-track" title={`${exact(c.actions_per_hour)} actions/hr`}>
              <div className="cap-rail"><div className="cap-bar" style={{ width: `${pct}%` }} /></div>
              <span className="cap-value">{exact(c.actions_per_hour)}/hr</span>
            </div>
          </li>
        )
      })}
    </ul>
    </>
  )
}
