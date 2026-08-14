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
  gap: 0.75rem;
}

.hist-head,
.compare-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.hist-head h3,
.compare-head h4 {
  margin: 0;
  font-size: 0.95rem;
}

.count-pill {
  font-size: 0.75rem;
  padding: 0.15rem 0.5rem;
  border-radius: 999px;
  background: var(--bg-elevated, #1e2a3a);
  border: 1px solid var(--border, #2a3a4e);
}

.attempt-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.attempt-row {
  border: 1px solid var(--border, #1e2a3a);
  border-radius: 8px;
  padding: 0.55rem 0.7rem;
  background: var(--bg-elevated, #121822);
}

.attempt-row.superseded {
  opacity: 0.85;
}

.attempt-meta {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  flex-wrap: wrap;
  margin-bottom: 0.4rem;
}

.art-id {
  font-size: 0.8rem;
}

.tag {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 0.1rem 0.4rem;
  border-radius: 4px;
  background: var(--bg-surface, #1a2230);
  color: var(--text-muted, #8b9bb0);
}

.active-tag {
  color: var(--ok, #6dcea0);
  border: 1px solid color-mix(in srgb, var(--ok, #6dcea0) 40%, transparent);
}

.axes {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.4rem 0.6rem;
  margin: 0;
}

.axes dt {
  margin: 0;
  font-size: 0.68rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--text-muted, #8b9bb0);
}

.axes dd {
  margin: 0.1rem 0 0;
  font-size: 0.85rem;
  word-break: break-word;
}

.axes .changed dd {
  color: var(--warn, #e6b35a);
  font-weight: 600;
}

.comparison {
  border-top: 1px solid var(--border, #1e2a3a);
  padding-top: 0.75rem;
}

.selectors {
  display: flex;
  gap: 0.6rem;
  flex-wrap: wrap;
}

.selectors label {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.8rem;
  color: var(--text-muted, #8b9bb0);
}

.selectors select {
  background: var(--bg-elevated, #121822);
  color: var(--text, #e8edf3);
  border: 1px solid var(--border, #2a3a4e);
  border-radius: 6px;
  padding: 0.2rem 0.4rem;
}

.compare-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.65rem;
  margin-top: 0.6rem;
}

.compare-card {
  border: 1px solid var(--border, #1e2a3a);
  border-radius: 8px;
  padding: 0.6rem 0.7rem;
  background: var(--bg-elevated, #121822);
}

.compare-card h5 {
  margin: 0 0 0.5rem;
  font-size: 0.9rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  align-items: baseline;
}

.compare-card h5 code {
  font-size: 0.75rem;
  font-weight: 400;
  color: var(--text-muted, #8b9bb0);
}

.path {
  margin: 0.5rem 0 0;
}

.muted {
  color: var(--text-muted, #8b9bb0);
}

.small {
  font-size: 0.8rem;
}

.error {
  color: var(--danger, #f07178);
}

@media (max-width: 640px) {
  .axes,
  .compare-grid {
    grid-template-columns: 1fr;
  }
}
</style>
