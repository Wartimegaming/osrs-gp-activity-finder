import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { fetchHistory, type Activity, type Leg, type Mark, type Player } from '../../api'
import { missingLevels, TYPE_LABEL } from '../../filters'
import { StarButton } from '../ActivityTable'
import { age, exact, gp, percent } from '../../format'
import { FLAGS } from '../flags'
import ItemIcon from '../ItemIcon'
import PriceChart from './PriceChart'
import RateCaps from './RateCaps'

const MODE_TEXT = {
  instant: 'Instant: buy at the instant-buy price, sell at the instant-sell price.',
  patient: 'Patient: buy at the instant-sell price, sell at the instant-buy price.',
  average: '1h average: instant prices averaged over the last hour.',
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="stat" title={hint}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
    </div>
  )
}

function ItemCell({ leg }: { leg: Leg }) {
  return (
    <span className="item-cell">
      <ItemIcon key={leg.icon} src={leg.icon} size={20} />
      <span>
        {leg.name}
        {leg.source && <span className="item-source">from {leg.source} (shop price)</span>}
      </span>
    </span>
  )
}

interface Props {
  activity: Activity | null
  missing: boolean // the selected key is no longer in the current results
  player: Player | null
  onClose: () => void
  mark: Mark | null
  onMark: (mark: Mark | null) => void
}

export default function DetailPanel({ activity: a, missing, player, onClose, mark, onMark }: Props) {
  const panel = useRef<HTMLDivElement>(null)
  const chartItems = a
    ? [...a.outputs, ...a.inputs].filter((l, i, all) =>
        l.kind === 'item' && l.item_id != null && all.findIndex((o) => o.item_id === l.item_id) === i)
    : []
  const [chartItem, setChartItem] = useState<number | null>(null)
  const itemId = chartItem != null && chartItems.some((l) => l.item_id === chartItem) ? chartItem : chartItems[0]?.item_id ?? null
  const history = useQuery({
    queryKey: ['history', itemId],
    queryFn: () => fetchHistory(itemId!),
    enabled: itemId != null,
    refetchInterval: 15 * 60_000,
    placeholderData: (previous) => previous,
  })

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    panel.current?.focus()
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside ref={panel} className="drawer" role="dialog" aria-modal="true" aria-label={a ? `${a.name} details` : 'Details'}
        tabIndex={-1} onClick={(e) => e.stopPropagation()}>
        <button className="drawer-close button ghost" onClick={onClose} aria-label="Close details">✕</button>
        {!a ? (
          <div className="empty">{missing ? 'This method is no longer profitable at current prices.' : 'Loading…'}</div>
        ) : (
          <>
            <header className="detail-head">
              <ItemIcon key={a.icon} src={a.icon} size={36} />
              <div>
                <h2><StarButton mark={mark} name={a.name} onMark={onMark} /> {a.name}</h2>
                <div className="muted">
                  {a.type === 'recipe'
                    ? [...new Set([a.variant, a.facilities].filter(Boolean))].join(' · ') || 'Processing'
                    : [TYPE_LABEL[a.type], a.variant, a.facilities].filter(Boolean).join(' · ')}
                  {a.wiki_url && <> · <a href={a.wiki_url} target="_blank" rel="noreferrer">Wiki ↗</a></>}
                </div>
                <div className="detail-tags">
                  {a.f2p && <span className="tag f2p">F2P</span>}
                  <button className="button ghost small" onClick={() => onMark(mark === 'hidden' ? null : 'hidden')}>
                    {mark === 'hidden' ? 'Unhide' : 'Hide this method'}
                  </button>
                  {a.risk && <span className={`risk ${a.risk}`}>{a.risk} risk</span>}
                  {a.skills.map(({ skill, level }) => {
                    const lacking = missingLevels(a, player).includes(`${skill} ${level}`)
                    return <span key={skill} className={`tag ${lacking ? 'bad' : 'neutral'}`}>{skill} {level}</span>
                  })}
                </div>
              </div>
            </header>

            {a.flags.length > 0 && (
              <ul className="flag-notes">
                {a.flags.map((f) => (
                  <li key={f}><span className={`tag ${FLAGS[f].tone}`}>{FLAGS[f].label}</span> {FLAGS[f].hint}</li>
                ))}
              </ul>
            )}

            <section className="stats">
              <Stat label="GP/hr" value={gp(a.gp_hr)} hint="After buy-limit and volume caps" />
              <Stat label="Risk-adj GP/hr" value={gp(a.gp_hr_risk_adjusted)} hint="GP/hr scaled down when normal price swings could wipe out the margin" />
              <Stat label="Profit per action" value={gp(a.profit)} />
              <Stat label="Actions/hr" value={exact(a.effective_actions)} />
              <Stat label="ROI" value={percent(a.roi)} hint="Profit ÷ input cost" />
              <Stat label="Capital/hr" value={gp(a.capital_per_hour)} hint="GP spent on inputs per hour" />
              <Stat label="Profitable hours (7d)" value={a.consistency == null ? '–' : percent(a.consistency)}
                hint={a.consistency_hours ? `${a.consistency_hours} hours with prices; median profit ${gp(a.median_profit_7d)} each` : 'Not enough price history yet'} />
            </section>

            <section className="detail-section">
              <h3>Profit per action</h3>
              <div className="breakdown-scroll">
              <table className="breakdown">
                <thead>
                  <tr><th>Item</th><th className="num">Qty</th><th className="num">Price</th><th className="num">Total</th><th className="num">Daily vol</th><th className="num">Buy limit</th></tr>
                </thead>
                <tbody>
                  <tr className="group"><td colSpan={6}>Buy</td></tr>
                  {a.inputs.map((leg, i) => (
                    <tr key={`in${i}`}>
                      <td><ItemCell leg={leg} /></td>
                      <td className="num">{leg.quantity}</td>
                      <td className="num">{exact(leg.price)}</td>
                      <td className="num">−{exact((leg.price ?? 0) * leg.quantity)}</td>
                      <td className={`num ${leg.kind === 'item' && leg.daily_volume < leg.min_daily_volume ? 'bad-text' : ''}`}>
                        {leg.kind === 'item' ? gp(leg.daily_volume) : '–'}
                      </td>
                      <td className="num" title={leg.kind === 'shop' ? 'Shop stock per world; GE buy limits don\'t apply' : undefined}>
                        {leg.kind === 'shop'
                          ? (leg.stock == null ? 'Unlimited stock' : `${exact(leg.stock)} per world`)
                          : leg.buy_limit ? exact(leg.buy_limit) : '–'}
                      </td>
                    </tr>
                  ))}
                  <tr className="group"><td colSpan={6}>Sell</td></tr>
                  {a.outputs.map((leg, i) => (
                    <tr key={`out${i}`}>
                      <td><ItemCell leg={leg} /></td>
                      <td className="num">{leg.quantity}</td>
                      <td className="num">{exact(leg.price)}</td>
                      <td className="num">+{exact((leg.price ?? 0) * leg.quantity)}</td>
                      <td className={`num ${leg.daily_volume < leg.min_daily_volume ? 'bad-text' : ''}`}>{gp(leg.daily_volume)}</td>
                      <td className="num">–</td>
                    </tr>
                  ))}
                  {a.fixed_revenue > 0 && (
                    <tr><td>High alchemy coins</td><td className="num">1</td><td className="num">{exact(a.fixed_revenue)}</td>
                      <td className="num">+{exact(a.fixed_revenue)}</td><td /><td /></tr>
                  )}
                </tbody>
                <tfoot>
                  <tr><td colSpan={3}>GE tax (2%, max 5m per item, none under 50 gp)</td><td className="num">−{exact(a.tax)}</td><td colSpan={2} /></tr>
                  <tr className="total"><td colSpan={3}>Profit</td><td className="num">{exact(a.profit)}</td><td colSpan={2} /></tr>
                  {a.day_profit != null && (
                    <tr><td colSpan={3} className="muted">At 24h average prices</td><td className="num muted">{exact(a.day_profit)}</td><td colSpan={2} /></tr>
                  )}
                </tfoot>
              </table>
              </div>
            </section>

            <section className="detail-section">
              <h3>What limits the rate</h3>
              {a.caps.length ? <RateCaps caps={a.caps} activity={a} /> : (
                <p className="muted">No rate: {a.assumptions.override_key
                  ? <>add <code>actions_per_hour</code> for <code>{a.assumptions.override_key}</code> in <code>backend/overrides.toml</code>.</>
                  : 'the speed of this method is unknown.'}</p>
              )}
            </section>

            {chartItems.length > 0 && (
              <section className="detail-section">
                <h3>Price history · last 7 days</h3>
                {chartItems.length > 1 && (
                  <div className="segmented chart-tabs" role="tablist" aria-label="Item to chart">
                    {chartItems.map((leg) => (
                      <button key={leg.item_id} role="tab" aria-selected={leg.item_id === itemId}
                        className={leg.item_id === itemId ? 'active' : ''} onClick={() => setChartItem(leg.item_id)}>
                        {leg.name}
                      </button>
                    ))}
                  </div>
                )}
                {history.isError ? (
                  <div className="banner error">Couldn't load history: {history.error.message}</div>
                ) : (
                  <PriceChart points={history.data?.item_id === itemId ? history.data.points : []}
                    loading={history.isFetching} />
                )}
              </section>
            )}

            <section className="detail-section">
              <h3>Assumptions</h3>
              <dl className="assumptions">
                <dt>Prices</dt><dd>{MODE_TEXT[a.assumptions.price_mode]} Oldest price used last traded {age(a.price_age)} ago.</dd>
                <dt>Speed</dt>
                <dd>
                  {a.type === 'flip' || a.type === 'decant' || a.type === 'set'
                    ? 'No skilling time: limited only by buy limits and how much the market trades.'
                    : a.type === 'shop'
                      ? `Estimated: ${exact(a.assumptions.fixed_rate)} bought per hour, allowing ~24 s per world hop and ~60 s per bank trip for items that don't stack. Travel to the shop isn't included.`
                      : a.type === 'chain'
                        ? `Estimated: ${exact(a.assumptions.fixed_rate)} per hour, adding the time for both steps.`
                        : a.assumptions.fixed_rate != null
                    ? `${exact(a.assumptions.fixed_rate)} actions/hr, set in overrides.toml.`
                    : a.ticks == null
                      ? 'Unknown: the wiki has no tick count for this method.'
                      : <>
                          {a.ticks} ticks per action{a.assumptions.ticks_estimated && ' (assumed: the wiki lists 0)'}.{' '}
                          {a.actions_per_trip
                            ? `${a.actions_per_trip} actions per inventory, then ${a.assumptions.trip_overhead_ticks} ticks to bank.`
                            : 'No banking needed.'}{' '}
                          {a.assumptions.efficiency != null && `${percent(a.assumptions.efficiency)} efficiency.`}
                        </>}
                </dd>
                <dt>Market share</dt>
                <dd>At most {percent(a.assumptions.liquidity_share)} of each item's hourly trade volume.</dd>
                {a.tools && <><dt>Tools</dt><dd>{a.tools}</dd></>}
                {a.note && <><dt>Note</dt><dd>{a.note}</dd></>}
                {a.assumptions.override_key && (
                  <><dt>Override key</dt><dd><code>{a.assumptions.override_key}</code> in <code>backend/overrides.toml</code></dd></>
                )}
              </dl>
            </section>
          </>
        )}
      </aside>
    </div>
  )
}
