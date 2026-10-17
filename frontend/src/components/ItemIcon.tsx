import { useState } from 'react'

/** A locally cached item icon; keeps its space blank if the icon hasn't been downloaded yet. */
export default function ItemIcon({ src, size }: { src: string | null; size: number }) {
  const [failed, setFailed] = useState(false)
  if (!src || failed) return <span className="icon-gap" style={{ width: size, height: size }} />
  return <img src={src} alt="" width={size} height={size} loading="lazy" onError={() => setFailed(true)} />
}
