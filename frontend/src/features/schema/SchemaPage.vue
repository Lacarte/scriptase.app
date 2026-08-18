<script setup>
/**
 * Schema (step 1.2) — the workflow graph as the engine holds it.
 *
 * Read-only by construction. The node registry says what each node is, the
 * workflow document says which nodes exist and how they wire, and the stage
 * projection says which Production stage each one reports to. Nothing on this
 * page runs, edits or saves anything, and no node or edge list is authored
 * here: change the backend's answer and the picture changes with it.
 *
 * Live job animation and the node inspector arrive in steps 1.3 and 1.4.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useToast } from '@/shared/composables/useToast.js'
import SchemaCanvas from './components/SchemaCanvas.vue'
import { useSchemaGraph } from './composables/useSchemaGraph.js'

defineOptions({ name: 'SchemaPage' })

const route = useRoute()
const router = useRouter()
const toast = useToast()

const {
  workflows,
  selectedWorkflowId,
  templateId,
  loading,
  error,
  stageError,
  nodes,
  edges,
  hasGraph,
  sourceLabel,
  load,
  selectWorkflow,
} = useSchemaGraph()

const canvasRef = ref(null)

const stageCount = computed(() => {
  const keys = new Set()
  for (const node of nodes.value) {
    if (node.stageKey) keys.add(node.stageKey)
  }
  return keys.size
})

const meta = computed(() => {
  const bits = []
  if (sourceLabel.value) bits.push(sourceLabel.value)
  bits.push(`${nodes.value.length} nodes`)
  if (stageCount.value) bits.push(`${stageCount.value} stages`)
  return bits.join(' · ')
})

async function onPickWorkflow(event) {
  const id = event.target.value
  if (!id || id === selectedWorkflowId.value) return
  try {
    await selectWorkflow(id)
    router.replace({ name: 'schema', query: { ...route.query, workflow: id } })
  } catch (err) {
    toast.error(err?.message || 'Could not open that workflow')
  }
}

function onRealign({ message }) {
  if (message) toast.info(message, 2000)
}

onMounted(async () => {
  const preferred = typeof route.query.workflow === 'string' ? route.query.workflow : ''
  // A registry that will not load is already reported through `error`; the
  // rejection would only become an unhandled one.
  await load(preferred).catch(() => null)
})

// Following the deep link keeps Schema addressable from Production and the
// Library without this page owning a second navigation model.
watch(() => route.query.workflow, async (next) => {
  if (typeof next !== 'string' || !next || next === selectedWorkflowId.value) return
  try {
    await selectWorkflow(next)
  } catch {
    /* surfaced through `error` */
  }
})
</script>

<template>
  <section class="schema-page">
    <header class="sch-topbar">
      <div class="sch-title">
        <h1>Workflow Schema</h1>
        <p class="sch-sub">
          Read-only projection of the node graph. Schema watches the engine; it never runs it.
        </p>
      </div>

      <div class="spacer" />

      <label v-if="workflows.length" class="sch-pick">
        <span class="sr-only">Workflow</span>
        <select :value="selectedWorkflowId" @change="onPickWorkflow">
          <option v-for="wf in workflows" :key="wf.workflow_id" :value="wf.workflow_id">
            {{ wf.name || wf.workflow_id }}
          </option>
        </select>
      </label>

      <div v-if="meta" class="sch-meta">{{ meta }}</div>

      <div class="sch-zoom" role="group" aria-label="Zoom">
        <button class="sch-zbtn" type="button" aria-label="Zoom out" @click="canvasRef?.zoomStep(-1)">−</button>
        <button class="sch-zbtn" type="button" @click="canvasRef?.fit()">Fit</button>
        <button class="sch-zbtn" type="button" aria-label="Zoom in" @click="canvasRef?.zoomStep(1)">+</button>
      </div>
    </header>

    <p v-if="templateId" class="banner info sch-banner">
      No saved workflow yet — showing the built-in <strong>{{ sourceLabel }}</strong>.
    </p>
    <p v-if="stageError" class="banner warn sch-banner">
      Stage projection unavailable, so nodes show their category instead of a stage:
      {{ stageError }}
    </p>
    <p v-if="error" class="banner error sch-banner">{{ error }}</p>

    <SchemaCanvas
      v-if="hasGraph"
      ref="canvasRef"
      :nodes="nodes"
      :edges="edges"
      @realign="onRealign"
    />
    <div v-else class="sch-empty">
      <p v-if="loading">Loading the graph…</p>
      <p v-else>
        No workflow graph to project. Create one from a template in the workflow
        builder, then come back.
      </p>
    </div>
  </section>
</template>

<style scoped>
.schema-page {
  display: flex;
  flex-direction: column;
  min-height: 0;
  height: 100%;
  overflow: hidden;
}

.sch-topbar {
  flex: none;
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 22px;
  border-bottom: 1px solid var(--line);
  background: linear-gradient(180deg, var(--bg-2), rgba(14, 17, 22, 0.6));
  z-index: 5;
}

.sch-title h1 {
  margin: 0;
  font-family: var(--display);
  font-size: 16px;
  font-weight: 600;
  letter-spacing: -0.2px;
  color: var(--text);
}

.sch-sub {
  margin: 2px 0 0;
  font-size: 11.5px;
  color: var(--muted);
}

.spacer {
  flex: 1 1 auto;
}

.sch-meta {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--muted);
  white-space: nowrap;
}

.sch-pick select {
  height: 30px;
  max-width: 220px;
  padding: 0 8px;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--panel);
  color: var(--text-2);
  font-family: var(--body);
  font-size: 12px;
}

.sch-zoom {
  display: flex;
  gap: 4px;
}

.sch-zbtn {
  width: 34px;
  height: 30px;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--panel);
  color: var(--text-2);
  font-family: var(--mono);
  font-size: 12px;
  cursor: pointer;
  transition: background 0.16s, color 0.16s;
}

.sch-zbtn:hover {
  background: var(--panel-2);
  color: var(--text);
}

.sch-banner {
  flex: none;
  margin: 10px 22px 0;
}

.sch-empty {
  flex: 1 1 auto;
  display: grid;
  place-items: center;
  padding: 40px 22px;
  color: var(--muted);
  font-size: 13px;
  text-align: center;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}

@media (max-width: 820px) {
  .sch-topbar {
    flex-wrap: wrap;
    gap: 10px;
    padding: 10px 14px;
  }

  .sch-meta {
    order: 3;
    width: 100%;
  }
}
</style>
