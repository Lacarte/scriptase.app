<script setup>
/**
 * The node inspector (step 1.3).
 *
 * One card's side of the running Job: status, the provider instance that
 * actually ran, the input it resolved, the output it produced, and the error
 * if it failed. Everything is read from the execution record, so the panel
 * stays in sync as stages advance without watching anything of its own.
 *
 * Step 1.4 adds Test with a one-shot provider override, Locate node, and Retry.
 * Those actions are emitted to the page; inspection itself remains derived.
 *
 * Nothing here can leak a credential: the execution record carries provider
 * **instance references**, and input/output are the engine's redacted
 * summaries, not raw payloads.
 */
import { computed } from 'vue'

import NodeIcon from '@/shared/components/NodeIcon.vue'
import { statusLabel } from '@/features/production/stageStatus.js'
import TestNodePanel from '@/features/production/components/TestNodePanel.vue'
import { formatDuration } from '../live.js'

const props = defineProps({
  /** inspectorModel(node, record) from ../live.js, or null when nothing is open. */
  model: { type: Object, default: null },
  /** True when no run is bound — the panel says so rather than showing zeroes. */
  bound: { type: Boolean, default: false },
  jobId: { type: String, default: '' },
  testOpen: { type: Boolean, default: false },
  testRunning: { type: Boolean, default: false },
  testResult: { type: Object, default: null },
})

defineEmits(['close', 'locate', 'retry', 'open-test', 'close-test', 'test-run'])

const durationLabel = computed(() => formatDuration(props.model?.durationMs))

/** Summaries are already compact and redacted; this only makes them readable. */
function pretty(value) {
  if (value == null) return ''
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function isEmpty(value) {
  if (value == null) return true
  if (Array.isArray(value)) return value.length === 0
  if (typeof value === 'object') return Object.keys(value).length === 0
  return false
}
</script>

<template>
  <aside v-if="model" class="sch-inspector" aria-label="Node inspector">
    <header class="si-head" :style="{ '--ac': model.accent }">
      <span class="si-ic">
        <NodeIcon :icon="model.icon" />
      </span>
      <div class="si-t">
        <strong class="nm">{{ model.name }}</strong>
        <span class="sb">{{ model.type }}</span>
      </div>
      <span class="si-badge" :class="`s-${model.visual}`">{{ statusLabel(model.status) }}</span>
      <button class="si-x" type="button" aria-label="Close inspector" @click="$emit('close')">
        ×
      </button>
    </header>

    <div class="si-body">
      <dl class="si-meta">
        <div class="si-row">
          <dt class="k">Stage</dt>
          <dd class="v">{{ model.stageLabel || model.subtitle }}</dd>
        </div>
        <div class="si-row">
          <dt class="k">Provider</dt>
          <dd class="v">
            <template v-if="model.provider">
              <span class="mono">{{ model.provider.instanceId }}</span>
              <span v-if="model.provider.reason" class="si-note">
                · {{ model.provider.reason }}
              </span>
            </template>
            <!-- Not "none": a local service has no provider instance to resolve,
                 and a node that has not run yet has not resolved one yet. -->
            <span v-else class="si-note">Not resolved for this run</span>
          </dd>
        </div>
        <div v-if="durationLabel || model.attempts" class="si-row">
          <dt class="k">Run</dt>
          <dd class="v">
            <span v-if="durationLabel">{{ durationLabel }}</span>
            <span v-if="model.attempts" class="si-note">
              · attempt {{ model.attempts }}
            </span>
            <span v-if="model.fromSampleData" class="si-note">· sample data</span>
          </dd>
        </div>
      </dl>

      <div class="si-actions" role="group" aria-label="Node actions">
        <button class="si-action primary" type="button" @click="$emit('open-test')">Test</button>
        <button class="si-action" type="button" @click="$emit('locate')">Locate node</button>
        <button
          v-if="model.visual === 'failed'"
          class="si-action"
          type="button"
          @click="$emit('retry')"
        >Retry</button>
      </div>

      <TestNodePanel
        v-if="testOpen"
        :title="model.name"
        :node-id="model.id"
        :node-type="model.type"
        :ports="model.inputs"
        :current-job-id="jobId"
        :provider-domain="model.providerDomain"
        :provider-label="model.provider?.instanceId || ''"
        :running="testRunning"
        :last-result="testResult"
        @run="$emit('test-run', $event)"
        @close="$emit('close-test')"
      />

      <p v-if="!bound" class="si-none">
        No run bound. Choose a run above to see what this node did.
      </p>
      <p v-else-if="model.empty" class="si-none">
        This run has not reached this node yet.
      </p>

      <section v-if="model.error" class="si-sec err" aria-label="Node error">
        <h3 class="si-h">Error</h3>
        <p class="si-err-msg">{{ model.error.message || '' }}</p>
        <p class="si-err-code">{{ model.error.code || 'ERROR' }}</p>
      </section>

      <section v-if="!isEmpty(model.input)" class="si-sec" aria-label="Node input">
        <h3 class="si-h in"><span class="arrow">▼</span> Input</h3>
        <pre>{{ pretty(model.input) }}</pre>
      </section>

      <section v-if="!isEmpty(model.output)" class="si-sec" aria-label="Node output">
        <h3 class="si-h out"><span class="arrow">▲</span> Output</h3>
        <pre>{{ pretty(model.output) }}</pre>
      </section>

      <section v-if="model.artifacts.length" class="si-sec" aria-label="Node artifacts">
        <h3 class="si-h">Artifacts</h3>
        <ul class="si-refs">
          <li v-for="ref in model.artifacts" :key="ref" class="mono">{{ ref }}</li>
        </ul>
      </section>
    </div>
  </aside>
</template>

<style scoped>
/* The panel's placement on the canvas belongs to the Schema view (`sch-*`);
   everything inside it is the prototype's shared status-indicator set. */
.sch-inspector {
  position: absolute;
  top: 12px;
  right: 12px;
  bottom: 12px;
  z-index: 8;
  display: flex;
  flex-direction: column;
  width: 320px;
  max-width: calc(100% - 24px);
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: var(--r);
  background: rgba(10, 13, 18, 0.94);
  backdrop-filter: blur(8px);
  box-shadow: var(--hairline-top), 0 18px 44px -18px rgba(0, 0, 0, 0.85);
}

/* ---- Head: the node's own accent tints its icon plate ---- */
.si-head {
  flex: none;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--line-soft);
  background: var(--bg-2);
}

.si-ic {
  flex: none;
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 8px;
  font-size: 15px;
  background: color-mix(in srgb, var(--ac) 18%, transparent);
  color: var(--ac);
  box-shadow:
    inset 0 0 0 1px color-mix(in srgb, var(--ac) 35%, transparent),
    inset 0 1px 0 rgba(255, 255, 255, 0.18);
}

.si-ic :deep(svg) {
  width: 15px;
  height: 15px;
}

.si-t {
  flex: 1;
  min-width: 0;
}

.si-t .nm {
  display: block;
  overflow: hidden;
  font-family: var(--display);
  font-size: 13.5px;
  font-weight: 600;
  color: var(--text);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.si-t .sb {
  display: block;
  margin-top: 1px;
  overflow: hidden;
  font-family: var(--mono);
  font-size: 9.5px;
  color: var(--muted);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.si-badge {
  flex: none;
  padding: 3px 8px;
  border-radius: 20px;
  font-family: var(--mono);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.3px;
  text-transform: uppercase;
  color: var(--muted);
  background: var(--bg);
  box-shadow: inset 0 0 0 1px var(--line);
}

.si-badge.s-active { color: var(--run); background: var(--run-dim); box-shadow: none; }
.si-badge.s-done { color: var(--ok); background: var(--ok-dim); box-shadow: none; }
.si-badge.s-failed { color: var(--fail); background: var(--fail-dim); box-shadow: none; }
.si-badge.s-blocked { color: var(--sched); background: var(--sched-dim); box-shadow: none; }

/* The three "nothing to see yet" states repeat the base rather than inherit
   it, because they are the ones the class list actually produces most often
   and reading them here is what makes the set legible. `s-skipped` is the
   engine's spelling of the prototype's `s-skip`; both resolve. */
.si-badge.s-pending,
.si-badge.s-idle,
.si-badge.s-skip,
.si-badge.s-skipped {
  color: var(--muted);
  background: var(--bg);
  box-shadow: inset 0 0 0 1px var(--line);
}

.si-x {
  flex: none;
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--muted);
  font-size: 15px;
  line-height: 1;
  cursor: pointer;
}

.si-x:hover {
  background: var(--raise);
  color: var(--text);
}

/* ---- Body ---- */
.si-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 12px 14px;
}

.si-meta {
  margin: 0 0 14px;
}

.si-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 4px 0;
  font-size: 12px;
}

.si-row .k {
  flex: none;
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.4px;
  text-transform: uppercase;
  color: var(--muted);
}

.si-row .v {
  margin: 0;
  min-width: 0;
  font-weight: 500;
  color: var(--text);
  text-align: right;
  overflow-wrap: anywhere;
}

.si-note {
  color: var(--faint);
  font-weight: 400;
}

.mono {
  font-family: var(--mono);
  font-size: 11px;
}

/* ---- Sections: a labelled bar over a recessed body ---- */
.si-sec {
  margin-top: 12px;
  border: 1px solid var(--line-soft);
  border-radius: var(--r-s);
  overflow: hidden;
}

.si-sec.err {
  border-color: var(--fail-line);
}

.si-h {
  display: flex;
  align-items: center;
  gap: 7px;
  margin: 0;
  padding: 8px 11px;
  border-bottom: 1px solid var(--line-soft);
  background: var(--bg-2);
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 500;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  color: var(--muted);
}

.si-h .arrow { font-size: 8px; }
.si-h.in .arrow { color: var(--sched); }
.si-h.out .arrow { color: var(--ok); }

.si-sec.err .si-h {
  color: var(--fail);
  background: var(--fail-dim);
  border-bottom-color: var(--fail-line);
}

.si-sec pre {
  margin: 0;
  max-height: 210px;
  overflow: auto;
  padding: 10px 11px;
  font-family: var(--mono);
  font-size: 11px;
  line-height: 1.55;
  color: var(--text-2);
  white-space: pre-wrap;
  word-break: break-word;
}

.si-none {
  margin: 0;
  padding: 11px;
  font-size: 11.5px;
  line-height: 1.5;
  color: var(--muted);
}

.si-err-msg {
  margin: 0;
  padding: 10px 11px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--fail-text);
  overflow-wrap: anywhere;
}

.si-err-code {
  margin: 0 11px 11px;
  padding: 7px 9px;
  border-radius: 5px;
  background: var(--fail-dim);
  font-family: var(--mono);
  font-size: 10.5px;
  color: var(--fail);
  word-break: break-word;
}

.si-refs {
  margin: 0;
  padding: 10px 11px;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 4px;
  color: var(--text-2);
  overflow-wrap: anywhere;
}

/* ---- Actions (step 1.4) — no prototype counterpart; the panel there is
       read-only. Styled as the shared compact button so it does not read
       as a different vocabulary. ---- */
.si-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  padding-top: 12px;
  border-top: 1px solid var(--line-soft);
}

.si-action {
  min-height: 30px;
  padding: 0 11px;
  border: 1px solid var(--line);
  border-radius: var(--r-s);
  background: var(--panel-grad);
  color: var(--text-2);
  font-family: var(--body);
  font-size: 11.5px;
  font-weight: 600;
  cursor: pointer;
}

.si-action:hover {
  color: var(--text);
  border-color: var(--line-2);
}

.si-action.primary {
  border-color: transparent;
  background: var(--accent-grad);
  color: #fff;
}

@media (max-width: 820px) {
  .sch-inspector {
    top: auto;
    left: 12px;
    width: auto;
    max-height: 55%;
  }
}
</style>
