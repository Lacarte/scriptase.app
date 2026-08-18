<script setup>
/**
 * Attempt history + side-by-side version comparison (step 4.3).
 *
 * Surfaces 1.2's immutable artifact versions with the three generation axes:
 * provider instance, seed, and prompt revision. Regenerating a scene image
 * shows both versions side by side — prior versions stay resolvable forever.
 */
import { computed, ref, watch } from 'vue'

import {
  compareArtifacts,
  getArtifactHistory,
  getChainHistory,
} from '../api.js'

const props = defineProps({
  /** Focus artifact id (loads full chain history). */
  artifactId: { type: String, default: '' },
  /** Explicit chain lookup when no focus id. */
  jobId: { type: String, default: '' },
  kind: { type: String, default: 'image' },
  sceneId: { type: String, default: '' },
  /**
   * Optional preloaded history payload (skips fetch):
   * { attempts, comparison, attempt_count, … }
   */
  history: { type: Object, default: null },
  /** When set, overrides the default last-two comparison pair. */
  leftId: { type: String, default: '' },
  rightId: { type: String, default: '' },
})

const loading = ref(false)
const error = ref('')
const payload = ref(null)
const selectedLeft = ref('')
const selectedRight = ref('')
const liveComparison = ref(null)

const attempts = computed(() => payload.value?.attempts || [])
const attemptCount = computed(() => payload.value?.attempt_count ?? attempts.value.length)

const comparison = computed(() => {
  if (liveComparison.value) return liveComparison.value
  return payload.value?.comparison || null
})

const hasPair = computed(
  () => Boolean(comparison.value?.left && comparison.value?.right),
)

function axisChanged(axis) {
  return Boolean(comparison.value?.axes?.[axis]?.changed)
}

function display(value) {
  if (value === null || value === undefined || value === '') return '—'
  return String(value)
}

async function load() {
  error.value = ''
  liveComparison.value = null

  if (props.history && typeof props.history === 'object') {
    payload.value = props.history
    seedSelection()
    return
  }

  loading.value = true
  try {
    let data
    if (props.artifactId) {
      data = await getArtifactHistory(props.artifactId)
    } else if (props.jobId && props.kind) {
      data = await getChainHistory({
        jobId: props.jobId,
        kind: props.kind,
        sceneId: props.sceneId || undefined,
      })
    } else {
      payload.value = null
      return
    }
    payload.value = data
    seedSelection()

    if (props.leftId && props.rightId && props.leftId !== props.rightId) {
      liveComparison.value = await compareArtifacts(props.leftId, props.rightId)
      selectedLeft.value = props.leftId
      selectedRight.value = props.rightId
    }
  } catch (err) {
    error.value = err?.message || 'Failed to load attempt history'
    payload.value = null
  } finally {
    loading.value = false
  }
}

function seedSelection() {
  const list = attempts.value
  if (list.length >= 2) {
    selectedLeft.value = list[list.length - 2].artifact_id
    selectedRight.value = list[list.length - 1].artifact_id
  } else if (list.length === 1) {
    selectedLeft.value = list[0].artifact_id
    selectedRight.value = ''
  } else {
    selectedLeft.value = ''
    selectedRight.value = ''
  }
}

async function onSelectChange() {
  if (!selectedLeft.value || !selectedRight.value) {
    liveComparison.value = null
    return
  }
  if (selectedLeft.value === selectedRight.value) {
    liveComparison.value = null
    error.value = 'Pick two different versions to compare'
    return
  }
  error.value = ''
  loading.value = true
  try {
    liveComparison.value = await compareArtifacts(
      selectedLeft.value,
      selectedRight.value,
    )
  } catch (err) {
    error.value = err?.message || 'Comparison failed'
    liveComparison.value = null
  } finally {
    loading.value = false
  }
}

watch(
  () => [
    props.artifactId,
    props.jobId,
    props.kind,
    props.sceneId,
    props.history,
    props.leftId,
    props.rightId,
  ],
  () => {
    load()
  },
  { immediate: true, deep: true },
)
</script>

<template>
  <div class="attempt-history" data-testid="attempt-history">
    <header class="hist-head">
      <h3>Attempt history</h3>
      <span v-if="attemptCount" class="count-pill">
        {{ attemptCount }} version{{ attemptCount === 1 ? '' : 's' }}
      </span>
    </header>

    <p v-if="loading" class="muted small" role="status">Loading history…</p>
    <p v-else-if="error" class="error small" role="alert">{{ error }}</p>
    <p v-else-if="!attempts.length" class="muted small">
      No artifact versions recorded for this chain yet.
    </p>

    <template v-else>
      <ol class="attempt-list" aria-label="Artifact versions">
        <li
          v-for="attempt in attempts"
          :key="attempt.artifact_id"
          class="attempt-row"
          :class="{ superseded: attempt.is_superseded, active: !attempt.is_superseded }"
        >
          <div class="attempt-meta">
            <strong>v{{ attempt.version }}</strong>
            <code class="art-id">{{ attempt.artifact_id }}</code>
            <span v-if="attempt.is_superseded" class="tag">superseded</span>
            <span v-else class="tag active-tag">active</span>
          </div>
          <dl class="axes">
            <div>
              <dt>Provider instance</dt>
              <dd>{{ display(attempt.provider_instance_id) }}</dd>
            </div>
            <div>
              <dt>Seed</dt>
              <dd>{{ display(attempt.seed) }}</dd>
            </div>
            <div>
              <dt>Prompt revision</dt>
              <dd>{{ display(attempt.prompt_revision) }}</dd>
            </div>
          </dl>
        </li>
      </ol>

      <section
        v-if="attempts.length >= 2"
        class="comparison"
        aria-label="Side-by-side version comparison"
        data-testid="version-comparison"
      >
        <header class="compare-head">
          <h4>Side-by-side comparison</h4>
          <div class="selectors">
            <label>
              Left
              <select v-model="selectedLeft" @change="onSelectChange">
                <option
                  v-for="attempt in attempts"
                  :key="`L-${attempt.artifact_id}`"
                  :value="attempt.artifact_id"
                >
                  v{{ attempt.version }}
                </option>
              </select>
            </label>
            <label>
              Right
              <select v-model="selectedRight" @change="onSelectChange">
                <option
                  v-for="attempt in attempts"
                  :key="`R-${attempt.artifact_id}`"
                  :value="attempt.artifact_id"
                >
                  v{{ attempt.version }}
                </option>
              </select>
            </label>
          </div>
        </header>

        <div v-if="hasPair" class="compare-grid">
          <article class="compare-card" data-side="left">
            <h5>
              v{{ comparison.left.version }}
              <code>{{ comparison.left.artifact_id }}</code>
            </h5>
            <dl class="axes">
              <div :class="{ changed: axisChanged('provider_instance_id') }">
                <dt>Provider instance</dt>
                <dd>{{ display(comparison.left.provider_instance_id) }}</dd>
              </div>
              <div :class="{ changed: axisChanged('seed') }">
                <dt>Seed</dt>
                <dd>{{ display(comparison.left.seed) }}</dd>
              </div>
              <div :class="{ changed: axisChanged('prompt_revision') }">
                <dt>Prompt revision</dt>
                <dd>{{ display(comparison.left.prompt_revision) }}</dd>
              </div>
            </dl>
            <p class="path muted small"><code>{{ comparison.left.path }}</code></p>
          </article>

          <article class="compare-card" data-side="right">
            <h5>
              v{{ comparison.right.version }}
              <code>{{ comparison.right.artifact_id }}</code>
            </h5>
            <dl class="axes">
              <div :class="{ changed: axisChanged('provider_instance_id') }">
                <dt>Provider instance</dt>
                <dd>{{ display(comparison.right.provider_instance_id) }}</dd>
              </div>
              <div :class="{ changed: axisChanged('seed') }">
                <dt>Seed</dt>
                <dd>{{ display(comparison.right.seed) }}</dd>
              </div>
              <div :class="{ changed: axisChanged('prompt_revision') }">
                <dt>Prompt revision</dt>
                <dd>{{ display(comparison.right.prompt_revision) }}</dd>
              </div>
            </dl>
            <p class="path muted small"><code>{{ comparison.right.path }}</code></p>
          </article>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.attempt-history {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.hist-head,
.compare-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.hist-head h3,
.compare-head h4 {
  margin: 0;
  font-family: var(--display);
  font-size: 15px;
  font-weight: 600;
  letter-spacing: -0.4px;
  color: var(--text);
}

.count-pill {
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  padding: 4px 10px;
  border-radius: 20px;
  color: var(--text-2);
  background: var(--bg-2);
  box-shadow: inset 0 0 0 1px var(--line);
}

.attempt-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.attempt-row {
  border: 1px solid var(--line);
  border-radius: var(--r);
  padding: 10px 12px;
  background: var(--panel-grad);
  box-shadow: var(--hairline-top), 0 1px 2px rgba(0, 0, 0, 0.3);
  transition: border-color 0.18s, background 0.18s;
}

.attempt-row:hover {
  border-color: var(--line-2);
  background: var(--panel-grad2);
}

.attempt-row.active {
  border-color: var(--accent-line-2);
  background: var(--accent-wash);
}

.attempt-row.superseded {
  opacity: 0.85;
}

.attempt-meta {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
  margin-bottom: 7px;
}

.attempt-meta strong {
  font-family: var(--display);
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
}

.art-id {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text-2);
}

.tag {
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding: 4px 10px;
  border-radius: 20px;
  background: var(--bg-2);
  color: var(--queue);
  box-shadow: inset 0 0 0 1px var(--line);
}

.active-tag {
  color: var(--ok);
  background: var(--ok-dim);
  box-shadow: inset 0 0 0 1px var(--ok-line);
}

.axes {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 7px 10px;
  margin: 0;
}

.axes dt {
  margin: 0;
  font-family: var(--mono);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: var(--muted);
}

.axes dd {
  margin: 3px 0 0;
  font-size: 12.5px;
  color: var(--text-2);
  word-break: break-word;
}

.axes .changed dd {
  color: var(--warn);
  font-weight: 600;
}

.comparison {
  border-top: 1px solid var(--line-soft);
  padding-top: 12px;
}

.selectors {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.selectors label {
  display: flex;
  align-items: center;
  gap: 7px;
  font-family: var(--mono);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: var(--muted);
}

/* The label wraps its control, so the eyebrow casing is reset here — an
   uppercased option list would misreport the stored version. */
.selectors select {
  background: var(--panel);
  color: var(--text);
  border: 1px solid var(--line);
  border-radius: var(--r-s);
  padding: 6px 9px;
  font-family: var(--body);
  font-size: 12px;
  text-transform: none;
  letter-spacing: 0.1px;
  cursor: pointer;
}

.selectors select:focus {
  outline: none;
  border-color: var(--accent-line-2);
  box-shadow: 0 0 0 3px var(--accent-ring);
}

.compare-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  margin-top: 10px;
}

.compare-card {
  border: 1px solid var(--line);
  border-radius: var(--r);
  padding: 11px 12px;
  background: var(--panel-grad);
  box-shadow: var(--hairline-top), 0 1px 2px rgba(0, 0, 0, 0.3);
}

.compare-card h5 {
  margin: 0 0 9px;
  font-family: var(--display);
  font-size: 13px;
  font-weight: 600;
  letter-spacing: -0.4px;
  color: var(--text);
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  align-items: baseline;
}

.compare-card h5 code {
  font-family: var(--mono);
  font-size: 11px;
  font-weight: 400;
  color: var(--muted);
}

.path {
  margin: 9px 0 0;
}

.path code {
  font-family: var(--mono);
  font-size: 11px;
}

.muted {
  color: var(--muted);
}

.small {
  font-size: 12px;
}

.error {
  color: var(--fail);
}

@media (max-width: 640px) {
  .axes,
  .compare-grid {
    grid-template-columns: 1fr;
  }
}
</style>
