import {
  createColumnHelper, flexRender, getCoreRowModel, getPaginationRowModel, getSortedRowModel,
  useReactTable, type SortingState,
} from '@tanstack/react-table'
import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { fetchMerch, type MerchItem } from '../../api'
import { parseAmount } from '../../filters'
import { age, exact, gp, percent } from '../../format'
import { usePersistentState } from '../../usePersistentState'
import { go } from '../../useView'
import ItemIcon from '../ItemIcon'
import MerchDetail from './MerchDetail'
import RangeBar from './RangeBar'

interface MerchFilters {
  search: string
  minConfidence: 'any' | 'medium' | 'high'
  minVolume: string
  minRoi: string // percent, e.g. "1"
  maxPrice: string // per item, e.g. "10m"
  f2pOnly: boolean
  nearLowOnly: boolean
}

const DEFAULTS: MerchFilters = {
  search: '', minConfidence: 'medium', minVolume: '', minRoi: '', maxPrice: '', f2pOnly: false, nearLowOnly: false,
}
const CONFIDENCE = ['low', 'medium', 'high'] as const
const TONE_ORDER = ['bad', 'warn', 'good']

function applyFilters(items: MerchItem[], f: MerchFilters): MerchItem[] {
  const search = f.search.trim().toLowerCase()
  const minVolume = parseAmount(f.minVolume)
  const minRoi = parseAmount(f.minRoi)
  const maxPrice = parseAmount(f.maxPrice)
  const minLevel = f.minConfidence === 'any' ? 0 : CONFIDENCE.indexOf(f.minConfidence)
  return items.filter((m) =>
    CONFIDENCE.indexOf(m.confidence) >= minLevel
    && (minVolume == null || m.daily_volume >= minVolume)
    && (minRoi == null || m.roi * 100 >= minRoi)
    && (maxPrice == null || m.buy_price <= maxPrice)
    && (!f.f2pOnly || !m.members)
    && (!f.nearLowOnly || (m.position != null && m.position <= 0.2))
    && (!search || m.name.toLowerCase().includes(search)))
}

const col = createColumnHelper<MerchItem>()
const desc = { sortDescFirst: true, sortUndefined: 'last' as const }
const n = (v: number | null) => v ?? undefined

const COLUMNS = [
  col.accessor('name', {
    header: 'Item', sortDescFirst: false,
    cell: ({ row: { original: m } }) => (
      <div className="activity">
        <ItemIcon key={m.icon} src={m.icon} size={24} />
        <div>
          <div className="activity-name"><span>{m.name}</span>{!m.members && <span className="tag f2p">F2P</span>}</div>
          <div className="activity-sub">{m.buy_limit ? `Limit ${exact(m.buy_limit)} per 4h` : 'No known buy limit'}</div>
        </div>
      </div>
    ),
  }),
  col.accessor('buy_price', {
    header: 'Buy → Sell', ...desc,
    cell: ({ row: { original: m } }) => (
      <span className="buy-sell"><span>{exact(m.buy_price)}</span><span className="muted">→ {exact(m.sell_price)}</span></span>
    ),
    meta: { numeric: true, hint: 'Buy offer at the latest instant-sell price; sell offer at the latest instant-buy price' },
  }),
  col.accessor('margin', {
    header: 'Margin', ...desc,
    cell: ({ row: { original: m } }) => <span><b>{gp(m.margin)}</b> <span className="muted">{percent(m.roi)}</span></span>,
    meta: { numeric: true, hint: 'Per item after GE tax, and as a share of the buy price' },
  }),
  col.accessor((m) => Math.min(m.sellers_per_hour, m.buyers_per_hour), {
    id: 'trades', header: 'Trades/hr', ...desc,
    cell: ({ row: { original: m } }) => (
      <span title={`${exact(m.sellers_per_hour)} instant sells (fill your buy) · ${exact(m.buyers_per_hour)} instant buys (fill your sell)`}>
        {gp(m.sellers_per_hour)} / {gp(m.buyers_per_hour)}
      </span>
    ),
    meta: { numeric: true, hint: 'Instant sells (which fill your buy offer) / instant buys (which fill your sell offer)' },
  }),
  col.accessor('profit_per_window', {
    header: 'Profit/4h', ...desc,
    cell: ({ row: { original: m } }) => (
      <span className="buy-sell" title={`${exact(m.units_per_window)} items per 4-hour window; ${gp(m.capital)} GP tied up`}>
        <span className="strong">{gp(m.profit_per_window)}</span>
        <span className="muted">{exact(m.units_per_window)} items · {gp(m.capital)}</span>
      </span>
    ),
    meta: { numeric: true, hint: 'Margin × items you can flip per 4-hour buy-limit window, and the GP that ties up' },
  }),
  col.accessor((m) => n(m.position), {
    id: 'position', header: '7-day range', sortUndefined: 'last',
    cell: ({ row: { original: m } }) => <RangeBar low={m.week_low} high={m.week_high} position={m.position} />,
    meta: { hint: 'Where today\'s price sits between its 7-day low and high' },
  }),
  col.accessor((m) => n(m.trend_24h), {
    id: 'trend', header: '24h trend', ...desc,
    cell: (c) => {
      const v = c.getValue()
      if (v == null) return <span className="muted">–</span>
      const tone = v >= 0.03 ? 'good' : v <= -0.03 ? 'bad' : ''
      return <span className={`trend ${tone}`}>{v >= 0 ? '▲' : '▼'} {percent(Math.abs(v))}</span>
    },
    meta: { numeric: true, hint: 'The last day\'s average price against the 7-day average' },
  }),
  col.accessor((m) => CONFIDENCE.indexOf(m.confidence), {
    id: 'confidence', header: 'Confidence', ...desc,
    cell: ({ row: { original: m } }) => <span className={`risk ${m.confidence === 'high' ? 'low' : m.confidence === 'medium' ? 'medium' : 'high'}`}>{m.confidence}</span>,
    meta: { hint: 'High: fresh prices, a margin that held most of last week, and a busy market' },
  }),
  col.display({
    id: 'signals', header: 'Signals',
    cell: ({ row: { original: m } }) => {
      // The most important signal first: problems, then warnings, then positives.
      const ordered = [...m.signals].sort((a, b) => TONE_ORDER.indexOf(a.tone) - TONE_ORDER.indexOf(b.tone))
      const [top, ...rest] = ordered
      if (!top) return <span className="muted">–</span>
      return (
        <div className="flags">
          <span className={`tag ${top.tone}`} title={top.detail}>{top.label}</span>
          {rest.length > 0 && (
            <span className="tag neutral" title={rest.map((s) => `${s.label}: ${s.detail}`).join('\n')}>+{rest.length}</span>
          )}
        </div>
      )
    },
  }),
  // Hidden: the default sort, shown in the detail view.
  col.accessor('adjusted_profit', { id: 'adjusted_profit', header: 'Score', ...desc }),
]

export default function MerchView({ itemId }: { itemId: number | null }) {
  const [filters, setFilters] = usePersistentState<MerchFilters>('gp-finder:merch-filters', DEFAULTS)
  const set = (patch: Partial<MerchFilters>) => setFilters((f) => ({ ...f, ...patch }))
  const query = useQuery({ queryKey: ['merch'], queryFn: fetchMerch, refetchInterval: 60_000, placeholderData: (p) => p })
  const all = useMemo(() => query.data?.items ?? [], [query.data])
  const visible = useMemo(() => applyFilters(all, filters), [all, filters])
  const [sorting, setSorting] = useState<SortingState>([{ id: 'adjusted_profit', desc: true }])
  const [pagination, setPagination] = useState({ pageIndex: 0, pageSize: 50 })
  const pageCount = Math.max(1, Math.ceil(visible.length / pagination.pageSize))
  const page = Math.min(pagination.pageIndex, pageCount - 1)
  const table = useReactTable({
    data: visible, columns: COLUMNS,
    state: { sorting, pagination: { ...pagination, pageIndex: page }, columnVisibility: { adjusted_profit: false } },
    onSortingChange: setSorting, onPaginationChange: setPagination,
    getCoreRowModel: getCoreRowModel(), getSortedRowModel: getSortedRowModel(), getPaginationRowModel: getPaginationRowModel(),
    autoResetPageIndex: false, getRowId: (m) => String(m.item_id),
  })
  const selected = itemId != null ? all.find((m) => m.item_id === itemId) ?? null : null
  const invalid = (text: string) => (text && parseAmount(text) == null ? 'invalid' : '')

  return (
    <>
      <section className="intro">
        <h2>Merchanting</h2>
        <p className="muted">
          Margin flips: put in a buy offer at the instant-sell price, and once it fills, a sell offer at the
          instant-buy price. Ranked by a score: profit per 4-hour buy-limit window, weighted by how reliable the
          margin is (click a column to sort by it instead).
          {query.data && ` Updated ${age(Date.now() / 1000 - query.data.generated_at)} ago.`}
        </p>
      </section>
      <section className="filters" aria-label="Merchanting filters">
        <input className="search" type="search" placeholder="Search items…" value={filters.search}
          onChange={(e) => set({ search: e.target.value })} />
        <select aria-label="Minimum confidence" value={filters.minConfidence}
          onChange={(e) => set({ minConfidence: e.target.value as MerchFilters['minConfidence'] })}>
          <option value="high">High confidence only</option>
          <option value="medium">Medium confidence and up</option>
          <option value="any">Any confidence</option>
        </select>
        <label className={`volume-filter ${invalid(filters.minVolume)}`} title="Units traded per day, e.g. 500, 10k, 1.5m">
          <span>Min daily vol</span>
          <input type="text" value={filters.minVolume} placeholder="any" aria-label="Minimum daily volume"
            onChange={(e) => set({ minVolume: e.target.value })} />
        </label>
        <label className={`volume-filter ${invalid(filters.minRoi)}`} title="Minimum margin after tax, as a percentage">
          <span>Min margin %</span>
          <input type="text" value={filters.minRoi} placeholder="any" aria-label="Minimum margin percent"
            onChange={(e) => set({ minRoi: e.target.value })} />
        </label>
        <label className={`volume-filter ${invalid(filters.maxPrice)}`} title="Most you'll pay per item, e.g. 50k, 10m">
          <span>Max price</span>
          <input type="text" value={filters.maxPrice} placeholder="any" aria-label="Maximum buy price"
            onChange={(e) => set({ maxPrice: e.target.value })} />
        </label>
        <label className="check"><input type="checkbox" checked={filters.nearLowOnly}
          onChange={(e) => set({ nearLowOnly: e.target.checked })} />Near 7-day low</label>
        <label className="check"><input type="checkbox" checked={filters.f2pOnly}
          onChange={(e) => set({ f2pOnly: e.target.checked })} />F2P only</label>
        <button className="button ghost" onClick={() => setFilters(DEFAULTS)}>Reset</button>
      </section>
      {query.isError && <div className="banner error">Couldn't load merchanting data: {query.error.message}</div>}
      {query.isPending ? <div className="empty">Loading…</div> : visible.length === 0 ? (
        <div className="empty">No flips match these filters ({all.length} with a margin in total).</div>
      ) : (
        <section className="table-card merch-table">
          <div className="table-scroll">
            <table>
              <thead>
                {table.getHeaderGroups().map((g) => (
                  <tr key={g.id}>
                    {g.headers.map((h) => {
                      const meta = h.column.columnDef.meta as { numeric?: boolean; hint?: string } | undefined
                      const sorted = h.column.getIsSorted()
                      return (
                        <th key={h.id} className={meta?.numeric ? 'num' : ''} title={meta?.hint}
                          aria-sort={sorted === 'asc' ? 'ascending' : sorted === 'desc' ? 'descending' : 'none'}>
                          {h.column.getCanSort() ? (
                            <button className="sort" onClick={h.column.getToggleSortingHandler()}>
                              {flexRender(h.column.columnDef.header, h.getContext())}
                              <span className="sort-mark">{sorted === 'asc' ? '▲' : sorted === 'desc' ? '▼' : ''}</span>
                            </button>
                          ) : flexRender(h.column.columnDef.header, h.getContext())}
                        </th>
                      )
                    })}
                  </tr>
                ))}
              </thead>
              <tbody>
                {table.getRowModel().rows.map((row) => (
                  <tr key={row.id} tabIndex={0} aria-label={`${row.original.name}: open details`}
                    className={row.original.item_id === itemId ? 'selected' : ''}
                    onClick={() => go.merch(row.original.item_id)}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go.merch(row.original.item_id) } }}>
                    {row.getVisibleCells().map((cell) => {
                      const meta = cell.column.columnDef.meta as { numeric?: boolean } | undefined
                      return <td key={cell.id} className={meta?.numeric ? 'num' : ''}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <footer className="table-footer">
            <span className="muted">{visible.length} of {all.length} flips with a margin</span>
            <div className="pager">
              <button className="button ghost" disabled={page === 0} onClick={() => setPagination((p) => ({ ...p, pageIndex: page - 1 }))}>Previous</button>
              <span>Page {page + 1} of {pageCount}</span>
              <button className="button ghost" disabled={page >= pageCount - 1} onClick={() => setPagination((p) => ({ ...p, pageIndex: page + 1 }))}>Next</button>
            </div>
          </footer>
        </section>
      )}
      {itemId != null && (
        <MerchDetail item={selected} missing={!query.isPending && !selected} onClose={() => go.merch()} />
      )}
    </>
  )
}
