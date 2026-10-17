import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'
import type { HistoryPoint } from '../../api'
import { gp } from '../../format'

// Two small multiples on one time axis: price (two lines) above, volume (bars) below.
// Never a second y-axis on the price panel.
const M = { top: 10, right: 72, left: 52, bottom: 24 }
const PRICE_H = 180
const GAP = 18
const VOLUME_H = 64

const SERIES = [
  { key: 'avg_high', label: 'Instant buy', color: 'var(--series-1)' },
  { key: 'avg_low', label: 'Instant sell', color: 'var(--series-2)' },
] as const

function niceTicks(min: number, max: number, count = 4): number[] {
  if (max <= min) return [min]
  const raw = (max - min) / count
  const mag = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw
  const ticks = []
  for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) ticks.push(v)
  return ticks
}

function linePath(points: HistoryPoint[], key: 'avg_high' | 'avg_low', x: (i: number) => number, y: (v: number) => number) {
  let d = ''
  let pen = false
  points.forEach((p, i) => {
    const v = p[key]
    // Hours with no trades are absent from the data: break the line rather than bridge the gap.
    if (i > 0 && p.ts - points[i - 1].ts > 3600) pen = false
    if (v == null) { pen = false; return }
    d += `${pen ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`
    pen = true
  })
  return d
}

const timeLabel = (ts: number) =>
  new Date(ts * 1000).toLocaleString(undefined, { weekday: 'short', hour: 'numeric', minute: '2-digit' })

export default function PriceChart({ points, loading }: { points: HistoryPoint[]; loading: boolean }) {
  const wrap = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(600)
  const [active, setActive] = useState<number | null>(null)

  useEffect(() => {
    const el = wrap.current
    if (!el) return
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(280, entry.contentRect.width)))
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  const layout = useMemo(() => {
    const plotW = width - M.left - M.right
    const n = points.length
    const t0 = points[0]?.ts ?? 0
    const span = n > 1 ? points[n - 1].ts - t0 : 0
    const x = (i: number) => M.left + (span === 0 ? plotW / 2 : ((points[i].ts - t0) / span) * plotW)
    const values = points.flatMap((p) => [p.avg_high, p.avg_low]).filter((v): v is number => v != null)
    const lo = Math.min(...values), hi = Math.max(...values)
    const pad = (hi - lo) * 0.08 || hi * 0.02 || 1
    const yTicks = niceTicks(lo - pad, hi + pad)
    const yMin = Math.min(lo - pad, yTicks[0]), yMax = Math.max(hi + pad, yTicks[yTicks.length - 1])
    const y = (v: number) => M.top + PRICE_H - ((v - yMin) / (yMax - yMin)) * PRICE_H
    const volTop = M.top + PRICE_H + GAP
    const volumes = points.map((p) => p.high_volume + p.low_volume)
    const vMax = Math.max(1, ...volumes)
    const vTicks = niceTicks(0, vMax, 2)
    const vScale = Math.max(vMax, vTicks[vTicks.length - 1])
    const vy = (v: number) => volTop + VOLUME_H - (v / vScale) * VOLUME_H
    const slot = span > 0 ? plotW / (span / 3600) : plotW
    const barW = Math.max(1, Math.min(24, slot - 2)) // 2px surface gap between bars
    // Midnight boundaries for x labels, thinned so labels never collide on narrow screens.
    const midnights: number[] = []
    points.forEach((p, i) => {
      if (new Date(p.ts * 1000).getHours() === 0 && i > 0) midnights.push(i)
    })
    const dayWidth = span > 0 ? plotW / (span / 86400) : plotW
    const every = Math.ceil(52 / dayWidth)
    const days = midnights.filter((_, k) => k % every === 0)
    return { plotW, x, y, yTicks, volTop, volumes, vy, vTicks, barW, days, height: volTop + VOLUME_H + M.bottom }
  }, [points, width])

  if (points.length === 0) {
    return <div ref={wrap} className="chart-empty">{loading ? 'Loading history…' : 'No trades recorded in this period.'}</div>
  }

  const { x, y, yTicks, volTop, volumes, vy, vTicks, barW, days, height } = layout
  const last = points.length - 1
  const ends = SERIES.map((s) => {
    for (let i = last; i >= 0; i--) {
      const v = points[i][s.key]
      if (v != null) return { ...s, value: v, y: y(v), i }
    }
    return null
  }).filter((e) => e !== null)
  // Converging end labels would need nudging off their lines; drop them and rely on the legend.
  const showEndLabels = ends.length < 2 || Math.abs(ends[0].y - ends[1].y) >= 14

  const nearest = (clientX: number) => {
    const rect = wrap.current!.getBoundingClientRect()
    const px = clientX - rect.left
    let best = 0
    points.forEach((_, i) => { if (Math.abs(x(i) - px) < Math.abs(x(best) - px)) best = i })
    return best
  }
  const onMove = (e: PointerEvent) => setActive(nearest(e.clientX))
  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'ArrowLeft') { setActive((a) => Math.max(0, (a ?? last) - 1)); e.preventDefault() }
    if (e.key === 'ArrowRight') { setActive((a) => Math.min(last, (a ?? 0) + 1)); e.preventDefault() }
    if (e.key === 'Escape') setActive(null)
  }
  const point = active != null ? points[active] : null
  // Keep the tooltip on the far side of the crosshair from where the reader is looking.
  const TIP_W = 170
  const tipLeft = active == null ? 0
    : x(active) > width / 2 ? Math.max(0, x(active) - 12 - TIP_W) : Math.min(x(active) + 12, width - TIP_W)

  return (
    <div className={`chart viz-root ${loading ? 'refetching' : ''}`}>
      <div className="chart-legend" aria-hidden="true">
        {SERIES.map((s) => (
          <span key={s.key}><i className="line-key" style={{ background: s.color }} />{s.label}</span>
        ))}
        <span><i className="bar-key" />Volume</span>
      </div>
      <div ref={wrap} className="chart-plot" tabIndex={0} onKeyDown={onKey} onBlur={() => setActive(null)}
        aria-label="Hourly price and volume over the last 7 days. Use left and right arrow keys to read values.">
        <svg width={width} height={height} role="img" onPointerMove={onMove} onPointerLeave={() => setActive(null)}>
          {/* price panel */}
          {yTicks.map((t) => (
            <g key={t}>
              <line className="grid" x1={M.left} x2={width - M.right} y1={y(t)} y2={y(t)} />
              <text className="tick" x={M.left - 8} y={y(t)} dy="0.32em" textAnchor="end">{gp(t)}</text>
            </g>
          ))}
          {SERIES.map((s) => (
            <path key={s.key} d={linePath(points, s.key, x, y)} fill="none" stroke={s.color}
              strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
          ))}
          {showEndLabels && ends.map((e) => (
            <g key={e.key}>
              <circle cx={x(e.i)} cy={e.y} r={4} fill={e.color} className="ring" />
              <text className="end-label" x={x(e.i) + 8} y={e.y} dy="0.32em">{gp(e.value)}</text>
            </g>
          ))}
          {/* volume panel */}
          {vTicks.map((t) => (
            <g key={`v${t}`}>
              <line className={t === 0 ? 'baseline' : 'grid'} x1={M.left} x2={width - M.right} y1={vy(t)} y2={vy(t)} />
              <text className="tick" x={M.left - 8} y={vy(t)} dy="0.32em" textAnchor="end">{gp(t)}</text>
            </g>
          ))}
          {volumes.map((v, i) => v > 0 && (
            <rect key={i} className={`vol ${active === i ? 'active' : ''}`} x={x(i) - barW / 2} y={vy(v)}
              width={barW} height={volTop + VOLUME_H - vy(v)} rx={barW >= 8 ? 4 : 0} />
          ))}
          {/* x axis: day boundaries */}
          {days.map((i) => (
            <g key={`d${i}`}>
              <text className="tick" x={x(i)} y={height - 6} textAnchor="middle">
                {new Date(points[i].ts * 1000).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric' })}
              </text>
            </g>
          ))}
          {/* crosshair */}
          {point && active != null && (
            <g pointerEvents="none">
              <line className="crosshair" x1={x(active)} x2={x(active)} y1={M.top} y2={volTop + VOLUME_H} />
              {SERIES.map((s) => point[s.key] != null && (
                <circle key={s.key} cx={x(active)} cy={y(point[s.key]!)} r={4} fill={s.color} className="ring" />
              ))}
            </g>
          )}
        </svg>
        {point && (
          <div className="tooltip" style={{ left: tipLeft, top: M.top }} role="status">
            <div className="tooltip-time">{timeLabel(point.ts)}</div>
            {SERIES.map((s) => (
              <div key={s.key} className="tooltip-row">
                <i className="line-key" style={{ background: s.color }} />
                <b>{point[s.key] == null ? '–' : point[s.key]!.toLocaleString()}</b>
                <span>{s.label}</span>
              </div>
            ))}
            <div className="tooltip-row">
              <i className="bar-key" />
              <b>{(point.high_volume + point.low_volume).toLocaleString()}</b>
              <span>traded</span>
            </div>
          </div>
        )}
      </div>
      <details className="chart-table">
        <summary>Show data table</summary>
        <div className="chart-table-scroll">
          <table>
            <thead><tr><th>Hour</th><th className="num">Instant buy</th><th className="num">Instant sell</th><th className="num">Volume</th></tr></thead>
            <tbody>
              {[...points].reverse().map((p) => (
                <tr key={p.ts}>
                  <td>{timeLabel(p.ts)}</td>
                  <td className="num">{p.avg_high?.toLocaleString() ?? '–'}</td>
                  <td className="num">{p.avg_low?.toLocaleString() ?? '–'}</td>
                  <td className="num">{(p.high_volume + p.low_volume).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  )
}
