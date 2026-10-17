import type { PriceMode, Status } from '../api'
import { age } from '../format'

const MODES: { value: PriceMode; label: string; hint: string }[] = [
  { value: 'instant', label: 'Instant', hint: 'Buy at the instant-buy price, sell at the instant-sell price' },
  { value: 'patient', label: 'Patient', hint: 'Buy at the instant-sell price, sell at the instant-buy price (slower fills)' },
  { value: 'average', label: '1h average', hint: 'Instant prices averaged over the last hour' },
]

interface Props {
  mode: PriceMode
  onModeChange: (mode: PriceMode) => void
  status: Status | undefined
  refreshing: boolean
  onRefresh: () => void
}

export default function Header({ mode, onModeChange, status, refreshing, onRefresh }: Props) {
  const latest = status?.refreshed.latest
  const priceAge = status && latest ? status.now - latest : null
  const errors = status ? Object.entries(status.errors) : []
  const backfilling = status?.running.includes('backfill')

  return (
    <header className="header">
      <div className="brand">
        <img src="/favicon.svg" alt="" width={28} height={28} />
        <div>
          <h1>GP Activity Finder</h1>
          <p>Money makers ranked by live Grand Exchange prices</p>
        </div>
      </div>
      <div className="header-controls">
        <div className="segmented" role="radiogroup" aria-label="Price mode">
          {MODES.map((m) => (
            <button key={m.value} role="radio" aria-checked={mode === m.value} title={m.hint}
              className={mode === m.value ? 'active' : ''} onClick={() => onModeChange(m.value)}>
              {m.label}
            </button>
          ))}
        </div>
        <div className="status">
          <span className={`dot ${priceAge != null && priceAge < 180 ? 'live' : 'stale'}`} />
          Prices {priceAge == null ? 'not loaded' : `${age(priceAge)} old`}
          {backfilling && <span className="muted"> · loading price history…</span>}
          {status && status.snapshot_hours.day < 24 && !backfilling && (
            <span className="muted"> · {status.snapshot_hours.day}/24h volume history</span>
          )}
        </div>
        <button className="button" onClick={onRefresh} disabled={refreshing}>
          {refreshing ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>
      {errors.length > 0 && (
        <div className="banner error header-errors">
          {errors.map(([job, message]) => <div key={job}>Refresh of <b>{job}</b> failed: {message}</div>)}
        </div>
      )}
    </header>
  )
}
