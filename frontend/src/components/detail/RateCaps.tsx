import type { Cap } from '../../api'
import { exact } from '../../format'

const LABEL = { speed: 'Speed', buy_limit: 'Buy limit', liquidity: 'Market volume' }

/** Every limit on actions/hour as a bar; the shortest bar is the one that applies. */
export default function RateCaps({ caps }: { caps: Cap[] }) {
  if (caps.length === 0) return null
  const binding = Math.min(...caps.map((c) => c.actions_per_hour))
  const max = Math.max(...caps.map((c) => c.actions_per_hour))
  const sorted = [...caps].sort((a, b) => a.actions_per_hour - b.actions_per_hour)
  return (
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
  )
}
