import type { Activity, Player, PriceMode, Risk } from './api'

export interface Settings {
  mode: PriceMode
  search: string
  type: 'all' | 'recipe' | 'alch'
  skill: string
  f2pOnly: boolean
  maxRisk: Risk
  showIlliquid: boolean
  showUnrated: boolean
  onlyDoable: boolean
  playerName: string
}

export const DEFAULT_SETTINGS: Settings = {
  mode: 'instant',
  search: '',
  type: 'all',
  skill: 'all',
  f2pOnly: false,
  maxRisk: 'high',
  showIlliquid: false,
  showUnrated: false,
  onlyDoable: true,
  playerName: '',
}

const RISK_ORDER: Risk[] = ['low', 'medium', 'high']

/** Skills where the player is below the requirement, e.g. ["Herblore 63"]. */
export function missingLevels(activity: Activity, player: Player | null): string[] {
  if (!player) return []
  return activity.skills
    .filter(({ skill, level }) => (player.levels[skill.toLowerCase()] ?? 1) < level)
    .map(({ skill, level }) => `${skill} ${level}`)
}

export function applyFilters(activities: Activity[], s: Settings, player: Player | null): Activity[] {
  const search = s.search.trim().toLowerCase()
  return activities.filter((a) => {
    if (a.gp_hr == null ? !s.showUnrated : a.gp_hr <= 0) return false
    if (!s.showIlliquid && !a.liquid) return false
    if (s.type !== 'all' && a.type !== s.type) return false
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
