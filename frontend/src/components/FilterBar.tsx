import type { Risk } from '../api'
import type { Settings } from '../filters'

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
        <option value="all">All types</option>
        <option value="recipe">Processing</option>
        <option value="alch">High alchemy</option>
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
      <button className="button ghost" onClick={onReset}>Reset</button>
    </section>
  )
}
