import { useEffect, useState } from 'react'

export type View = { page: 'methods' } | { page: 'merch'; itemId: number | null }

function read(): View {
  const match = window.location.hash.match(/^#\/merch(?:\/(\d+))?/)
  return match ? { page: 'merch', itemId: match[1] ? Number(match[1]) : null } : { page: 'methods' }
}

/** Which page is showing lives in the URL hash: #/merch, #/merch/<item id>, or anything else for methods. */
export function useView() {
  const [view, setView] = useState<View>(read)
  useEffect(() => {
    const onChange = () => setView(read())
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return view
}

export const go = {
  methods: () => {
    history.replaceState(null, '', window.location.pathname)
    window.dispatchEvent(new HashChangeEvent('hashchange')) // replaceState doesn't fire it
  },
  merch: (itemId?: number) => {
    window.location.hash = itemId == null ? '#/merch' : `#/merch/${itemId}`
  },
}
