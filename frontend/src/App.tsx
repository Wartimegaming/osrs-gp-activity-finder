import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo } from 'react'
import { fetchActivities, fetchMarks, fetchPlayer, fetchStatus, refreshPrices, saveMark, type Mark, type Marks } from './api'
import ActivityTable from './components/ActivityTable'
import DetailPanel from './components/detail/DetailPanel'
import FilterBar from './components/FilterBar'
import Header from './components/Header'
import PlayerBar from './components/PlayerBar'
import { applyFilters, DEFAULT_SETTINGS, skillsIn, type Settings } from './filters'
import { useHashSelection } from './useHashSelection'
import { usePersistentState } from './usePersistentState'
import type { Activity } from './api'

export default function App() {
  const [settings, setSettings] = usePersistentState<Settings>('gp-finder:settings', DEFAULT_SETTINGS)
  const update = (patch: Partial<Settings>) => setSettings((s) => ({ ...s, ...patch }))
  const queryClient = useQueryClient()

  const activities = useQuery({
    queryKey: ['activities', settings.mode, settings.sellHours],
    queryFn: () => fetchActivities(settings.mode, settings.sellHours),
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
  const marksQuery = useQuery({ queryKey: ['marks'], queryFn: fetchMarks, staleTime: Infinity })
  const marks = useMemo(() => marksQuery.data ?? {}, [marksQuery.data])
  const markMutation = useMutation({
    mutationFn: ({ key, mark }: { key: string; mark: Mark | null }) => saveMark(key, mark),
    onMutate: ({ key, mark }) => {
      // Optimistic: the star/hide responds immediately; rolled back if the save fails.
      const previous = queryClient.getQueryData<Marks>(['marks']) ?? {}
      const next = { ...previous }
      if (mark) next[key] = mark
      else delete next[key]
      queryClient.setQueryData(['marks'], next)
      return { previous }
    },
    onError: (_e, _v, context) => context && queryClient.setQueryData(['marks'], context.previous),
  })
  const setMark = (key: string, mark: Mark | null) => markMutation.mutate({ key, mark })

  const refresh = useMutation({
    mutationFn: refreshPrices,
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['activities'] })
      queryClient.invalidateQueries({ queryKey: ['status'] })
    },
  })

  const all = useMemo(() => activities.data?.activities ?? [], [activities.data])
  const playerData = player.data ?? null
  const visible = useMemo(() => applyFilters(all, settings, playerData, marks), [all, settings, playerData, marks])
  const skills = useMemo(() => skillsIn(all), [all])

  const [selectedKey, openDetail, closeDetail] = useHashSelection()
  const selected: Activity | null = selectedKey ? all.find((a) => a.key === selectedKey) ?? null : null

  return (
    <div className="page">
      <Header
        mode={settings.mode}
        onModeChange={(mode) => update({ mode })}
        sellHours={settings.sellHours}
        onSellHoursChange={(sellHours) => update({ sellHours })}
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
          update({ ...DEFAULT_SETTINGS, mode: settings.mode, sellHours: settings.sellHours, playerName: settings.playerName })} />
        {activities.isError && <div className="banner error">Couldn't load activities: {activities.error.message}</div>}
        {activities.isPending ? (
          <div className="empty">Loading activities…</div>
        ) : (
          <ActivityTable activities={visible} total={all.length} player={playerData}
            selected={selectedKey} onSelect={openDetail} marks={marks} onMark={setMark}
            updating={activities.isPlaceholderData && activities.isFetching} />
        )}
      </main>
      {selectedKey && (
        <DetailPanel activity={selected} missing={!activities.isPending && !selected}
          player={playerData} onClose={closeDetail}
          mark={selectedKey ? marks[selectedKey] ?? null : null}
          onMark={(mark) => selectedKey && setMark(selectedKey, mark)} />
      )}
    </div>
  )
}
