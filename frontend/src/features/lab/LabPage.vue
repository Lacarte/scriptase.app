<script setup>
/**
 * Prompt Lab — a workbench for the script prompt engine.
 *
 * The prompt *engine* stays in tested code; the Lab makes it visible and
 * measurable. Variants are named bundles of prompt-tuning knobs (data). An
 * experiment runs a (channel × variant × provider) through the real provider
 * and scores the result with the offline Virality Scorer, so a prompt change
 * is measurable immediately — not blind.
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { apiGet, apiPost, apiPut, apiDelete } from '@/shared/api.js'

defineOptions({ name: 'LabPage' })

const TABS = [
  { id: 'test', label: 'Test' },
  { id: 'variants', label: 'Variants' },
  { id: 'inspector', label: 'Inspector' },
  { id: 'preview', label: 'Preview' },
  { id: 'performance', label: 'Performance' },
]
const tab = ref('test')
const error = ref('')

// ── Shared catalog: channels + script providers ─────────────────────────────
const channels = ref([])
const providers = ref([])
const variants = ref([])

async function loadCatalog() {
  try {
    const [ch, pv, vs] = await Promise.all([
      apiGet('/api/channels', { limit: 500 }).catch(() => ({ channels: [] })),
      apiGet('/api/providers').catch(() => ({ domains: {} })),
      apiGet('/api/lab/variants').catch(() => ({ variants: [] })),
    ])
    channels.value = ch.channels || []
    const script = (pv.domains && pv.domains.script && pv.domains.script.providers) || []
    providers.value = script.map((p) => ({ id: p.id, label: p.label }))
    variants.value = vs.variants || []
  } catch (exc) {
    error.value = exc.message || 'Could not load the Lab catalog'
  }
}

// ── Test: run an experiment and score it ────────────────────────────────────
const run = reactive({ channel_id: '', provider_id: 'script_n8n', variant_id: 'builtin', idea: '' })
const running = ref(false)
const results = ref([]) // most recent first, kept for side-by-side compare

async function runExperiment() {
  running.value = true
  error.value = ''
  try {
    const body = {
      channel_id: run.channel_id || null,
      provider_id: run.provider_id,
      variant_id: run.variant_id,
      overrides: run.idea ? { idea: run.idea } : {},
    }
    const data = await apiPost('/api/lab/run', body)
    results.value.unshift(data.run)
    results.value = results.value.slice(0, 6)
    await loadRuns()
  } catch (exc) {
    error.value = exc.message || 'The run failed — check the script webhook is reachable.'
  } finally {
    running.value = false
  }
}

const compareA = ref(0)
const compareB = ref(1)
const bandClass = (band) => `band-${band}`

// ── Variants: create / edit / delete ────────────────────────────────────────
const editing = ref(null) // the variant being edited, or a fresh draft
function newVariant() {
  editing.value = {
    id: null, name: '', description: '',
    angle_pool: [], extra_directives: [], tone_override: '',
    language_level: '', temperature: null, word_target_ratio: 1,
  }
}
const angleText = computed({
  get: () => (editing.value?.angle_pool || []).join('\n'),
  set: (v) => { if (editing.value) editing.value.angle_pool = v.split('\n').map((s) => s.trim()).filter(Boolean) },
})
const directiveText = computed({
  get: () => (editing.value?.extra_directives || []).join('\n'),
  set: (v) => { if (editing.value) editing.value.extra_directives = v.split('\n').map((s) => s.trim()).filter(Boolean) },
})

async function saveVariant() {
  error.value = ''
  const v = editing.value
  try {
    if (v.id) await apiPut(`/api/lab/variants/${v.id}`, v)
    else await apiPost('/api/lab/variants', v)
    editing.value = null
    await loadCatalog()
  } catch (exc) {
    error.value = exc.message || 'Could not save the variant'
  }
}
async function removeVariant(id) {
  error.value = ''
  try {
    await apiDelete(`/api/lab/variants/${id}`)
    await loadCatalog()
  } catch (exc) {
    error.value = exc.message || 'Could not delete the variant'
  }
}

// ── Performance leaderboard + runs ──────────────────────────────────────────
const leaderboard = ref([])
async function loadRuns() {
  try {
    const data = await apiGet('/api/lab/runs', { limit: 100 })
    leaderboard.value = data.leaderboard || []
  } catch { /* non-fatal */ }
}

// ── Inspector + Preview (section 1, unchanged) ──────────────────────────────
const recent = ref([])
const selectedId = ref('')
const selected = computed(() => recent.value.find((r) => r.project_id === selectedId.value) || null)
async function loadRecent() {
  try {
    const data = await apiGet('/api/lab/prompts', { limit: 40 })
    recent.value = data.prompts || []
    if (recent.value.length && !selectedId.value) selectedId.value = recent.value[0].project_id
  } catch { /* non-fatal */ }
}
const pform = reactive({ preset_style: 'stickman_animation', story_category: 'psychology', niche_preset: 'dark_psychology', language: 'english', duration: 60, idea: '' })
const preview = ref(null)
const previewing = ref(false)
async function runPreview() {
  previewing.value = true
  try { preview.value = await apiPost('/api/lab/prompt-preview', { ...pform }) }
  catch (exc) { error.value = exc.message } finally { previewing.value = false }
}
function copy(text) { if (navigator?.clipboard) navigator.clipboard.writeText(text || '') }

onMounted(async () => {
  await loadCatalog()
  await Promise.all([loadRuns(), loadRecent()])
})
</script>

<template>
  <div class="lab">
    <header class="lab-head">
      <h1>Prompt Lab</h1>
      <p class="sub">Test prompt variants against real providers and measure the impact on the score.</p>
      <nav class="lab-tabs" role="tablist" aria-label="Lab sections">
        <button
          v-for="t in TABS" :key="t.id" type="button" class="lab-tab"
          :class="{ on: tab === t.id }" role="tab" :aria-selected="String(tab === t.id)"
          @click="tab = t.id"
        >{{ t.label }}</button>
      </nav>
    </header>

    <p v-if="error" class="lab-error">{{ error }}</p>

    <!-- ── TEST ─────────────────────────────────────────────────────────── -->
    <section v-if="tab === 'test'" class="lab-body split">
      <aside class="lab-form">
        <div class="list-head"><span>Run a variant</span></div>
        <label class="f">Channel
          <select v-model="run.channel_id">
            <option value="">— manual / no channel —</option>
            <option v-for="c in channels" :key="c.id" :value="c.id">{{ c.name }}</option>
          </select>
        </label>
        <label class="f">Provider
          <select v-model="run.provider_id">
            <option v-for="p in providers" :key="p.id" :value="p.id">{{ p.label }}</option>
          </select>
        </label>
        <label class="f">Variant
          <select v-model="run.variant_id">
            <option v-for="v in variants" :key="v.id" :value="v.id">{{ v.name }}</option>
          </select>
        </label>
        <label class="f">Idea (optional)
          <textarea v-model="run.idea" rows="2" placeholder="what the story is about"></textarea>
        </label>
        <button type="button" class="primary" :disabled="running" @click="runExperiment">
          {{ running ? 'Generating & scoring…' : 'Run test' }}
        </button>
        <p class="hint">
          Generates a real script through the provider and scores it with the offline
          Virality Scorer — so you see the impact immediately. Run again to build up
          results and compare.
        </p>
      </aside>

      <div class="lab-detail">
        <p v-if="!results.length" class="empty">Run a test to see the script and its score.</p>
        <template v-else>
          <div v-if="results.length > 1" class="compare-bar">
            <span>Compare</span>
            <select v-model.number="compareA"><option v-for="(r, i) in results" :key="i" :value="i">{{ i + 1 }}. {{ r.variant.name }} · {{ r.score.score }}</option></select>
            <span>vs</span>
            <select v-model.number="compareB"><option v-for="(r, i) in results" :key="i" :value="i">{{ i + 1 }}. {{ r.variant.name }} · {{ r.score.score }}</option></select>
          </div>

          <div class="runs" :class="{ dual: results.length > 1 }">
            <article v-for="idx in (results.length > 1 ? [compareA, compareB] : [0])" :key="idx" class="run-card">
              <div class="run-top">
                <span class="score-badge" :class="bandClass(results[idx].score.band)">{{ results[idx].score.score }}</span>
                <div class="run-meta">
                  <div class="rm-variant">{{ results[idx].variant.name }}</div>
                  <div class="rm-sub">{{ results[idx].score.band }} · {{ results[idx].word_count }}w · {{ results[idx].provider_id }}</div>
                </div>
              </div>
              <div class="dims">
                <div v-for="d in results[idx].score.dimensions" :key="d.id" class="dim">
                  <span class="dim-name">{{ d.id.replaceAll('_', ' ') }}</span>
                  <span class="dim-bar"><i :style="{ width: Math.min(100, d.points * 3) + '%' }"></i></span>
                  <span class="dim-pts">{{ d.points }}</span>
                </div>
              </div>
              <pre class="raw script">{{ results[idx].story_text }}</pre>
            </article>
          </div>
        </template>
      </div>
    </section>

    <!-- ── VARIANTS ─────────────────────────────────────────────────────── -->
    <section v-else-if="tab === 'variants'" class="lab-body split">
      <aside class="lab-list">
        <div class="list-head"><span>Variants</span><button type="button" class="mini" @click="newVariant">+ New</button></div>
        <button
          v-for="v in variants" :key="v.id" type="button" class="list-item"
          :class="{ on: editing && editing.id === v.id }"
          @click="editing = v.builtin ? null : { ...v }"
        >
          <span class="li-title">{{ v.name }}<span v-if="v.builtin" class="soon-chip">control</span></span>
          <span class="li-meta">{{ v.description || 'no description' }}</span>
        </button>
      </aside>

      <div class="lab-detail">
        <p v-if="!editing" class="empty">Select a variant to edit, or create a new one. The built-in control can't be edited.</p>
        <template v-else>
          <div class="list-head"><span>{{ editing.id ? 'Edit variant' : 'New variant' }}</span></div>
          <label class="f">Name<input v-model="editing.name" placeholder="e.g. Question hooks, tighter" /></label>
          <label class="f">Description<input v-model="editing.description" placeholder="what this variant tries" /></label>
          <label class="f">Angle pool <span class="fn">— one per line; empty uses the built-in pool</span>
            <textarea v-model="angleText" rows="4" placeholder="Begin with a provocative question…"></textarea>
          </label>
          <label class="f">Extra directives <span class="fn">— one per line, appended to the prompt</span>
            <textarea v-model="directiveText" rows="3" placeholder="Make it more emotional"></textarea>
          </label>
          <div class="f2">
            <label class="f">Tone override<input v-model="editing.tone_override" placeholder="optional" /></label>
            <label class="f">Language level
              <select v-model="editing.language_level">
                <option value="">default</option>
                <option>beginner</option><option>intermediate</option><option>advanced</option><option>native</option>
              </select>
            </label>
          </div>
          <div class="f2">
            <label class="f">Temperature<input v-model.number="editing.temperature" type="number" step="0.1" min="0" max="2" placeholder="default" /></label>
            <label class="f">Word target ×<input v-model.number="editing.word_target_ratio" type="number" step="0.05" min="0.5" max="2" /></label>
          </div>
          <div class="btn-row">
            <button type="button" class="primary" @click="saveVariant">{{ editing.id ? 'Save' : 'Create' }}</button>
            <button v-if="editing.id" type="button" class="danger" @click="removeVariant(editing.id)">Delete</button>
            <button type="button" class="ghost" @click="editing = null">Cancel</button>
          </div>
        </template>
      </div>
    </section>

    <!-- ── PERFORMANCE (leaderboard from offline scores; real metrics later) ─ -->
    <section v-else-if="tab === 'performance'" class="lab-body">
      <div class="lab-detail">
        <div class="list-head"><span>Variant leaderboard — average Virality score</span><button type="button" class="mini" @click="loadRuns">↻</button></div>
        <p v-if="!leaderboard.length" class="empty">Run some tests to build a leaderboard.</p>
        <table v-else class="board">
          <thead><tr><th>Variant</th><th>Runs</th><th>Avg score</th></tr></thead>
          <tbody>
            <tr v-for="row in leaderboard" :key="row.variant_id">
              <td>{{ row.name }}</td><td>{{ row.runs }}</td>
              <td><b>{{ row.avg_score }}</b></td>
            </tr>
          </tbody>
        </table>
        <p class="hint">
          Ranked by the offline Virality Scorer today. Real view/retention data
          plugs in here later to rank by actual performance.
        </p>
      </div>
    </section>

    <!-- ── INSPECTOR ────────────────────────────────────────────────────── -->
    <section v-else-if="tab === 'inspector'" class="lab-body split">
      <aside class="lab-list">
        <div class="list-head"><span>Recent scripts</span><button type="button" class="mini" @click="loadRecent">↻</button></div>
        <p v-if="!recent.length" class="empty">No scripts with saved prompts yet.</p>
        <button v-for="r in recent" :key="r.project_id" type="button" class="list-item" :class="{ on: selectedId === r.project_id }" @click="selectedId = r.project_id">
          <span class="li-title">{{ r.concept_family || r.story_category || r.project_id }}</span>
          <span class="li-meta">{{ r.story_category }} · {{ r.word_count }}w</span>
        </button>
      </aside>
      <div class="lab-detail">
        <p v-if="!selected" class="empty">Select a script to inspect its prompt.</p>
        <template v-else>
          <h3 class="block-h">User prompt — decomposed</h3>
          <div class="parts">
            <div v-for="(p, i) in selected.prompt.decomposed" :key="i" class="part">
              <span class="part-label">{{ p.label }}</span><p class="part-text">{{ p.text }}</p>
            </div>
          </div>
          <div class="raw-row"><h3 class="block-h">System prompt</h3><button type="button" class="mini" @click="copy(selected.prompt.system_prompt)">Copy</button></div>
          <pre class="raw">{{ selected.prompt.system_prompt }}</pre>
          <div class="raw-row"><h3 class="block-h">Script</h3></div>
          <pre class="raw script">{{ selected.story_text }}</pre>
        </template>
      </div>
    </section>

    <!-- ── PREVIEW ──────────────────────────────────────────────────────── -->
    <section v-else class="lab-body split">
      <aside class="lab-form">
        <div class="list-head"><span>Inputs</span></div>
        <label class="f">Niche preset<input v-model="pform.niche_preset" /></label>
        <label class="f">Story category<input v-model="pform.story_category" /></label>
        <label class="f">Visual style<input v-model="pform.preset_style" /></label>
        <div class="f2">
          <label class="f">Language<input v-model="pform.language" /></label>
          <label class="f">Duration<input v-model.number="pform.duration" type="number" /></label>
        </div>
        <label class="f">Idea<textarea v-model="pform.idea" rows="2"></textarea></label>
        <button type="button" class="primary" :disabled="previewing" @click="runPreview">{{ previewing ? 'Building…' : 'Build prompt' }}</button>
        <p class="hint">Each build rotates the angle, concept, and seed — the diversity engine.</p>
      </aside>
      <div class="lab-detail">
        <p v-if="!preview" class="empty">Build a prompt to preview it.</p>
        <template v-else>
          <h3 class="block-h">User prompt — decomposed</h3>
          <div class="parts">
            <div v-for="(p, i) in preview.decomposed" :key="i" class="part">
              <span class="part-label">{{ p.label }}</span><p class="part-text">{{ p.text }}</p>
            </div>
          </div>
          <div class="raw-row"><h3 class="block-h">System prompt</h3><button type="button" class="mini" @click="copy(preview.system_prompt)">Copy</button></div>
          <pre class="raw">{{ preview.system_prompt }}</pre>
        </template>
      </div>
    </section>
  </div>
</template>

<style scoped>
.lab { padding: 22px 26px; max-width: 1200px; margin: 0 auto; }
.lab-head h1 { margin: 0; font-family: var(--display); font-size: 22px; font-weight: 600; }
.lab-head .sub { margin: 6px 0 0; color: var(--muted); font-size: 13px; }
.lab-tabs { display: flex; gap: 6px; margin-top: 16px; border-bottom: 1px solid var(--line-soft); }
.lab-tab { border: 0; background: none; color: var(--muted); font: inherit; font-size: 13px; padding: 9px 12px;
  cursor: pointer; border-bottom: 2px solid transparent; margin-bottom: -1px; }
.lab-tab:hover { color: var(--text-2); }
.lab-tab.on { color: var(--text); border-bottom-color: var(--accent); }
.lab-error { color: var(--fail-text); background: var(--fail-dim); border: 1px solid var(--fail-line);
  border-radius: var(--r-s); padding: 8px 12px; margin: 14px 0 0; font-size: 13px; }

.lab-body { margin-top: 18px; }
.split { display: grid; grid-template-columns: 300px 1fr; gap: 16px; align-items: start; }
.lab-list, .lab-form { border: 1px solid var(--line); background: var(--panel-grad); border-radius: var(--r-s);
  padding: 8px; box-shadow: var(--hairline-top); position: sticky; top: 14px; }
.list-head { display: flex; justify-content: space-between; align-items: center; padding: 6px 8px 10px;
  color: var(--muted); font-family: var(--mono); font-size: 10px; letter-spacing: .5px; text-transform: uppercase; }
.list-item { display: flex; flex-direction: column; gap: 3px; width: 100%; text-align: left; border: 0;
  background: transparent; color: var(--text); font: inherit; cursor: pointer; padding: 9px 10px; border-radius: var(--r-s); }
.list-item:hover { background: var(--raise); }
.list-item.on { background: var(--accent-wash); }
.li-title { font-size: 13px; font-weight: 600; display: flex; align-items: center; gap: 6px; }
.li-meta { font-family: var(--mono); font-size: 10px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.lab-detail { border: 1px solid var(--line); background: var(--panel-grad); border-radius: var(--r-s);
  padding: 16px 18px; box-shadow: var(--hairline-top); min-height: 300px; }
.empty { color: var(--muted); font-size: 13px; padding: 24px 4px; text-align: center; }

.f { display: flex; flex-direction: column; gap: 5px; padding: 6px 8px; font-size: 11px; color: var(--muted);
  font-family: var(--mono); text-transform: uppercase; letter-spacing: .3px; }
.f .fn { text-transform: none; letter-spacing: 0; color: var(--faint); font-size: 10px; }
.f input, .f textarea, .f select { font-family: var(--display); font-size: 13px; text-transform: none; letter-spacing: 0;
  color: var(--text); background: var(--panel); border: 1px solid var(--line); border-radius: var(--r-s); padding: 7px 9px; }
.f input:focus, .f textarea:focus, .f select:focus { outline: none; border-color: var(--accent-line-2); }
.f2 { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; }
.primary { padding: 9px 14px; border: 0; border-radius: var(--r-s); background: var(--accent-grad); color: #fff;
  font: inherit; font-weight: 600; cursor: pointer; }
.primary { width: calc(100% - 16px); margin: 8px; }
.primary:disabled { opacity: .6; cursor: default; }
.hint { color: var(--muted); font-size: 11px; padding: 0 10px 8px; line-height: 1.5; }
.mini { border: 1px solid var(--line); background: var(--panel); color: var(--text-2); font: inherit; font-size: 11px;
  padding: 3px 8px; border-radius: var(--r-s); cursor: pointer; }
.mini:hover { border-color: var(--line-2); }
.btn-row { display: flex; gap: 8px; padding: 8px; }
.btn-row .primary { width: auto; margin: 0; }
.danger { border: 1px solid var(--fail-line); background: var(--fail-dim); color: var(--fail-text); font: inherit;
  padding: 9px 14px; border-radius: var(--r-s); cursor: pointer; }
.ghost { border: 1px solid var(--line); background: transparent; color: var(--muted); font: inherit; padding: 9px 14px;
  border-radius: var(--r-s); cursor: pointer; }
.soon-chip { font-family: var(--mono); font-size: 8px; letter-spacing: .4px; text-transform: uppercase; color: var(--faint);
  background: var(--bg-2); box-shadow: inset 0 0 0 1px var(--line-soft); padding: 1px 5px; border-radius: 999px; }

.compare-bar { display: flex; align-items: center; gap: 8px; margin-bottom: 14px; color: var(--muted);
  font-family: var(--mono); font-size: 11px; }
.compare-bar select { background: var(--panel); border: 1px solid var(--line); border-radius: var(--r-s);
  color: var(--text); padding: 4px 6px; font-size: 11px; }
.runs.dual { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.run-card { border: 1px solid var(--line-soft); border-radius: var(--r-s); padding: 12px; background: var(--bg-2); }
.run-top { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.score-badge { width: 46px; height: 46px; border-radius: 12px; display: grid; place-items: center;
  font-family: var(--display); font-weight: 700; font-size: 18px; flex: none; }
.band-strong { background: rgba(53,192,138,.18); color: var(--ok); box-shadow: inset 0 0 0 1px var(--ok-line); }
.band-solid { background: rgba(88,166,255,.18); color: var(--run); box-shadow: inset 0 0 0 1px var(--run-line); }
.band-weak { background: rgba(240,173,75,.18); color: var(--warn); box-shadow: inset 0 0 0 1px var(--warn-line); }
.band-poor { background: rgba(255,95,110,.18); color: var(--fail); box-shadow: inset 0 0 0 1px var(--fail-line); }
.rm-variant { font-family: var(--display); font-weight: 600; font-size: 14px; }
.rm-sub { font-family: var(--mono); font-size: 11px; color: var(--muted); }
.dims { display: flex; flex-direction: column; gap: 5px; margin-bottom: 12px; }
.dim { display: grid; grid-template-columns: 90px 1fr 34px; align-items: center; gap: 8px; font-size: 11px; }
.dim-name { font-family: var(--mono); color: var(--muted); text-transform: capitalize; }
.dim-bar { height: 6px; background: var(--line-soft); border-radius: 999px; overflow: hidden; }
.dim-bar i { display: block; height: 100%; background: var(--accent-grad); }
.dim-pts { text-align: right; font-family: var(--mono); color: var(--text-2); }

.block-h { font-size: 12px; font-weight: 600; color: var(--text-2); margin: 14px 0 8px; text-transform: uppercase; letter-spacing: .4px; }
.parts { display: flex; flex-direction: column; gap: 8px; }
.part { border: 1px solid var(--line-soft); border-radius: var(--r-s); padding: 9px 11px; background: var(--bg-2); }
.part-label { font-family: var(--mono); font-size: 9px; letter-spacing: .5px; text-transform: uppercase; color: var(--accent); }
.part-text { margin: 4px 0 0; font-size: 12.5px; color: var(--text-2); line-height: 1.5; white-space: pre-wrap; }
.raw-row { display: flex; justify-content: space-between; align-items: center; }
.raw { margin: 8px 0 0; padding: 12px; background: var(--bg-2); border: 1px solid var(--line-soft); border-radius: var(--r-s);
  font-family: var(--mono); font-size: 11.5px; color: var(--text-2); white-space: pre-wrap; overflow: auto;
  line-height: 1.55; max-height: 340px; }
.raw.script { color: var(--text); }

.board { width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 13px; }
.board th { text-align: left; color: var(--muted); font-family: var(--mono); font-size: 10px; text-transform: uppercase;
  letter-spacing: .4px; padding: 8px 10px; border-bottom: 1px solid var(--line-soft); }
.board td { padding: 9px 10px; border-bottom: 1px solid var(--line-soft); }
.board td b { color: var(--accent); }

@media (max-width: 860px) { .split { grid-template-columns: 1fr; } .runs.dual { grid-template-columns: 1fr; } }
</style>
