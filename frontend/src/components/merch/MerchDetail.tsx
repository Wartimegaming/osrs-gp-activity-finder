import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { fetchHistory, type MerchItem } from '../../api'
import { age, exact, gp, percent } from '../../format'
import PriceChart from '../detail/PriceChart'
import ItemIcon from '../ItemIcon'

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="stat" title={hint}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
    </div>
  )
}

const wikiUrl = (name: string) => `https://oldschool.runescape.wiki/w/${encodeURIComponent(name.replace(/ /g, '_'))}`

export default function MerchDetail({ item: m, missing, onClose }: { item: MerchItem | null; missing: boolean; onClose: () => void }) {
  const panel = useRef<HTMLDivElement>(null)
  const history = useQuery({
    queryKey: ['history', m?.item_id],
    queryFn: () => fetchHistory(m!.item_id),
    enabled: m != null,
    refetchInterval: 15 * 60_000,
  })

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    panel.current?.focus()
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside ref={panel} className="drawer" role="dialog" aria-modal="true" aria-label={m ? `${m.name} flip details` : 'Flip details'}
        tabIndex={-1} onClick={(e) => e.stopPropagation()}>
        <button className="drawer-close button ghost" onClick={onClose} aria-label="Close details">✕</button>
        {!m ? (
          <div className="empty">{missing ? 'This item no longer has a margin at current prices.' : 'Loading…'}</div>
        ) : (
          <>
            <header className="detail-head">
              <ItemIcon key={m.icon} src={m.icon} size={36} />
              <div>
                <h2>{m.name}</h2>
                <div className="muted">Margin flip · <a href={wikiUrl(m.name)} target="_blank" rel="noreferrer">Wiki ↗</a></div>
                <div className="detail-tags">
                  {!m.members && <span className="tag f2p">F2P</span>}
                  <span className={`risk ${m.confidence === 'high' ? 'low' : m.confidence === 'medium' ? 'medium' : 'high'}`}>
                    {m.confidence} confidence
                  </span>
                </div>
              </div>
            </header>

            <section className="stats">
              <Stat label="Margin each" value={gp(m.margin)} hint={m.tax > 0 ? `After ${exact(m.tax)} GE tax` : 'Tax-free item'} />
              <Stat label="Margin %" value={percent(m.roi)} />
              <Stat label="Profit / 4h" value={gp(m.profit_per_window)} hint="Margin × items per 4-hour buy-limit window" />
              <Stat label="Items / 4h" value={exact(m.units_per_window)} hint={m.buy_limit ? `Buy limit ${exact(m.buy_limit)}` : 'No known buy limit'} />
              <Stat label="Capital" value={gp(m.capital)} hint="GP tied up for one window's buys" />
              <Stat label="Score" value={gp(m.adjusted_profit)} hint="Profit per 4h weighted by margin reliability, freshness and volume: the default ranking" />
            </section>

            <section className="detail-section">
              <h3>How to flip it</h3>
              <ol className="steps">
                <li>Place a <b>buy offer for {exact(m.units_per_window)}</b> at <b>{exact(m.buy_price)}</b> each
                  ({gp(m.capital)} total). Players instant-sell about {exact(m.sellers_per_hour)} an hour, which is what fills it.</li>
                <li>As it fills, place a <b>sell offer</b> at <b>{exact(m.sell_price)}</b>. About {exact(m.buyers_per_hour)} an hour are
                  instant-bought.</li>
                <li>Each sale keeps <b>{exact(m.margin)}</b> {m.tax > 0 ? `after ${exact(m.tax)} GE tax` : '(tax-free)'}: about{' '}
                  <b>{gp(m.profit_per_window)}</b> per 4 hours.</li>
              </ol>
              <p className="muted small-print">
                Prices last traded {age(m.buy_age)} ago (buy side) and {age(m.sell_age)} ago (sell side). Margins move:
                check the live price in game before committing a lot of GP.
              </p>
            </section>

            {m.signals.length > 0 && (
              <section className="detail-section">
                <h3>Signals</h3>
                <ul className="flag-notes">
                  {m.signals.map((s) => (
                    <li key={s.key}><span className={`tag ${s.tone}`}>{s.label}</span> {s.detail}</li>
                  ))}
                </ul>
              </section>
            )}

            <section className="detail-section">
              <h3>The last 7 days</h3>
              <dl className="assumptions">
                <dt>Range</dt>
                <dd>{m.week_low != null ? `${exact(m.week_low)} – ${exact(m.week_high)} (average ${exact(m.week_avg)})` : 'Not enough history yet'}</dd>
                <dt>Latest hour</dt>
                <dd>{m.position == null ? '–'
                  : m.week_low != null && (m.buy_price + m.sell_price) / 2 < m.week_low ? "Below the week's lowest hourly average"
                  : `${percent(m.position)} of the way from the week's low to its high`}</dd>
                <dt>24h trend</dt>
                <dd>{m.trend_24h == null ? '–' : `${m.trend_24h >= 0 ? '+' : ''}${percent(m.trend_24h)} against the week's average`
                  + (m.trend_vs_market == null ? ''
                    : ` (${Math.abs(m.trend_vs_market) < 0.005 ? 'in line with the market' : `${percent(Math.abs(m.trend_vs_market))} ${m.trend_vs_market < 0 ? 'weaker' : 'stronger'} than the market`})`)}</dd>
                <dt>Margin</dt>
                <dd>{m.margin_steady != null
                  ? `Positive in ${percent(m.margin_steady)} of hours; typically ${exact(m.median_margin)} gp after tax`
                  : '–'}</dd>
              </dl>
              {history.isError ? (
                <div className="banner error">Couldn't load history: {history.error.message}</div>
              ) : (
                <PriceChart points={history.data?.item_id === m.item_id ? history.data.points : []} loading={history.isFetching} />
              )}
            </section>
          </>
        )}
      </aside>
    </div>
  )
}
