import type { View } from '../useView'
import { go } from '../useView'

const PAGES = [
  { page: 'methods', label: 'Methods', hint: 'Ranked money makers: processing, alching, shops and more', icon: '⚒' },
  { page: 'merch', label: 'Merchanting', hint: 'Buy low, sell high: margin flips with buy and sell signals', icon: '⇄' },
] as const

export default function SideNav({ view }: { view: View }) {
  return (
    <nav className="side-nav" aria-label="Pages">
      {PAGES.map((p) => (
        <button key={p.page} className={view.page === p.page ? 'active' : ''} title={p.hint}
          aria-current={view.page === p.page ? 'page' : undefined}
          onClick={() => (p.page === 'merch' ? go.merch() : go.methods())}>
          <span className="nav-icon" aria-hidden="true">{p.icon}</span>
          <span>{p.label}</span>
        </button>
      ))}
    </nav>
  )
}
