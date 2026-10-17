import type { Activity, ActivityType, Marks, Player, PriceMode, Risk, SellHours } from './api'

/** 'active' is every method you play through; flipping is passive offer time, so it's opt-in. */
export type TypeFilter = 'active' | 'everything' | ActivityType

export const TYPE_OPTIONS: { value: TypeFilter; label: string }[] = [
  { value: 'active', label: 'All active methods' },
  { value: 'recipe', label: 'Processing' },
  { value: 'alch', label: 'High alchemy' },
  { value: 'decant', label: 'Decanting' },
  { value: 'set', label: 'Item sets' },
  { value: 'shop', label: 'NPC shops' },
  { value: 'chain', label: 'Two-step chains' },
  { value: 'flip', label: 'Flipping' },
  { value: 'everything', label: 'Everything (incl. flipping)' },
]

export const TYPE_LABEL: Record<ActivityType, string> = {
  recipe: 'Processing', alch: 'High alchemy', flip: 'GE flip', decant: 'Decanting', set: 'Item set',
  shop: 'Shop', chain: 'Chain',
}

function typeMatches(filter: TypeFilter | 'all', type: ActivityType): boolean {
  if (filter === 'everything') return true
  if (filter === 'active' || filter === 'all') return type !== 'flip' // 'all' = setting saved before flips existed
  return filter === type
}

export interface Settings {
  mode: PriceMode
  sellHours: SellHours
  search: string
  type: TypeFilter
  skill: string
  f2pOnly: boolean
  maxRisk: Risk
  showIlliquid: boolean
  showUnrated: boolean
  onlyDoable: boolean
  playerName: string
  favouritesOnly: boolean
  showHidden: boolean
  consistentOnly: boolean
  minVolume: string // as typed, e.g. "10k"; empty means no minimum
}

export const DEFAULT_SETTINGS: Settings = {
  mode: 'instant',
  sellHours: 1,
  search: '',
  type: 'active',
  skill: 'all',
  f2pOnly: false,
  maxRisk: 'high',
  showIlliquid: false,
  showUnrated: false,
  onlyDoable: true,
  playerName: '',
  favouritesOnly: false,
  showHidden: false,
  consistentOnly: false,
  minVolume: '',
}

/** "10k" -> 10000, "1.5m" -> 1500000, "2,500" -> 2500. Null when empty or not a number. */
export function parseAmount(text: string): number | null {
  const match = text.trim().toLowerCase().replace(/,/g, '').match(/^(\d+(?:\.\d+)?)\s*([kmb]?)$/)
  if (!match) return null
  const scale = { '': 1, k: 1e3, m: 1e6, b: 1e9 }[match[2] as '' | 'k' | 'm' | 'b']
  return Number(match[1]) * scale
}

/** "Consistent only" keeps methods profitable in at least this share of last week's hours. */
export const CONSISTENT_SHARE = 0.8

const RISK_ORDER: Risk[] = ['low', 'medium', 'high']

/** Skills where the player is below the requirement, e.g. ["Herblore 63"]. */
export function missingLevels(activity: Activity, player: Player | null): string[] {
  if (!player) return []
  return activity.skills
    .filter(({ skill, level }) => (player.levels[skill.toLowerCase()] ?? 1) < level)
    .map(({ skill, level }) => `${skill} ${level}`)
}

export function applyFilters(activities: Activity[], s: Settings, player: Player | null, marks: Marks): Activity[] {
  const search = s.search.trim().toLowerCase()
  const minVolume = parseAmount(s.minVolume)
  return activities.filter((a) => {
    if (minVolume != null && a.daily_volume < minVolume) return false
    const mark = marks[a.key]
    if (s.favouritesOnly && mark !== 'favourite') return false
    if (!s.showHidden && mark === 'hidden') return false
    if (a.gp_hr == null ? !s.showUnrated : a.gp_hr <= 0) return false
    if (!s.showIlliquid && !a.liquid) return false
    if (!typeMatches(s.type, a.type)) return false
    if (s.consistentOnly && (a.consistency ?? 0) < CONSISTENT_SHARE) return false
    if (s.skill !== 'all' && !a.skills.some((k) => k.skill === s.skill)) return false
    if (s.f2pOnly && !a.f2p) return false
    if (a.risk && RISK_ORDER.indexOf(a.risk) > RISK_ORDER.indexOf(s.maxRisk)) return false
    if (player && s.onlyDoable && missingLevels(a, player).length > 0) return false
    if (search && !`${a.name} ${a.variant ?? ''}`.toLowerCase().includes(search)) return false
    return true
  })
}

export function skillsIn(activities: Activity[]): string[] {
  return [...new Set(activities.flatMap((a) => a.skills.map((k) => k.skill)))].sort()
}
