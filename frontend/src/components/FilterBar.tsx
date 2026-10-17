import type { Risk } from '../api'
import { parseAmount, TYPE_OPTIONS, type Settings } from '../filters'

interface Props {
  settings: Settings
  skills: string[]
  onChange: (patch: Partial<Settings>) => void
  onReset: () => void
}

export default function FilterBar({ settings: s, skills, onChange, onReset }: Props) {
  return (
    <section className="filters" aria-label="Filters">
      <input className="search" type="search" placeholder="Search items…" value={s.search}
        onChange={(e) => onChange({ search: e.target.value })} />
      <select value={s.type} onChange={(e) => onChange({ type: e.target.value as Settings['type'] })} aria-label="Type">
        {TYPE_OPTIONS.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
      </select>
      <select value={s.skill} onChange={(e) => onChange({ skill: e.target.value })} aria-label="Skill">
        <option value="all">All skills</option>
        {skills.map((skill) => <option key={skill} value={skill}>{skill}</option>)}
      </select>
      <select value={s.maxRisk} onChange={(e) => onChange({ maxRisk: e.target.value as Risk })} aria-label="Maximum risk">
        <option value="high">Any risk</option>
        <option value="medium">Low &amp; medium risk</option>
        <option value="low">Low risk only</option>
      </select>
      <label className={`volume-filter ${s.minVolume && parseAmount(s.minVolume) == null ? 'invalid' : ''}`}
        title="Only methods whose product trades at least this many a day on the GE (e.g. 500, 10k, 1.5m)">
        <span>Min daily vol</span>
        <input type="text" inputMode="decimal" placeholder="any" value={s.minVolume} size={6}
          aria-label="Minimum daily volume" onChange={(e) => onChange({ minVolume: e.target.value })} />
      </label>
      <label className="check">
        <input type="checkbox" checked={s.f2pOnly} onChange={(e) => onChange({ f2pOnly: e.target.checked })} />
        F2P only
      </label>
      <label className="check" title="Methods where an item trades below the daily volume threshold">
        <input type="checkbox" checked={s.showIlliquid} onChange={(e) => onChange({ showIlliquid: e.target.checked })} />
        Show illiquid
      </label>
      <label className="check" title="Profitable methods with no reliable rate (e.g. Runecraft, unknown ticks)">
        <input type="checkbox" checked={s.showUnrated} onChange={(e) => onChange({ showUnrated: e.target.checked })} />
        Show unrated
      </label>
      <label className="check" title="Profitable in at least 80% of the last 7 days' hours">
        <input type="checkbox" checked={s.consistentOnly} onChange={(e) => onChange({ consistentOnly: e.target.checked })} />
        Consistent only
      </label>
      <label className="check">
        <input type="checkbox" checked={s.favouritesOnly} onChange={(e) => onChange({ favouritesOnly: e.target.checked })} />
        Favourites only
      </label>
      <label className="check">
        <input type="checkbox" checked={s.showHidden} onChange={(e) => onChange({ showHidden: e.target.checked })} />
        Show hidden
      </label>
      <button className="button ghost" onClick={onReset}>Reset</button>
    </section>
  )
}
