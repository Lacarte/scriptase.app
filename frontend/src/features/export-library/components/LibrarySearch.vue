<script setup>
import { ref, computed, watch, onBeforeUnmount } from 'vue'

defineOptions({ name: 'LibrarySearch' })

const props = defineProps({
  items: { type: Array, default: () => [] },
  sortBy: { type: String, default: 'newest' },
  filterStyle: { type: String, default: '' },
  filterRatio: { type: String, default: '' },
  filterDuration: { type: String, default: '' },
  filterChannel: { type: String, default: '' },
  sortOptions: { type: Array, default: () => [] },
  durationFilters: { type: Array, default: () => [] },
  styleOptions: { type: Array, default: () => [] },
  ratioOptions: { type: Array, default: () => [] },
  channelOptions: { type: Array, default: () => [] },
  filteredCount: { type: Number, default: 0 },
})

const emit = defineEmits(['update:sortBy', 'update:filterStyle', 'update:filterRatio', 'update:filterDuration', 'update:filterChannel', 'search', 'clear'])

const searchQuery = ref('')
const searchFocused = ref(false)

function styleLabel(id) {
  if (!id) return 'All styles'
  return id.replace(/[_-]/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

const hasFilters = computed(() =>
  props.filterStyle || props.filterRatio || props.filterDuration || props.filterChannel || searchQuery.value.trim()
)

const activeFilterCount = computed(() => {
  let c = 0
  if (props.filterStyle) c++
  if (props.filterRatio) c++
  if (props.filterDuration) c++
  if (props.filterChannel) c++
  if (searchQuery.value.trim()) c++
  return c
})

// Suggestions based on search query
const suggestions = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q || q.length < 2) return []
  const results = []

  // Match styles
  for (const s of props.styleOptions) {
    if (s && styleLabel(s).toLowerCase().includes(q)) {
      results.push({ type: 'style', value: s, label: styleLabel(s) })
    }
  }

  // Match project IDs
  const seen = new Set()
  for (const item of props.items) {
    if (item.project_id && item.project_id.toLowerCase().includes(q) && !seen.has(item.project_id)) {
      seen.add(item.project_id)
      results.push({ type: 'project', value: item.project_id, label: item.project_id })
    }
  }

  return results.slice(0, 8)
})

function applySuggestion(sug) {
  if (sug.type === 'style') {
    emit('update:filterStyle', sug.value)
    searchQuery.value = ''
  } else if (sug.type === 'project') {
    searchQuery.value = sug.value
    emit('search', sug.value)
  }
  searchFocused.value = false
}

// The dropdown closes on a delay so a click on a suggestion lands before the
// blur unmounts it. V2 called setTimeout inline in the template, which a
// compiled render function resolves against the component instance rather
// than the window — it never actually ran.
let blurTimer = null

function onSearchBlur() {
  if (blurTimer) window.clearTimeout(blurTimer)
  blurTimer = window.setTimeout(() => { searchFocused.value = false }, 200)
}

onBeforeUnmount(() => {
  if (blurTimer) window.clearTimeout(blurTimer)
})

watch(searchQuery, (q) => {
  emit('search', q.trim())
})

function clearAll() {
  searchQuery.value = ''
  emit('update:filterStyle', '')
  emit('update:filterRatio', '')
  emit('update:filterDuration', '')
  emit('update:filterChannel', '')
  emit('clear')
}
</script>

<template>
  <div class="search-section">
    <!-- Search input row -->
    <div class="search-row">
      <div class="search-input-wrap" :class="{ focused: searchFocused }">
        <svg class="search-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
        <input
          v-model="searchQuery"
          class="search-input"
          type="text"
          placeholder="Search videos, projects, or channels..."
          aria-label="Search exports"
          data-shortcut-search
          @focus="searchFocused = true"
          @blur="onSearchBlur"
        />
        <button
          v-if="searchQuery"
          type="button"
          class="search-clear"
          aria-label="Clear search"
          @click="searchQuery = ''"
        >
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" aria-hidden="true"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>

        <!-- Suggestions dropdown -->
        <Transition name="sug-fade">
          <div v-if="searchFocused && suggestions.length" class="search-suggestions">
            <button v-for="sug in suggestions" :key="sug.type + sug.value" class="search-sug-item" @mousedown.prevent="applySuggestion(sug)">
              <span class="sug-type" :class="'sug-type--' + sug.type">{{ sug.type }}</span>
              <span class="sug-label">{{ sug.label }}</span>
            </button>
          </div>
        </Transition>
      </div>

      <div class="filter-pills">
        <select class="f-select" :class="{ active: filterChannel }" :value="filterChannel" aria-label="Filter by channel" @change="emit('update:filterChannel', $event.target.value)">
          <option value="">All channels</option>
          <option v-for="channel in channelOptions" :key="channel.value" :value="channel.value">{{ channel.label }}</option>
        </select>

        <select class="f-select" :value="sortBy" @change="emit('update:sortBy', $event.target.value)">
          <option v-for="opt in sortOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
        </select>

        <select class="f-select" :class="{ active: filterStyle }" :value="filterStyle" @change="emit('update:filterStyle', $event.target.value)">
          <option value="">All styles</option>
          <option v-for="s in styleOptions.filter(v => v)" :key="s" :value="s">{{ styleLabel(s) }}</option>
        </select>

        <select class="f-select" :class="{ active: filterRatio }" :value="filterRatio" @change="emit('update:filterRatio', $event.target.value)">
          <option value="">All ratios</option>
          <option v-for="r in ratioOptions.filter(v => v)" :key="r" :value="r">{{ r }}</option>
        </select>

        <select class="f-select" :class="{ active: filterDuration }" :value="filterDuration" @change="emit('update:filterDuration', $event.target.value)">
          <option v-for="d in durationFilters" :key="d.value" :value="d.value">{{ d.label }}</option>
        </select>
      </div>
    </div>

    <!-- Active filters + count -->
    <div class="search-meta">
      <div class="search-meta-left">
        <button v-if="hasFilters" class="clear-all-btn" @click="clearAll">
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          Clear {{ activeFilterCount }} filter{{ activeFilterCount !== 1 ? 's' : '' }}
        </button>
      </div>
      <span class="search-count">
        <template v-if="filteredCount < items.length">{{ filteredCount }} / {{ items.length }}</template>
        <template v-else>{{ items.length }} video{{ items.length !== 1 ? 's' : '' }}</template>
      </span>
    </div>
  </div>
</template>

<style scoped>
.search-section {
  margin-bottom: 14px;
}

.search-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

/* Search input — the shared `.search-field` geometry, on the wrap the
   template already provides. */
.search-input-wrap {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 200px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--r-s);
  padding: 7px 11px;
  transition: border-color 0.15s, box-shadow 0.15s;
}

.search-input-wrap.focused,
.search-input-wrap:focus-within {
  border-color: var(--accent-line-2);
  box-shadow: 0 0 0 3px var(--accent-ring);
}

.search-icon { color: var(--muted); flex-shrink: 0; }

.search-input {
  flex: 1;
  min-width: 0;
  background: transparent;
  border: none;
  outline: none;
  color: var(--text);
  font-family: var(--body);
  font-size: 13px;
  padding: 0;
}

.search-input::placeholder { color: var(--faint); }

.search-clear {
  display: flex; align-items: center; padding: 3px; background: none; border: none;
  color: var(--muted); cursor: pointer; border-radius: 4px; transition: color 0.15s;
}

.search-clear:hover { color: var(--text); }

/* Suggestions */
.search-suggestions {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  margin-top: 5px;
  background: var(--panel-grad2);
  border: 1px solid var(--line);
  border-radius: var(--r-s);
  box-shadow: var(--shadow);
  z-index: 50;
  overflow: hidden;
}

.search-sug-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px 12px;
  background: none;
  border: none;
  border-bottom: 1px solid var(--line-soft);
  color: var(--text);
  cursor: pointer;
  font-family: var(--body);
  font-size: 13px;
  transition: background 0.1s;
  text-align: left;
}

.search-sug-item:last-child { border-bottom: none; }
.search-sug-item:hover { background: var(--panel-2); }

.sug-type {
  font-family: var(--mono);
  font-size: 9px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding: 2px 6px;
  border-radius: 5px;
  flex-shrink: 0;
}

.sug-type--style { color: var(--sched); background: var(--sched-dim); box-shadow: inset 0 0 0 1px var(--sched-line); }
.sug-type--project { color: var(--run); background: var(--run-dim); box-shadow: inset 0 0 0 1px var(--run-line); }
.sug-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.sug-fade-enter-active { animation: sug-in 0.12s ease-out; }
.sug-fade-leave-active { animation: sug-out 0.1s ease-in forwards; }
@keyframes sug-in { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: translateY(0); } }
@keyframes sug-out { from { opacity: 1; } to { opacity: 0; } }

/* Filter pills */
.filter-pills {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.f-select {
  background: var(--panel);
  color: var(--text-2);
  border: 1px solid var(--line);
  border-radius: var(--r-s);
  padding: 7px 10px;
  font-family: var(--body);
  font-size: 12.5px;
  cursor: pointer;
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s, color 0.14s, background 0.14s;
}

.f-select:hover { border-color: var(--line-2); }

.f-select:focus {
  border-color: var(--accent-line-2);
  box-shadow: 0 0 0 3px var(--accent-ring);
}

/* A filter that is actually filtering is an active state. */
.f-select.active {
  border-color: var(--accent-line);
  background: var(--accent-dim);
  color: var(--accent);
}

/* Meta row */
.search-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 8px;
  min-height: 20px;
}

.search-meta-left { display: flex; gap: 6px; align-items: center; }

.clear-all-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 9px;
  font-family: var(--body);
  font-size: 11.5px;
  font-weight: 500;
  border: 1px solid var(--fail-line);
  border-radius: 6px;
  background: transparent;
  color: var(--fail);
  cursor: pointer;
  transition: background 0.16s, border-color 0.16s, color 0.14s;
}

.clear-all-btn:hover { background: var(--fail-dim); border-color: var(--fail-line-2); }

.search-count {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--muted);
}

@media (max-width: 700px) {
  .search-row { flex-direction: column; }
  .search-input-wrap { width: 100%; }
  .filter-pills { width: 100%; }
}
</style>
