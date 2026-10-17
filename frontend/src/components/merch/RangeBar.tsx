import { gp, percent } from '../../format'

/** Where today's price sits in its 7-day range: a track from low to high with a marker. */
export default function RangeBar({ low, high, position }: { low: number | null; high: number | null; position: number | null }) {
  if (low == null || high == null || position == null) return <span className="muted">–</span>
  const where = position <= 0.2 ? 'near the low' : position >= 0.8 ? 'near the high' : 'mid-range'
  return (
    <span className="range" title={`7-day range ${gp(low)}–${gp(high)}; now ${where} (${percent(position)} of the way up)`}>
      <span className="range-track">
        <span className="range-marker" style={{ left: `${Math.min(100, Math.max(0, position * 100))}%` }} />
      </span>
      <span className="range-label">{where}</span>
    </span>
  )
}
