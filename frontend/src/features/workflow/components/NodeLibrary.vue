<script setup>
import { computed, onMounted, ref } from 'vue'
import { useWorkflowStore } from '../stores/workflow.js'
import { DRAG_MIME } from '../constants.js'
import NodeIcon from '@/shared/components/NodeIcon.vue'

const store = useWorkflowStore()
const query = ref('')

onMounted(() => store.loadNodeTypes())

// A sort hint, not a filter: a category missing from this array used to drop
// its nodes out of the palette silently. Visibility is the registry's `hidden`
// flag alone (step 12.1); an unlisted category now simply sorts last.
const CATEGORY_ORDER = ['input', 'audio', 'timing', 'ai', 'assets', 'video', 'output', 'utility', 'testing']

function categoryRank(category) {
  const index = CATEGORY_ORDER.indexOf(category)
  return index === -1 ? CATEGORY_ORDER.length : index
}

const hiddenCount = computed(
  () => Object.values(store.nodeTypes).filter((node) => node.hidden).length,
)

const groups = computed(() => {
  const q = query.value.trim().toLowerCase()
  const byCategory = {}
  for (const node of Object.values(store.nodeTypes)) {
    if (node.hidden && !store.showAllNodes) continue
    if (q && !`${node.display_name} ${node.description} ${node.type}`.toLowerCase().includes(q)) {
      continue
    }
    ;(byCategory[node.category] ??= []).push(node)
  }
  return Object.keys(byCategory)
    .sort((a, b) => categoryRank(a) - categoryRank(b) || a.localeCompare(b))
    .map((cat) => ({
      key: cat,
      label: store.categories[cat]?.label || cat,
      color: store.categories[cat]?.color || '#9CA3AF',
      nodes: byCategory[cat].sort((a, b) => a.display_name.localeCompare(b.display_name)),
    }))
})

const recentNodes = computed(() => {
  const q = query.value.trim().toLowerCase()
  return store.recentNodeTypes
    .map((type) => store.nodeTypes[type])
    .filter(Boolean)
    .filter((node) => !q || `${node.display_name} ${node.description} ${node.type}`.toLowerCase().includes(q))
})

function onDragStart(event, node) {
  event.dataTransfer.setData(DRAG_MIME, node.type)
  event.dataTransfer.effectAllowed = 'copy'
}
</script>

<template>
  <div class="library">
    <div class="library-search">
      <input
        v-model="query"
        type="search"
        placeholder="Search nodes…"
        class="library-search-input"
      />
      <label v-if="hiddenCount" class="library-toggle">
        <input
          type="checkbox"
          class="library-toggle-input"
          :checked="store.showAllNodes"
          @change="store.setShowAllNodes($event.target.checked)"
        />
        <span>Show all nodes</span>
        <span v-if="!store.showAllNodes" class="library-toggle-count">{{ hiddenCount }} hidden</span>
      </label>
    </div>

    <div v-if="store.registryLoading" class="library-note">Loading node types…</div>
    <div v-else-if="store.registryError" class="library-note error">{{ store.registryError }}</div>
    <div v-else-if="!groups.length" class="library-note">No nodes match “{{ query }}”</div>

    <div class="library-groups">
      <section v-if="recentNodes.length" class="library-group library-recent">
        <header class="library-group-header">
          <span class="library-group-dot recent-dot" />
          <span>Recently used</span>
          <button
            type="button"
            class="library-recent-clear"
            title="Clear recently used nodes"
            aria-label="Clear recently used nodes"
            @click="store.clearRecentNodeTypes()"
          >
            Clear
          </button>
        </header>
        <div
          v-for="node in recentNodes"
          :key="`recent:${node.type}`"
          class="library-item"
          draggable="true"
          :title="node.description"
          @dragstart="onDragStart($event, node)"
        >
          <span class="library-item-icon" :style="{ color: store.categories[node.category]?.color || '#9CA3AF' }">
            <NodeIcon :icon="node.icon" />
          </span>
          <span class="library-item-text">
            <span class="library-item-name">{{ node.display_name }}</span>
            <span class="library-item-desc">{{ node.description }}</span>
          </span>
        </div>
      </section>
      <section v-for="group in groups" :key="group.key" class="library-group">
        <header class="library-group-header">
          <span class="library-group-dot" :style="{ background: group.color }" />
          {{ group.label }}
        </header>
        <div
          v-for="node in group.nodes"
          :key="node.type"
          class="library-item"
          draggable="true"
          :title="node.description"
          @dragstart="onDragStart($event, node)"
        >
          <span class="library-item-icon" :style="{ color: group.color }">
            <NodeIcon :icon="node.icon" />
          </span>
          <span class="library-item-text">
            <span class="library-item-name">{{ node.display_name }}</span>
            <span class="library-item-desc">{{ node.description }}</span>
          </span>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.library {
  display: flex;
  flex-direction: column;
  min-height: 0;
  flex: 1;
}

.library-search {
  padding: 8px 12px;
}

.library-search-input {
  width: 100%;
  background: var(--bg-dark);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text);
  font-size: 12px;
  padding: 7px 10px;
  outline: none;
}

.library-search-input:focus {
  border-color: var(--accent);
}

.library-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 7px;
  font-size: 11px;
  color: var(--text-muted);
  cursor: pointer;
  user-select: none;
}

.library-toggle-input {
  accent-color: var(--accent, #8b5cf6);
  margin: 0;
  cursor: pointer;
}

.library-toggle-count {
  margin-left: auto;
  font-size: 10px;
  letter-spacing: 0.04em;
  opacity: 0.75;
}

.library-note {
  font-size: 12px;
  color: var(--text-muted);
  padding: 8px 14px;
}

.library-note.error {
  color: var(--accent-warning, #ffb347);
}

.library-groups {
  flex: 1;
  overflow-y: auto;
  padding-bottom: 12px;
}

.library-group-header {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 9px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.14em;
  color: var(--text-muted);
  padding: 10px 14px 4px;
}

.library-recent { border-bottom: 1px solid var(--border); padding-bottom: 6px; }
.recent-dot { background: var(--accent, #8b5cf6); }

.library-recent-clear {
  margin-left: auto;
  padding: 2px 5px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--text-muted);
  font: inherit;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  cursor: pointer;
}

.library-recent-clear:hover,
.library-recent-clear:focus-visible {
  background: rgba(255, 255, 255, 0.07);
  color: var(--text);
  outline: none;
}

.library-group-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}

.library-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 7px 12px;
  margin: 1px 6px;
  border-radius: 8px;
  cursor: grab;
  transition: background 0.15s;
}

.library-item:hover {
  background: rgba(255, 255, 255, 0.05);
}

.library-item:active {
  cursor: grabbing;
}

.library-item-icon {
  width: 18px;
  height: 18px;
  min-width: 18px;
  margin-top: 1px;
}

.library-item-icon svg {
  width: 100%;
  height: 100%;
}

.library-item-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.library-item-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
  line-height: 1.3;
}

.library-item-desc {
  font-size: 10.5px;
  color: var(--text-muted);
  line-height: 1.35;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
