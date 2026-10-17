import { useCallback, useEffect, useState } from 'react'

const PREFIX = '#/activity/'

function read(): string | null {
  return window.location.hash.startsWith(PREFIX)
    ? decodeURIComponent(window.location.hash.slice(PREFIX.length))
    : null
}

/** The open activity lives in the URL hash, so it can be linked and closed with Back. */
export function useHashSelection() {
  const [key, setKey] = useState<string | null>(read)
  useEffect(() => {
    const onChange = () => setKey(read())
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  const open = useCallback((next: string) => {
    window.location.hash = PREFIX + encodeURIComponent(next)
  }, [])
  const close = useCallback(() => {
    if (read() === null) return
    history.replaceState(null, '', window.location.pathname + window.location.search)
    setKey(null)
  }, [])
  return [key, open, close] as const
}
