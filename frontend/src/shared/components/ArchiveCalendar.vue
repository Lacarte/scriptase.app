<script setup>
import { computed, ref } from 'vue'

defineOptions({ name: 'ArchiveCalendar' })

const props = defineProps({
  items: { type: Array, default: () => [] },
  searchQuery: { type: String, default: '' },
  timestampKey: { type: String, default: 'completed_at' },
  itemKey: { type: String, default: 'id' },
  searchKeys: {
    type: Array,
    default: () => ['name', 'title', 'project_name', 'video_name', 'id', 'project_id'],
  },
  archiveAfterHours: { type: Number, default: 48 },
  noun: { type: String, default: 'item' },
  layout: {
    type: String,
    default: 'rows',
    validator: value => ['rows', 'grid'].includes(value),
  },
  now: { type: [Number, String, Date], default: () => Date.now() },
})

const openDates = ref(new Set())

function timestamp(item) {
  const value = item?.[props.timestampKey]
  if (!value) return null
  const milliseconds = value instanceof Date ? value.getTime() : new Date(value).getTime()
  return Number.isFinite(milliseconds) ? milliseconds : null
}

function dateKey(milliseconds) {
  const date = new Date(milliseconds)
  return [
    date.getFullYear(),
    String(date.getMonth() + 1).padStart(2, '0'),
    String(date.getDate()).padStart(2, '0'),
  ].join('-')
}

function keyFor(item, index = 0) {
  return item?.[props.itemKey] || `${dateKey(timestamp(item) || 0)}-${index}`
}

function isArchived(item) {
  const milliseconds = timestamp(item)
  if (milliseconds == null) return false
  const now = props.now instanceof Date ? props.now.getTime() : new Date(props.now).getTime()
  return Number.isFinite(now) && now - milliseconds >= props.archiveAfterHours * 60 * 60 * 1000
}

const matchingItems = computed(() => {
  const query = props.searchQuery.trim().toLocaleLowerCase()
  if (!query) return props.items
  return props.items.filter(item => props.searchKeys.some(key =>
    String(item?.[key] ?? '').toLocaleLowerCase().includes(query),
  ))
})

const recentItems = computed(() => matchingItems.value.filter(item => !isArchived(item)))
const archivedItems = computed(() => matchingItems.value.filter(isArchived))

const archiveDates = computed(() => {
  const groups = new Map()
  archivedItems.value.forEach(item => {
    const milliseconds = timestamp(item)
    const key = dateKey(milliseconds)
    if (!groups.has(key)) groups.set(key, { key, milliseconds, items: [] })
    groups.get(key).items.push(item)
  })
  return [...groups.values()]
    .map(group => ({
      ...group,
      items: [...group.items].sort((a, b) => timestamp(b) - timestamp(a)),
    }))
    .sort((a, b) => b.milliseconds - a.milliseconds)
})

const shownArchiveDates = computed(() =>
  archiveDates.value.filter(group => openDates.value.has(group.key)),
)

const searching = computed(() => Boolean(props.searchQuery.trim()))

function toggleDate(key) {
  const next = new Set(openDates.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  openDates.value = next
}

function closeDate(key) {
  const next = new Set(openDates.value)
  next.delete(key)
  openDates.value = next
}

function revealItem(itemOrKey) {
  const item = typeof itemOrKey === 'object'
    ? itemOrKey
    : props.items.find((candidate, index) => keyFor(candidate, index) === itemOrKey)
  if (!item || !isArchived(item)) return false
  const next = new Set(openDates.value)
  next.add(dateKey(timestamp(item)))
  openDates.value = next
  return true
}

function dayLabel(milliseconds) {
  return new Intl.DateTimeFormat(undefined, { weekday: 'short' }).format(milliseconds).toUpperCase()
}

function monthLabel(milliseconds) {
  return new Intl.DateTimeFormat(undefined, { month: 'short' }).format(milliseconds).toUpperCase()
}

function fullDate(milliseconds) {
  return new Intl.DateTimeFormat(undefined, {
    weekday: 'long', month: 'long', day: 'numeric', year: 'numeric',
  }).format(milliseconds)
}

function plural(count) {
  return count === 1 ? props.noun : `${props.noun}s`
}

defineExpose({ revealItem })
</script>

<template>
  <div class="archive-calendar" :data-layout="layout">
    <div v-if="recentItems.length" class="archive-items recent-items">
      <slot v-for="(item, index) in recentItems" :key="keyFor(item, index)" name="item" :item="item" :archived="false" />
    </div>

    <template v-if="archivedItems.length">
      <template v-if="searching">
        <div class="archive-result-head">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
            <rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>
          </svg>
          Found in archive · {{ archivedItems.length }}
          <span class="head-line" />
        </div>
        <div class="archive-items search-results">
          <slot v-for="(item, index) in archivedItems" :key="keyFor(item, index)" name="item" :item="item" :archived="true" />
        </div>
      </template>

      <template v-else>
        <section class="archive-strip" aria-label="Archive calendar">
          <header class="archive-strip-head">
            <div class="archive-title">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
                <rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>
              </svg>
              Archive · {{ archivedItems.length }} {{ plural(archivedItems.length) }}
            </div>
            <p>Older than {{ archiveAfterHours }}h — pick a date to reveal its {{ plural(2) }}. Still searchable by name.</p>
          </header>
          <div class="calendar-cells">
            <button
              v-for="group in archiveDates"
              :key="group.key"
              type="button"
              class="calendar-cell"
              :class="{ open: openDates.has(group.key) }"
              :aria-expanded="String(openDates.has(group.key))"
              :aria-label="`${fullDate(group.milliseconds)} · ${group.items.length} ${plural(group.items.length)}`"
              @click="toggleDate(group.key)"
            >
              <span class="calendar-weekday">{{ dayLabel(group.milliseconds) }}</span>
              <span class="calendar-day">{{ new Date(group.milliseconds).getDate() }}</span>
              <span class="calendar-month">{{ monthLabel(group.milliseconds) }}</span>
              <span class="calendar-count">{{ group.items.length }}</span>
            </button>
          </div>
        </section>

        <section v-for="group in shownArchiveDates" :key="group.key" class="archive-day">
          <header class="archive-day-head">
            <span class="calendar-dot" />
            {{ fullDate(group.milliseconds) }} · {{ group.items.length }}
            <span class="head-line" />
            <button type="button" @click="closeDate(group.key)">Hide</button>
          </header>
          <div class="archive-items revealed-items">
            <slot v-for="(item, index) in group.items" :key="keyFor(item, index)" name="item" :item="item" :archived="true" />
          </div>
        </section>
      </template>
    </template>

    <slot v-if="matchingItems.length === 0" name="empty" />
  </div>
</template>

<style scoped>
.archive-calendar { display: grid; gap: 12px; min-width: 0; }
.archive-items { display: grid; gap: 10px; min-width: 0; }
[data-layout="grid"] .archive-items { grid-template-columns: repeat(auto-fill, minmax(min(280px, 100%), 1fr)); gap: 14px; }
.archive-strip { border: 1px solid var(--line); border-radius: var(--r); background: var(--panel-grad); overflow: hidden; }
.archive-strip-head { padding: 12px 15px 10px; border-bottom: 1px solid var(--line); }
.archive-title { display: flex; align-items: center; gap: 9px; font-family: var(--display); font-weight: 600; font-size: 13px; color: var(--text); }
.archive-title svg { color: var(--muted); }
.archive-strip-head p { margin: 5px 0 0; font-size: 11.5px; color: var(--muted); }
.calendar-cells { display: flex; gap: 8px; padding: 14px 15px; overflow-x: auto; }
.calendar-cell { flex: none; width: 60px; padding: 10px 6px 8px; border-radius: 10px; border: 1px solid var(--line); background: var(--bg-2); cursor: pointer; display: flex; flex-direction: column; align-items: center; gap: 2px; position: relative; color: var(--text-2); transition: all .14s; }
.calendar-cell:hover { border-color: var(--line-2); background: var(--panel-2); transform: translateY(-1px); }
.calendar-cell.open { border-color: var(--accent-line-2); background: var(--accent-dim); color: var(--text); box-shadow: 0 0 0 1px var(--accent-line); }
.calendar-weekday, .calendar-month { font-family: var(--mono); color: var(--muted); }
.calendar-weekday { font-size: 8.5px; letter-spacing: .6px; }
.calendar-cell.open .calendar-weekday { color: var(--accent); }
.calendar-day { font-family: var(--display); font-size: 20px; font-weight: 600; line-height: 1; letter-spacing: -.5px; }
.calendar-month { font-size: 9px; }
.calendar-count { position: absolute; top: -6px; right: -6px; min-width: 17px; height: 17px; border-radius: 9px; background: var(--accent); color: #fff; font-family: var(--mono); font-size: 10px; font-weight: 700; display: grid; place-items: center; padding: 0 4px; box-sizing: border-box; }
.archive-result-head, .archive-day-head { display: flex; align-items: center; gap: 7px; min-width: 0; color: var(--muted); font-family: var(--mono); font-size: 10px; font-weight: 600; letter-spacing: .6px; text-transform: uppercase; }
.archive-day { display: grid; gap: 10px; }
.calendar-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--accent); flex: none; }
.head-line { flex: 1; height: 1px; background: var(--line); }
.archive-day-head button { border: 0; background: transparent; color: var(--muted); cursor: pointer; font: inherit; text-transform: none; }
.archive-day-head button:hover { color: var(--text); }
</style>
