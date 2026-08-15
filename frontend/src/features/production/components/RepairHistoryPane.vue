<script setup>
/**
 * Repair history pane (step 11.4).
 *
 * Reads the existing read-only endpoint GET /api/jobs/<job_id>/repair-history
 * (step 8.4) and shows, for a repaired Job: every ReviewIssue the correction
 * loop raised, the node type the Repair Router routed it to, what was retried,
 * and the artifact versions the repair superseded. Prior evidence is never
 * erased, so superseded rows stay visible next to the version that replaced
 * them.
 *
 * The pane never starts a run and never mutates a Job.
 */
import { computed, ref, watch } from 'vue'

import { getJobRepairHistory } from '../api.js'

const props = defineProps({
  /** Bound Job id. Without one there is nothing to reconstruct. */
  jobId: { type: String, default: '' },
  /**
   * Open issue ids on the selected stage (StageProjection.issues). Entries
   * answering one of these are marked as belonging to this stage.
   */
  issueIds: { type: Array, default: () => [] },
  /** Optional preloaded payload (tests / parent-owned fetch) — skips fetch. */
  history: { type: Object, default: null },
})

const loading = ref(false)
const error = ref('')
const payload = ref(null)

const entries = computed(() => payload.value?.entries || payload.value?.sequence || [])

const entryCount = computed(() => payload.value?.entry_count ?? entries.value.length)

const stageIssueIds = computed(() =>
  (props.issueIds || []).filter((id) => typeof id === 'string' && id),
)

/** Superseded versions across the whole Job, oldest evidence first. */
const supersededVersions = computed(
  () => payload.value?.superseded_artifact_versions || [],
)

/**
 * Issue id → the repair entries that answered it. Issues still open on the
 * stage with no entry are shown as unrouted so an escalation is visible.
 */
const issueRows = computed(() => {
  const byIssue = new Map()
  for (const id of stageIssueIds.value) {
    byIssue.set(id, { issueId: id, open: true, entries: [] })
  }
  for (const entry of entries.value) {
    const id = entry?.issue_id
    if (!id) continue
    const row = byIssue.get(id)
    if (row) {
      row.entries.push(entry)
    } else {
      byIssue.set(id, { issueId: id, open: false, entries: [entry] })
    }
  }
  return [...byIssue.values()]
})

function display(value) {
  if (value === null || value === undefined || value === '') return '—'
  return String(value)
}

function belongsToStage(entry) {
  return stageIssueIds.value.includes(entry?.issue_id)
}

async function load() {
  error.value = ''

  if (props.history && typeof props.history === 'object') {
    payload.value = props.history
    return
  }
  if (!props.jobId) {
    payload.value = null
    return
  }

  loading.value = true
  try {
    payload.value = await getJobRepairHistory(props.jobId)
  } catch (err) {
    error.value = err?.message || 'Failed to load repair history'
    payload.value = null
  } finally {
    loading.value = false
  }
}

watch(
  () => [props.jobId, props.history],
  () => {
    load()
  },
  { immediate: true, deep: true },
)
</script>

<template>
  <div class="repair-history" data-testid="repair-history">
    <header class="repair-head">
      <h4>Repair history</h4>
      <span v-if="entryCount" class="count-pill">
        {{ entryCount }} repair{{ entryCount === 1 ? '' : 's' }}
      </span>
    </header>

    <p v-if="loading" class="muted small" role="status">Loading repair history…</p>
    <p v-else-if="error" class="error small" role="alert">{{ error }}</p>
    <p v-else-if="!jobId && !history" class="muted small">
      Bind a Job to reconstruct the repairs the correction loop ran.
    </p>

    <template v-else>
      <section
        v-if="issueRows.length"
        class="issue-block"
        aria-label="Review issues and routing"
        data-testid="repair-issue-rows"
      >
        <h5>Issues</h5>
        <ul class="issue-list">
          <li v-for="row in issueRows" :key="row.issueId" class="issue-row">
            <div class="issue-line">
              <code class="issue-id">{{ row.issueId }}</code>
              <span v-if="row.open" class="tag open-tag">open</span>
              <span v-else class="tag">closed</span>
              <span class="tag">
                {{ row.entries.length }} repair{{ row.entries.length === 1 ? '' : 's' }}
              </span>
            </div>
            <p v-if="!row.entries.length" class="muted small">
              No repair recorded — the router escalated or the issue is still
              awaiting a decision.
            </p>
            <ul v-else class="routing-list">
              <li v-for="entry in row.entries" :key="`${row.issueId}-${entry.id}`">
                routed to <code>{{ display(entry.routed_to_node_type) }}</code>
                — {{ display(entry.action) }} → {{ display(entry.result) }}
              </li>
            </ul>
          </li>
        </ul>
      </section>

      <p v-if="!entries.length" class="muted small">
        No repair has run for this Job.
      </p>

      <ol v-else class="repair-list" aria-label="Repairs in attempt order">
        <li
          v-for="(entry, index) in entries"
          :key="entry.id"
          class="repair-row"
          :class="{ 'this-stage': belongsToStage(entry) }"
          :data-result="entry.result || 'unknown'"
        >
          <div class="repair-line">
            <strong>#{{ index + 1 }}</strong>
            <code class="entry-id">{{ entry.id }}</code>
            <span class="tag action-tag">{{ display(entry.action) }}</span>
            <span class="tag result-tag">{{ display(entry.result) }}</span>
            <span v-if="belongsToStage(entry)" class="tag stage-tag">this stage</span>
          </div>
          <dl class="repair-meta">
            <div>
              <dt>Issue</dt>
              <dd><code>{{ display(entry.issue_id) }}</code></dd>
            </div>
            <div>
              <dt>Routed to</dt>
              <dd><code>{{ display(entry.routed_to_node_type) }}</code></dd>
            </div>
            <div>
              <dt>Scene</dt>
              <dd>{{ display(entry.scene_id) }}</dd>
            </div>
            <div>
              <dt>Provider instance</dt>
              <dd>{{ display(entry.provider_instance_id) }}</dd>
            </div>
            <div>
              <dt>Prompt revision</dt>
              <dd>{{ display(entry.prompt_revision) }}</dd>
            </div>
            <div>
              <dt>Attempted</dt>
              <dd>{{ display(entry.created_at) }}</dd>
            </div>
          </dl>
          <p class="reason small">
            <span class="reason-label">Reason</span> {{ display(entry.reason) }}
          </p>
          <p v-if="entry.instruction" class="reason small">
            <span class="reason-label">Retried with</span> {{ entry.instruction }}
          </p>
          <p class="artifact-line small">
            <span class="reason-label">Artifacts</span>
            <span class="mono">{{ (entry.input_artifact_ids || []).join(', ') || '—' }}</span>
            →
            <span class="mono">{{ (entry.output_artifact_ids || []).join(', ') || '—' }}</span>
          </p>
        </li>
      </ol>

      <section
        v-if="supersededVersions.length"
        class="superseded-block"
        aria-label="Superseded artifact versions"
        data-testid="superseded-versions"
      >
        <h5>Superseded versions</h5>
        <ul class="superseded-list">
          <li v-for="art in supersededVersions" :key="art.artifact_id">
            <code>{{ art.artifact_id }}</code>
            <span class="tag">v{{ display(art.version) }}</span>
            <span class="muted small">
              replaced by <code>{{ display(art.superseded_by) }}</code>
            </span>
          </li>
        </ul>
      </section>
    </template>
  </div>
</template>

<style scoped>
.repair-history {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

.repair-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.repair-head h4 {
  margin: 0;
  font-size: 0.95rem;
}

.issue-block h5,
.superseded-block h5 {
  margin: 0 0 0.35rem;
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--text-muted, #6b7f93);
}

.count-pill {
  font-size: 0.75rem;
  padding: 0.15rem 0.5rem;
  border-radius: 999px;
  background: var(--bg-elevated, #222d3d);
  border: 1px solid var(--border, #1e2a3a);
}

.issue-list,
.repair-list,
.superseded-list,
.routing-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

.routing-list {
  gap: 0.2rem;
  margin-top: 0.25rem;
  font-size: 0.8rem;
  color: var(--text-secondary, #8899aa);
}

.issue-row,
.repair-row {
  border: 1px solid var(--border, #1e2a3a);
  border-radius: 8px;
  padding: 0.5rem 0.65rem;
  background: var(--bg-dark, #0f1520);
}

.repair-row.this-stage {
  border-color: rgba(78, 205, 196, 0.45);
}

.repair-row[data-result='failed'],
.repair-row[data-result='escalated'] {
  border-left: 3px solid var(--coral, #ff6b6b);
}

.issue-line,
.repair-line {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.4rem;
}

.issue-id,
.entry-id,
.mono {
  font-family: var(--font-mono, monospace);
  font-size: 0.78rem;
}

.tag {
  font-size: 0.68rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 0.1rem 0.4rem;
  border-radius: 4px;
  background: var(--bg-elevated, #222d3d);
  color: var(--text-secondary, #8899aa);
  border: 1px solid var(--border, #1e2a3a);
}

.open-tag {
  color: var(--accent-active, #ff9f43);
  border-color: rgba(255, 159, 67, 0.35);
}

.stage-tag {
  color: var(--accent, #4ecdc4);
  border-color: rgba(78, 205, 196, 0.35);
}

.repair-meta {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.35rem 0.6rem;
  margin: 0.45rem 0 0;
}

.repair-meta dt {
  margin: 0;
  font-size: 0.65rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-muted, #6b7f93);
}

.repair-meta dd {
  margin: 0.1rem 0 0;
  font-size: 0.82rem;
  word-break: break-word;
}

.reason,
.artifact-line {
  margin: 0.4rem 0 0;
  line-height: 1.4;
  word-break: break-word;
}

.reason-label {
  font-size: 0.65rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-muted, #6b7f93);
  margin-right: 0.35rem;
}

.superseded-list li {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.4rem;
}

.muted {
  color: var(--text-secondary, #8899aa);
}

.small {
  font-size: 0.8rem;
}

.error {
  color: var(--coral, #ff6b6b);
}

@media (max-width: 640px) {
  .repair-meta {
    grid-template-columns: 1fr;
  }
}
</style>
