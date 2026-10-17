import { useState } from 'react'
import type { Player } from '../api'

interface Props {
  name: string
  onNameChange: (name: string) => void
  player: Player | null
  loading: boolean
  error: string | null
  onlyDoable: boolean
  onOnlyDoableChange: (value: boolean) => void
}

export default function PlayerBar({ name, onNameChange, player, loading, error, onlyDoable, onOnlyDoableChange }: Props) {
  // The parent remounts this bar (via `key`) when the saved name changes, which resets the draft.
  const [draft, setDraft] = useState(name)

  return (
    <section className="player-bar">
      <form className="player-form" onSubmit={(e) => { e.preventDefault(); onNameChange(draft.trim()) }}>
        <label htmlFor="player">Player</label>
        <input id="player" value={draft} maxLength={12} placeholder="RSN for your levels"
          onChange={(e) => setDraft(e.target.value)} />
        <button className="button" type="submit" disabled={loading}>{loading ? 'Loading…' : 'Load levels'}</button>
        {name && <button className="button ghost" type="button" onClick={() => onNameChange('')}>Clear</button>}
      </form>
      <div className="player-info">
        {error && <span className="error-text">{error}. Showing every method.</span>}
        {player && !error && (
          <>
            <span>Levels loaded for <b>{player.name}</b></span>
            <label className="check">
              <input type="checkbox" checked={onlyDoable} onChange={(e) => onOnlyDoableChange(e.target.checked)} />
              Only methods I can do
            </label>
          </>
        )}
        {!player && !error && !loading && <span className="muted">Load your levels to hide methods you can't do yet.</span>}
      </div>
    </section>
  )
}
