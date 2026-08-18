<script setup>
/**
 * The node inspector (step 1.3).
 *
 * One card's side of the running Job: status, the provider instance that
 * actually ran, the input it resolved, the output it produced, and the error
 * if it failed. Everything is read from the execution record, so the panel
 * stays in sync as stages advance without watching anything of its own.
 *
 * Read-only in this step. Node **actions** — Test with a one-shot provider
 * override, Locate node, Retry — arrive in step 1.4.
 *
 * Nothing here can leak a credential: the execution record carries provider
 * **instance references**, and input/output are the engine's redacted
 * summaries, not raw payloads.
 */
import { computed } from 'vue'

import NodeIcon from '@/shared/components/NodeIcon.vue'
import { statusLabel } from '@/features/production/stageStatus.js'
import { formatDuration } from '../live.js'

const props = defineProps({
  /** inspectorModel(node, record) from ../live.js, or null when nothing is open. */
  model: { type: Object, default: null },
  /** True when no run is bound — the panel says so rather than showing zeroes. */
  bound: { type: Boolean, default: false },
})

defineEmits(['close'])

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
    <header class="ins-head">
      <span class="ins-ic" :style="{ '--ac': model.accent }">
        <NodeIcon :icon="model.icon" />
      </span>
      <div class="ins-title">
        <strong class="ins-name">{{ model.name }}</strong>
        <span class="ins-type">{{ model.type }}</span>
      </div>
      <button class="ins-close" type="button" aria-label="Close inspector" @click="$emit('close')">
        ×
      </button>
    </header>

    <dl class="ins-facts">
      <div class="ins-fact">
        <dt>Status</dt>
        <dd>
          <span class="ins-badge" :data-visual="model.visual">{{ statusLabel(model.status) }}</span>
        </dd>
      </div>
      <div class="ins-fact">
        <dt>Stage</dt>
        <dd>{{ model.stageLabel || model.subtitle }}</dd>
      </div>
      <div class="ins-fact">
        <dt>Provider</dt>
        <dd>
          <template v-if="model.provider">
            <span class="mono">{{ model.provider.instanceId }}</span>
            <span v-if="model.provider.reason" class="ins-note">
              · {{ model.provider.reason }}
            </span>
          </template>
          <!-- Not "none": a local service has no provider instance to resolve,
               and a node that has not run yet has not resolved one yet. -->
          <span v-else class="ins-note">Not resolved for this run</span>
        </dd>
      </div>
      <div v-if="durationLabel || model.attempts" class="ins-fact">
        <dt>Run</dt>
        <dd>
          <span v-if="durationLabel">{{ durationLabel }}</span>
          <span v-if="model.attempts" class="ins-note">
            · attempt {{ model.attempts }}
          </span>
          <span v-if="model.fromSampleData" class="ins-note">· sample data</span>
        </dd>
      </div>
    </dl>

    <p v-if="!bound" class="ins-empty">
      No run bound. Choose a run above to see what this node did.
    </p>
    <p v-else-if="model.empty" class="ins-empty">
      This run has not reached this node yet.
    </p>

    <section v-if="model.error" class="ins-block error" aria-label="Node error">
      <h3>Error</h3>
      <p class="ins-code">{{ model.error.code || 'ERROR' }}</p>
      <p class="ins-msg">{{ model.error.message || '' }}</p>
    </section>

    <section v-if="!isEmpty(model.input)" class="ins-block" aria-label="Node input">
      <h3>Input</h3>
      <pre class="ins-json">{{ pretty(model.input) }}</pre>
    </section>

    <section v-if="!isEmpty(model.output)" class="ins-block" aria-label="Node output">
      <h3>Output</h3>
      <pre class="ins-json">{{ pretty(model.output) }}</pre>
    </section>

    <section v-if="model.artifacts.length" class="ins-block" aria-label="Node artifacts">
      <h3>Artifacts</h3>
      <ul class="ins-refs">
        <li v-for="ref in model.artifacts" :key="ref" class="mono">{{ ref }}</li>
      </ul>
    </section>
  </aside>
</template>

<style scoped>
.sch-inspector {
  position: absolute;
  top: 12px;
  right: 12px;
  bottom: 12px;
  z-index: 8;
  width: 320px;
  max-width: calc(100% - 24px);
  overflow-y: auto;
  padding: 14px 15px 18px;
  border: 1px solid var(--line);
  border-radius: var(--r);
  background: rgba(10, 13, 18, 0.94);
  backdrop-filter: blur(8px);
  box-shadow: var(--hairline-top), 0 18px 44px -18px rgba(0, 0, 0, 0.85);
}

.ins-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--line-soft);
}

.ins-ic {
  display: grid;
  flex: none;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: color-mix(in srgb, var(--ac) 18%, transparent);
  color: var(--ac);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--ac) 35%, transparent);
}

.ins-ic :deep(svg) {
  width: 15px;
  height: 15px;
}

.ins-title {
  flex: 1;
  min-width: 0;
}

.ins-name {
  display: block;
  overflow: hidden;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: -0.1px;
  color: var(--text);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ins-type {
  display: block;
  margin-top: 2px;
  font-family: var(--mono);
  font-size: 10px;
  color: var(--faint);
  overflow-wrap: anywhere;
}

.ins-close {
  flex: none;
  width: 26px;
  height: 26px;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--panel);
  color: var(--text-2);
  font-size: 15px;
  line-height: 1;
  cursor: pointer;
}

.ins-close:hover {
  background: var(--panel-2);
  color: var(--text);
}

.ins-facts {
  margin: 12px 0 0;
  display: flex;
  flex-direction: column;
  gap: 9px;
}

.ins-fact {
  display: flex;
  gap: 10px;
  align-items: baseline;
}

.ins-fact dt {
  flex: none;
  width: 66px;
  font-family: var(--mono);
  font-size: 9.5px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.7px;
  color: var(--muted);
}

.ins-fact dd {
  margin: 0;
  min-width: 0;
  font-size: 12px;
  color: var(--text-2);
  overflow-wrap: anywhere;
}

.ins-note {
  color: var(--faint);
  font-size: 11px;
}

.mono {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text);
}

.ins-badge {
  display: inline-block;
  padding: 3px 9px;
  border-radius: 20px;
  font-family: var(--mono);
  font-size: 9.5px;
  font-weight: 600;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  color: var(--queue);
  background: var(--bg-2);
  box-shadow: inset 0 0 0 1px var(--line);
}

.ins-badge[data-visual='active'] {
  color: var(--run);
  background: var(--run-dim);
  box-shadow: inset 0 0 0 1px var(--run-line);
}

.ins-badge[data-visual='done'] {
  color: var(--ok);
  background: var(--ok-dim);
  box-shadow: inset 0 0 0 1px var(--ok-line);
}

.ins-badge[data-visual='failed'] {
  color: var(--fail);
  background: var(--fail-dim);
  box-shadow: inset 0 0 0 1px var(--fail-line);
}

.ins-badge[data-visual='blocked'] {
  color: var(--sched);
  background: var(--sched-dim);
  box-shadow: inset 0 0 0 1px var(--sched-line);
}

.ins-empty {
  margin: 14px 0 0;
  font-size: 11.5px;
  line-height: 1.5;
  color: var(--muted);
}

.ins-block {
  margin-top: 16px;
}

.ins-block h3 {
  margin: 0 0 6px;
  font-family: var(--mono);
  font-size: 9.5px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: var(--muted);
}

.ins-block.error {
  padding: 10px 11px;
  border: 1px solid var(--fail-line);
  border-radius: var(--r-s);
  background: var(--fail-dim);
}

.ins-code {
  margin: 0;
  font-family: var(--mono);
  font-size: 11px;
  font-weight: 600;
  color: var(--fail-text);
}

.ins-msg {
  margin: 4px 0 0;
  font-size: 11.5px;
  line-height: 1.5;
  color: var(--text-2);
  overflow-wrap: anywhere;
}

.ins-json {
  margin: 0;
  max-height: 210px;
  overflow: auto;
  padding: 9px 10px;
  border: 1px solid var(--line-soft);
  border-radius: var(--r-s);
  background: var(--bg-2);
  font-family: var(--mono);
  font-size: 10.5px;
  line-height: 1.5;
  color: var(--text-2);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.ins-refs {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.ins-refs li {
  overflow-wrap: anywhere;
  color: var(--text-2);
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
