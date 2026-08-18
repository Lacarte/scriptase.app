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
  gap: 10px;
  font-family: var(--body);
  font-size: 13px;
  color: var(--text);
}

.repair-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.repair-head h4 {
  margin: 0;
  font-family: var(--display);
  font-size: 13.5px;
  font-weight: 600;
  letter-spacing: -0.2px;
  color: var(--text);
}

/* Micro-label eyebrow — the prototype's section header. */
.issue-block h5,
.superseded-block h5 {
  margin: 0 0 8px;
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: var(--muted);
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

.issue-list,
.repair-list,
.superseded-list,
.routing-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.routing-list {
  gap: 4px;
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-2);
}

/* Recessed well: read-only evidence, never a raised surface. */
.issue-row,
.repair-row {
  padding: 10px 12px;
  background: var(--bg-2);
  border: 1px solid var(--line-soft);
  border-radius: var(--r-s);
  box-shadow: var(--hairline-top);
}

.repair-row.this-stage {
  border-color: var(--accent-line);
  box-shadow: var(--hairline-top), inset 0 0 0 1px var(--accent-line);
}

.repair-row[data-result='failed'],
.repair-row[data-result='escalated'] {
  border-left: 3px solid var(--fail-line-2);
}

.issue-line,
.repair-line {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 7px;
}

.repair-line strong {
  font-family: var(--mono);
  font-size: 11px;
  font-weight: 600;
  color: var(--muted);
}

code {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text-2);
}

.issue-id,
.entry-id,
.mono {
  font-family: var(--mono);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0;
  color: var(--text-2);
}

.tag {
  font-family: var(--mono);
  font-size: 9.5px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding: 2px 8px;
  border-radius: 20px;
  background: var(--bg);
  color: var(--queue);
  border: 1px solid var(--line);
  white-space: nowrap;
}

.open-tag {
  color: var(--warn);
  background: var(--warn-dim);
  border-color: var(--warn-line);
}

.stage-tag {
  color: var(--accent);
  background: var(--accent-dim);
  border-color: var(--accent-line);
}

.repair-row[data-result='failed'] .result-tag,
.repair-row[data-result='escalated'] .result-tag {
  color: var(--fail);
  background: var(--fail-dim);
  border-color: var(--fail-line);
}

.repair-row[data-result='succeeded'] .result-tag,
.repair-row[data-result='repaired'] .result-tag {
  color: var(--ok);
  background: var(--ok-dim);
  border-color: var(--ok-line);
}

.repair-meta {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px 12px;
  margin: 10px 0 0;
}

.repair-meta dt {
  margin: 0;
  font-family: var(--mono);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: var(--muted);
}

.repair-meta dd {
  margin: 3px 0 0;
  font-size: 12.5px;
  color: var(--text);
  word-break: break-word;
}

.reason,
.artifact-line {
  margin: 8px 0 0;
  line-height: 1.5;
  color: var(--text-2);
  word-break: break-word;
}

.reason-label {
  font-family: var(--mono);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: var(--muted);
  margin-right: 7px;
}

.superseded-list li {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 7px;
}

.muted {
  color: var(--muted);
}

.small {
  font-size: 11.5px;
  line-height: 1.5;
}

.error {
  color: var(--fail-text);
  background: var(--fail-dim);
  border: 1px solid var(--fail-line);
  border-radius: var(--r-s);
  padding: 9px 12px;
  margin: 0;
}

@media (max-width: 640px) {
  .repair-meta {
    grid-template-columns: 1fr;
  }
}
</style>
