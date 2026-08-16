<script setup>
import { ref, computed, watch, onBeforeUnmount } from 'vue'

defineOptions({ name: 'LibrarySearch' })

const props = defineProps({
  items: { type: Array, default: () => [] },
  sortBy: { type: String, default: 'newest' },
  filterStyle: { type: String, default: '' },
  filterRatio: { type: String, default: '' },
  filterDuration: { type: String, default: '' },
  sortOptions: { type: Array, default: () => [] },
  durationFilters: { type: Array, default: () => [] },
  styleOptions: { type: Array, default: () => [] },
  ratioOptions: { type: Array, default: () => [] },
  filteredCount: { type: Number, default: 0 },
})

const emit = defineEmits(['update:sortBy', 'update:filterStyle', 'update:filterRatio', 'update:filterDuration', 'search', 'clear'])

const searchQuery = ref('')
const searchFocused = ref(false)

function styleLabel(id) {
  if (!id) return 'All styles'
  return id.replace(/[_-]/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

const hasFilters = computed(() =>
  props.filterStyle || props.filterRatio || props.filterDuration || searchQuery.value.trim()
)

const activeFilterCount = computed(() => {
  let c = 0
  if (props.filterStyle) c++
  if (props.filterRatio) c++
  if (props.filterDuration) c++
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
          placeholder="Search projects, styles, prompts..."
          @focus="searchFocused = true"
          @blur="onSearchBlur"
        />
        <button v-if="searchQuery" class="search-clear" @click="searchQuery = ''">
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
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

/* Search input */
.search-input-wrap {
  position: relative;
  display: flex;
  align-items: center;
  flex: 1;
  min-width: 200px;
  background: var(--bg-darkest);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0 10px;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.search-input-wrap.focused {
  border-color: var(--accent);
  box-shadow: 0 0 0 2px rgba(78, 205, 196, 0.1);
}
.search-icon { color: var(--text-muted); flex-shrink: 0; }
.search-input {
  flex: 1;
  background: none;
  border: none;
  outline: none;
  color: var(--text);
  font-size: 11px;
  font-family: var(--font-mono);
  padding: 7px 8px;
}
.search-input::placeholder { color: var(--text-muted); opacity: 0.6; }
.search-clear {
  display: flex; align-items: center; padding: 3px; background: none; border: none;
  color: var(--text-muted); cursor: pointer; border-radius: 3px; transition: color 0.15s;
}
.search-clear:hover { color: var(--accent); }

/* Suggestions */
.search-suggestions {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  margin-top: 4px;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.4);
  z-index: 50;
  overflow: hidden;
}
.search-sug-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 7px 12px;
  background: none;
  border: none;
  border-bottom: 1px solid var(--border);
  color: var(--text);
  cursor: pointer;
  font-size: 11px;
  transition: background 0.1s;
  text-align: left;
}
.search-sug-item:last-child { border-bottom: none; }
.search-sug-item:hover { background: rgba(78,205,196,0.06); }
.sug-type {
  font-family: var(--font-mono);
  font-size: 8px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 1px 5px;
  border-radius: 3px;
  flex-shrink: 0;
}
.sug-type--style { color: #A78BFA; background: rgba(167,139,250,0.1); }
.sug-type--project { color: #4ECDC4; background: rgba(78,205,196,0.1); }
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
  background: var(--bg-darkest);
  color: var(--text-secondary);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 10px;
  font-size: 10px;
  font-family: var(--font-mono);
  cursor: pointer;
  outline: none;
  transition: border-color 0.15s;
}
.f-select:hover, .f-select:focus { border-color: var(--border-hover); }
.f-select.active { border-color: rgba(78,205,196,0.4); color: var(--accent); }

/* Meta row */
.search-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 6px;
  min-height: 20px;
}
.search-meta-left { display: flex; gap: 6px; align-items: center; }

.clear-all-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  font-size: 9px;
  font-weight: 600;
  font-family: var(--font-mono);
  border: 1px solid rgba(255, 107, 107, 0.3);
  border-radius: 4px;
  background: transparent;
  color: #FF6B6B;
  cursor: pointer;
  transition: all 0.15s;
}
.clear-all-btn:hover { background: rgba(255, 107, 107, 0.08); border-color: #FF6B6B; }

.search-count {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-muted);
}

@media (max-width: 700px) {
  .search-row { flex-direction: column; }
  .search-input-wrap { width: 100%; }
  .filter-pills { width: 100%; }
}
</style>
