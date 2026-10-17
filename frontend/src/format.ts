export function gp(value: number | null | undefined): string {
  if (value == null) return '–'
  const abs = Math.abs(value)
  if (abs >= 1e9) return `${(value / 1e9).toFixed(2)}b`
  if (abs >= 1e6) return `${(value / 1e6).toFixed(abs >= 1e8 ? 0 : 1)}m`
  if (abs >= 1e4) return `${(value / 1e3).toFixed(abs >= 1e5 ? 0 : 1)}k`
  return Math.round(value).toLocaleString()
}

export function exact(value: number | null | undefined): string {
  return value == null ? '–' : Math.round(value).toLocaleString()
}

export function percent(value: number | null | undefined): string {
  if (value == null) return '–'
  const pct = value * 100
  return `${Math.abs(pct) >= 100 ? pct.toFixed(0) : pct.toFixed(1)}%`
}

export function age(seconds: number | null | undefined): string {
  if (seconds == null) return '–'
  if (seconds < 60) return `${Math.max(0, Math.round(seconds))}s`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h`
  return `${Math.round(seconds / 86400)}d`
}
