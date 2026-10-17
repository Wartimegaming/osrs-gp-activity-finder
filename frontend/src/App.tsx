import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo } from 'react'
import { fetchActivities, fetchPlayer, fetchStatus, refreshPrices } from './api'
import ActivityTable from './components/ActivityTable'
import FilterBar from './components/FilterBar'
import Header from './components/Header'
import PlayerBar from './components/PlayerBar'
import { applyFilters, DEFAULT_SETTINGS, skillsIn, type Settings } from './filters'
import { usePersistentState } from './usePersistentState'

export default function App() {
  const [settings, setSettings] = usePersistentState<Settings>('gp-finder:settings', DEFAULT_SETTINGS)
  const update = (patch: Partial<Settings>) => setSettings((s) => ({ ...s, ...patch }))
  const queryClient = useQueryClient()

  const activities = useQuery({
    queryKey: ['activities', settings.mode],
    queryFn: () => fetchActivities(settings.mode),
    refetchInterval: 60_000,
    placeholderData: (previous) => previous,
  })
  const status = useQuery({ queryKey: ['status'], queryFn: fetchStatus, refetchInterval: 15_000 })
  const player = useQuery({
    queryKey: ['player', settings.playerName.toLowerCase()],
    queryFn: () => fetchPlayer(settings.playerName),
    enabled: settings.playerName.trim().length > 0,
    staleTime: 5 * 60_000,
    retry: false,
  })
  const refresh = useMutation({
    mutationFn: refreshPrices,
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['activities'] })
      queryClient.invalidateQueries({ queryKey: ['status'] })
    },
  })

  const all = useMemo(() => activities.data?.activities ?? [], [activities.data])
  const playerData = player.data ?? null
  const visible = useMemo(() => applyFilters(all, settings, playerData), [all, settings, playerData])
  const skills = useMemo(() => skillsIn(all), [all])

  return (
    <div className="page">
      <Header
        mode={settings.mode}
        onModeChange={(mode) => update({ mode })}
        status={status.data}
        refreshing={refresh.isPending || activities.isFetching}
        onRefresh={() => refresh.mutate()}
      />
      <main>
        <PlayerBar
          key={settings.playerName}
          name={settings.playerName}
          onNameChange={(playerName) => update({ playerName })}
          player={playerData}
          loading={player.isFetching}
          error={player.error?.message ?? null}
          onlyDoable={settings.onlyDoable}
          onOnlyDoableChange={(onlyDoable) => update({ onlyDoable })}
        />
        <FilterBar settings={settings} skills={skills} onChange={update} onReset={() =>
          update({ ...DEFAULT_SETTINGS, mode: settings.mode, playerName: settings.playerName })} />
        {activities.isError && <div className="banner error">Couldn't load activities: {activities.error.message}</div>}
        {activities.isPending ? (
          <div className="empty">Loading activities…</div>
        ) : (
          <ActivityTable activities={visible} total={all.length} player={playerData} />
        )}
      </main>
    </div>
  )
}
