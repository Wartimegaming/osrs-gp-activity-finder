import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  type SortingState,
} from '@tanstack/react-table'
import { useState } from 'react'
import type { Activity, Mark, Marks, Player } from '../api'
import { missingLevels, TYPE_LABEL } from '../filters'
import { age, exact, gp, percent } from '../format'
import { FLAGS } from './flags'
import ItemIcon from './ItemIcon'

const LIMITS = {
  speed: { label: 'Speed', hint: 'Limited by how fast you can make it' },
  buy_limit: { label: 'Buy limit', hint: 'Limited by the GE buy limit on an input (per 4 hours)' },
  liquidity: { label: 'Volume', hint: 'Limited by how much the market trades per hour' },
}

const col = createColumnHelper<Activity>()
const nullsLast = { sortUndefined: 'last' as const, sortDescFirst: true }
const num = (v: number | null) => v ?? undefined

export function StarButton({ mark, onMark, name }: { mark: Mark | undefined | null; onMark: (m: Mark | null) => void; name: string }) {
  const on = mark === 'favourite'
  return (
    <button className={`star ${on ? 'on' : ''}`} aria-pressed={on}
      aria-label={on ? `Remove ${name} from favourites` : `Add ${name} to favourites`}
      title={on ? 'Remove from favourites' : 'Add to favourites'}
      onClick={(e) => { e.stopPropagation(); onMark(on ? null : 'favourite') }}
      onKeyDown={(e) => e.stopPropagation()}>
      {on ? '★' : '☆'}
    </button>
  )
}

function columns(player: Player | null, marks: Marks, onMark: (key: string, mark: Mark | null) => void) {
  return [
    col.accessor('name', {
      header: 'Activity',
      sortDescFirst: false,
      cell: ({ row: { original: a } }) => (
        <div className="activity">
          <StarButton mark={marks[a.key]} name={a.name} onMark={(m) => onMark(a.key, m)} />
          <ItemIcon key={a.icon} src={a.icon} size={24} />
          <div>
            <div className="activity-name">
              <span>{a.name}</span>
              {a.f2p && <span className="tag f2p" title="Free-to-play: recipe and every item are F2P">F2P</span>}
              {marks[a.key] === 'hidden' && <span className="tag neutral">Hidden</span>}
            </div>
            <div className="activity-sub">
              {a.type === 'recipe' ? a.variant ?? a.facilities ?? 'Processing'
                : a.type === 'alch' || a.type === 'flip' ? TYPE_LABEL[a.type]
                : `${TYPE_LABEL[a.type]} · ${a.variant}`}
            </div>
          </div>
        </div>
      ),
    }),
    col.display({
      id: 'skills',
      header: 'Requires',
      cell: ({ row: { original: a } }) => {
        if (!a.skills.length) return <span className="muted">–</span>
        const missing = new Set(missingLevels(a, player))
        return (
          <div className="skills">
            {a.skills.map(({ skill, level }) => {
              const text = `${skill} ${level}`
              return <span key={skill} className={missing.has(text) ? 'missing' : ''}>{text}</span>
            })}
          </div>
        )
      },
    }),
    col.accessor((a) => num(a.gp_hr), {
      id: 'gp_hr', header: 'GP/hr', ...nullsLast,
      cell: (c) => <span className="strong">{gp(c.getValue())}</span>,
      meta: { numeric: true, hint: 'Profit × actions/hour after buy-limit and volume caps' },
    }),
    col.accessor((a) => num(a.gp_hr_risk_adjusted), {
      id: 'risk_adj', header: 'Risk-adj', ...nullsLast, cell: (c) => gp(c.getValue()),
      meta: { numeric: true, hint: 'GP/hr scaled down when normal price swings could wipe out the margin' },
    }),
    col.accessor('profit', {
      header: 'Profit/ea', ...nullsLast, cell: (c) => gp(c.getValue()),
      meta: { numeric: true, hint: 'Profit per action after GE tax' },
    }),
    col.accessor((a) => num(a.effective_actions), {
      id: 'actions', header: 'Actions/hr', ...nullsLast, cell: (c) => exact(c.getValue()),
      meta: { numeric: true, hint: 'Actions per hour after caps' },
    }),
    col.accessor('limiting_factor', {
      header: 'Limited by', sortUndefined: 'last',
      cell: (c) => {
        const limit = c.getValue()
        return limit ? <span title={LIMITS[limit].hint}>{LIMITS[limit].label}</span> : <span className="muted">–</span>
      },
    }),
    col.accessor('daily_volume', {
      header: 'Daily vol', ...nullsLast, cell: (c) => gp(c.getValue()),
      meta: { numeric: true, hint: 'Units of the product traded in the last 24 hours' },
    }),
    col.accessor((a) => num(a.roi), {
      id: 'roi', header: 'ROI', ...nullsLast, cell: (c) => percent(c.getValue()),
      meta: { numeric: true, hint: 'Profit ÷ input cost, per action' },
    }),
    col.accessor((a) => num(a.capital_per_hour), {
      id: 'capital', header: 'Capital/hr', ...nullsLast, cell: (c) => gp(c.getValue()),
      meta: { numeric: true, hint: 'GP spent on inputs per hour' },
    }),
    col.accessor((a) => num(a.consistency), {
      id: 'consistency', header: '7-day', ...nullsLast,
      cell: (c) => {
        const a = c.row.original
        if (a.consistency == null) return <span className="muted" title="Not enough price history yet">–</span>
        const tone = a.consistency >= 0.8 ? 'good' : a.consistency >= 0.5 ? 'warn' : 'bad'
        return (
          <span className={`consistency ${tone}`}
            title={`Profitable in ${percent(a.consistency)} of ${a.consistency_hours} hours over the last 7 days; median profit ${gp(a.median_profit_7d)} each`}>
            {percent(a.consistency)}
          </span>
        )
      },
      meta: { numeric: true, hint: 'Share of the last 7 days\' hours this method was profitable' },
    }),
    col.accessor('risk', {
      header: 'Risk', sortUndefined: 'last',
      sortingFn: (a, b) => ['low', 'medium', 'high'].indexOf(a.original.risk ?? 'high') -
        ['low', 'medium', 'high'].indexOf(b.original.risk ?? 'high'),
      cell: (c) => {
        const a = c.row.original
        if (!a.risk) return <span className="muted">–</span>
        const hint = `ROI ${percent(a.roi)} · price can fall ${percent(a.breakeven_move)} before a loss · 7-day volatility ${percent(a.volatility)}`
        return <span className={`risk ${a.risk}`} title={hint}>{a.risk}</span>
      },
    }),
    col.display({
      id: 'flags', header: 'Flags',
      cell: ({ row: { original: a } }) => (
        <div className="flags">
          {a.flags.map((f) => (
            <span key={f} className={`tag ${FLAGS[f].tone}`} title={FLAGS[f].hint}>{FLAGS[f].label}</span>
          ))}
        </div>
      ),
    }),
    col.accessor((a) => num(a.price_age), {
      id: 'age', header: 'Price age', sortUndefined: 'last', cell: (c) => age(c.getValue()),
      meta: { numeric: true, hint: 'Time since the oldest price used last traded' },
    }),
  ]
}

interface Props {
  activities: Activity[]
  total: number
  player: Player | null
  selected: string | null
  onSelect: (key: string) => void
  marks: Marks
  onMark: (key: string, mark: Mark | null) => void
}

export default function ActivityTable({ activities, total, player, selected, onSelect, marks, onMark }: Props) {
  const [sorting, setSorting] = useState<SortingState>([{ id: 'gp_hr', desc: true }])
  const [pagination, setPagination] = useState({ pageIndex: 0, pageSize: 50 })
  // Filters can shrink the list under the current page; clamp instead of showing an empty page.
  const pageCount = Math.max(1, Math.ceil(activities.length / pagination.pageSize))
  const page = Math.min(pagination.pageIndex, pageCount - 1)
  const table = useReactTable({
    data: activities,
    columns: columns(player, marks, onMark),
    state: { sorting, pagination: { ...pagination, pageIndex: page } },
    onSortingChange: setSorting,
    onPaginationChange: setPagination,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    autoResetPageIndex: false,
    getRowId: (a) => a.key,
  })

  if (activities.length === 0) {
    return <div className="empty">No methods match these filters ({total} profitable in total).</div>
  }

  return (
    <section className="table-card">
      <div className="table-scroll">
        <table>
          <thead>
            {table.getHeaderGroups().map((group) => (
              <tr key={group.id}>
                {group.headers.map((header) => {
                  const meta = header.column.columnDef.meta as { numeric?: boolean; hint?: string } | undefined
                  const sorted = header.column.getIsSorted()
                  return (
                    <th key={header.id} className={meta?.numeric ? 'num' : ''} title={meta?.hint}
                      aria-sort={sorted === 'asc' ? 'ascending' : sorted === 'desc' ? 'descending' : 'none'}>
                      {header.column.getCanSort() ? (
                        <button className="sort" onClick={header.column.getToggleSortingHandler()}>
                          {flexRender(header.column.columnDef.header, header.getContext())}
                          <span className="sort-mark">{sorted === 'asc' ? '▲' : sorted === 'desc' ? '▼' : ''}</span>
                        </button>
                      ) : flexRender(header.column.columnDef.header, header.getContext())}
                    </th>
                  )
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id} tabIndex={0} aria-label={`${row.original.name}: open details`}
                className={[
                  missingLevels(row.original, player).length ? 'locked' : '',
                  row.id === selected ? 'selected' : '',
                  marks[row.id] === 'hidden' ? 'hidden-row' : '',
                ].join(' ')}
                onClick={() => onSelect(row.id)}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(row.id) } }}>
                {row.getVisibleCells().map((cell) => {
                  const meta = cell.column.columnDef.meta as { numeric?: boolean } | undefined
                  return (
                    <td key={cell.id} className={meta?.numeric ? 'num' : ''}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <footer className="table-footer">
        <span className="muted">{activities.length} of {total} profitable methods</span>
        <div className="pager">
          <button className="button ghost" onClick={() => setPagination((p) => ({ ...p, pageIndex: page - 1 }))}
            disabled={page === 0}>Previous</button>
          <span>Page {page + 1} of {pageCount}</span>
          <button className="button ghost" onClick={() => setPagination((p) => ({ ...p, pageIndex: page + 1 }))}
            disabled={page >= pageCount - 1}>Next</button>
        </div>
      </footer>
    </section>
  )
}
