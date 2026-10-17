import { useEffect, useState } from 'react'

/** useState that remembers its value in localStorage. Storage failures are ignored. */
export function usePersistentState<T extends object>(key: string, initial: T) {
  const [value, setValue] = useState<T>(() => {
    try {
      const stored = localStorage.getItem(key)
      return stored === null ? initial : { ...initial, ...JSON.parse(stored) }
    } catch {
      return initial
    }
  })
  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(value))
    } catch {
      // private mode or storage disabled: settings just won't persist
    }
  }, [key, value])
  return [value, setValue] as const
}
