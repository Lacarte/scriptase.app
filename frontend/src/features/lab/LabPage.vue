<script setup>
/**
 * Prompt Lab — makes the script prompt engineering (normally buried in
 * prompts.py) visible, inspectable, and testable.
 *
 * Section 1 (Inspector + Preview) is live: see the exact system/user prompt a
 * script was built from, decomposed into its parts, and preview what a set of
 * inputs would produce (with the diversity engine visible across regenerations).
 * Sections 2-4 (Test, Config, Performance) are staged as labeled placeholders.
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { apiGet, apiPost } from '@/shared/api.js'

defineOptions({ name: 'LabPage' })

const TABS = [
  { id: 'inspector', label: 'Inspector', ready: true },
  { id: 'preview', label: 'Preview', ready: true },
  { id: 'test', label: 'Test', ready: false },
  { id: 'config', label: 'Config', ready: false },
  { id: 'performance', label: 'Performance', ready: false },
]
const tab = ref('inspector')

// ── Inspector: recent generated scripts + their saved prompts ───────────────
const recent = ref([])
const selectedId = ref('')
const loading = ref(false)
const error = ref('')

const selected = computed(() => recent.value.find((r) => r.project_id === selectedId.value) || null)

async function loadRecent() {
  loading.value = true
  error.value = ''
  try {
    const data = await apiGet('/api/lab/prompts', { limit: 40 })
    recent.value = data.prompts || []
    if (recent.value.length && !selectedId.value) selectedId.value = recent.value[0].project_id
  } catch (exc) {
    error.value = exc.message || 'Could not load prompts'
  } finally {
    loading.value = false
  }
}

// ── Preview: build the prompt for chosen inputs (no generation) ─────────────
const form = reactive({
  preset_style: 'stickman_animation',
  story_category: 'psychology',
  niche_preset: 'dark_psychology',
  story_tone: '',
  language: 'english',
  duration: 60,
  idea: '',
})
const preview = ref(null)
const previewing = ref(false)

async function runPreview() {
  previewing.value = true
  error.value = ''
  try {
    preview.value = await apiPost('/api/lab/prompt-preview', { ...form })
  } catch (exc) {
    error.value = exc.message || 'Could not build the prompt'
  } finally {
    previewing.value = false
  }
}

function copy(text) {
  if (navigator?.clipboard) navigator.clipboard.writeText(text || '')
}

onMounted(loadRecent)
</script>

<template>
  <div class="lab">
    <header class="lab-head">
      <h1>Prompt Lab</h1>
      <p class="sub">See, test, and improve the prompts that write your scripts.</p>
      <nav class="lab-tabs" role="tablist" aria-label="Lab sections">
        <button
          v-for="t in TABS"
          :key="t.id"
          type="button"
          class="lab-tab"
          :class="{ on: tab === t.id, soon: !t.ready }"
          role="tab"
          :aria-selected="String(tab === t.id)"
          @click="tab = t.id"
        >
          {{ t.label }}<span v-if="!t.ready" class="soon-chip">soon</span>
        </button>
      </nav>
    </header>

    <p v-if="error" class="lab-error">{{ error }}</p>

    <!-- ── INSPECTOR ─────────────────────────────────────────────────────── -->
    <section v-if="tab === 'inspector'" class="lab-body split">
      <aside class="lab-list">
        <div class="list-head">
          <span>Recent scripts</span>
          <button type="button" class="mini" @click="loadRecent">↻</button>
        </div>
        <p v-if="loading" class="empty">Loading…</p>
        <p v-else-if="!recent.length" class="empty">
          No scripts with saved prompts yet. Generate a script and it appears here.
        </p>
        <button
          v-for="r in recent"
          :key="r.project_id"
          type="button"
          class="list-item"
          :class="{ on: selectedId === r.project_id }"
          @click="selectedId = r.project_id"
        >
          <span class="li-title">{{ r.concept_family || r.story_category || r.project_id }}</span>
          <span class="li-meta">{{ r.story_category }} · {{ r.word_count }}w · {{ r.duration }}s</span>
        </button>
      </aside>

      <div class="lab-detail">
        <p v-if="!selected" class="empty">Select a script to inspect its prompt.</p>
        <template v-else>
          <div class="detail-head">
            <div>
              <div class="dh-title">{{ selected.concept_family || selected.story_category }}</div>
              <div class="dh-meta">
                {{ selected.preset_style }} · {{ selected.story_category }} ·
                {{ selected.word_count }} words · {{ selected.provider }}
              </div>
            </div>
          </div>

          <h3 class="block-h">User prompt — decomposed</h3>
          <div class="parts">
            <div v-for="(p, i) in selected.prompt.decomposed" :key="i" class="part">
              <span class="part-label">{{ p.label }}</span>
              <p class="part-text">{{ p.text }}</p>
            </div>
          </div>

          <div class="raw-row">
            <h3 class="block-h">System prompt</h3>
            <button type="button" class="mini" @click="copy(selected.prompt.system_prompt)">Copy</button>
          </div>
          <pre class="raw">{{ selected.prompt.system_prompt }}</pre>

          <div class="raw-row">
            <h3 class="block-h">Generated script</h3>
          </div>
          <pre class="raw script">{{ selected.story_text }}</pre>
        </template>
      </div>
    </section>

    <!-- ── PREVIEW ───────────────────────────────────────────────────────── -->
    <section v-else-if="tab === 'preview'" class="lab-body split">
      <aside class="lab-form">
        <div class="list-head"><span>Inputs</span></div>
        <label class="f">Niche preset
          <input v-model="form.niche_preset" placeholder="e.g. dark_psychology" />
        </label>
        <label class="f">Story category
          <input v-model="form.story_category" placeholder="e.g. psychology" />
        </label>
        <label class="f">Visual style
          <input v-model="form.preset_style" placeholder="e.g. stickman_animation" />
        </label>
        <label class="f">Story tone
          <input v-model="form.story_tone" placeholder="optional" />
        </label>
        <div class="f2">
          <label class="f">Language
            <input v-model="form.language" />
          </label>
          <label class="f">Duration (s)
            <input v-model.number="form.duration" type="number" min="10" max="300" />
          </label>
        </div>
        <label class="f">Idea
          <textarea v-model="form.idea" rows="3" placeholder="optional — what the story is about"></textarea>
        </label>
        <button type="button" class="primary" :disabled="previewing" @click="runPreview">
          {{ previewing ? 'Building…' : 'Build prompt' }}
        </button>
        <p class="hint">
          Each build rotates the angle, concept, and seed — click again to see the
          diversity engine vary the prompt for the same inputs.
        </p>
      </aside>

      <div class="lab-detail">
        <p v-if="!preview" class="empty">Set inputs and build a prompt to preview it.</p>
        <template v-else>
          <div class="detail-head">
            <div class="dh-meta">
              target {{ preview.word_target }} words · concept:
              <b>{{ preview.inputs.concept_family || '—' }}</b>
            </div>
          </div>
          <h3 class="block-h">User prompt — decomposed</h3>
          <div class="parts">
            <div v-for="(p, i) in preview.decomposed" :key="i" class="part">
              <span class="part-label">{{ p.label }}</span>
              <p class="part-text">{{ p.text }}</p>
            </div>
          </div>
          <div class="raw-row">
            <h3 class="block-h">System prompt</h3>
            <button type="button" class="mini" @click="copy(preview.system_prompt)">Copy</button>
          </div>
          <pre class="raw">{{ preview.system_prompt }}</pre>
        </template>
      </div>
    </section>

    <!-- ── STAGED SECTIONS ───────────────────────────────────────────────── -->
    <section v-else class="lab-body">
      <div class="placeholder">
        <h2>{{ TABS.find((t) => t.id === tab).label }}</h2>
        <p v-if="tab === 'test'">
          Generate scripts from tweaked inputs and compare two runs side by side —
          a workbench you iterate in without editing code. Coming next.
        </p>
        <p v-else-if="tab === 'config'">
          Edit the angle starters, topic banks, rut-warnings and narrative lenses
          in the UI so you tune the prompt without a deploy. Coming next.
        </p>
        <p v-else-if="tab === 'performance'">
          Tie scripts to real outcomes (views, retention) and rank which angles,
          concepts, and hooks actually perform. Coming next.
        </p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.lab { padding: 22px 26px; max-width: 1200px; margin: 0 auto; }
.lab-head h1 { margin: 0; font-family: var(--display); font-size: 22px; font-weight: 600; }
.lab-head .sub { margin: 6px 0 0; color: var(--muted); font-size: 13px; }
.lab-tabs { display: flex; gap: 6px; margin-top: 16px; border-bottom: 1px solid var(--line-soft); }
.lab-tab {
  border: 0; background: none; color: var(--muted); font: inherit; font-size: 13px;
  padding: 9px 12px; cursor: pointer; border-bottom: 2px solid transparent; margin-bottom: -1px;
  display: inline-flex; align-items: center; gap: 6px;
}
.lab-tab:hover { color: var(--text-2); }
.lab-tab.on { color: var(--text); border-bottom-color: var(--accent); }
.lab-tab.soon { opacity: 0.6; }
.soon-chip {
  font-family: var(--mono); font-size: 8px; letter-spacing: .4px; text-transform: uppercase;
  color: var(--faint); background: var(--bg-2); box-shadow: inset 0 0 0 1px var(--line-soft);
  padding: 1px 5px; border-radius: 999px;
}
.lab-error { color: var(--fail-text); background: var(--fail-dim); border: 1px solid var(--fail-line);
  border-radius: var(--r-s); padding: 8px 12px; margin: 14px 0 0; font-size: 13px; }

.lab-body { margin-top: 18px; }
.split { display: grid; grid-template-columns: 300px 1fr; gap: 16px; align-items: start; }

.lab-list, .lab-form {
  border: 1px solid var(--line); background: var(--panel-grad); border-radius: var(--r-s);
  padding: 8px; box-shadow: var(--hairline-top); position: sticky; top: 14px;
}
.list-head { display: flex; justify-content: space-between; align-items: center;
  padding: 6px 8px 10px; color: var(--muted); font-family: var(--mono); font-size: 10px;
  letter-spacing: .5px; text-transform: uppercase; }
.list-item {
  display: flex; flex-direction: column; gap: 3px; width: 100%; text-align: left;
  border: 0; background: transparent; color: var(--text); font: inherit; cursor: pointer;
  padding: 9px 10px; border-radius: var(--r-s);
}
.list-item:hover { background: var(--raise); }
.list-item.on { background: var(--accent-wash); }
.li-title { font-size: 13px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.li-meta { font-family: var(--mono); font-size: 10px; color: var(--muted); }

.lab-detail {
  border: 1px solid var(--line); background: var(--panel-grad); border-radius: var(--r-s);
  padding: 16px 18px; box-shadow: var(--hairline-top); min-height: 300px;
}
.empty { color: var(--muted); font-size: 13px; padding: 24px 4px; text-align: center; }
.detail-head { border-bottom: 1px solid var(--line-soft); padding-bottom: 12px; margin-bottom: 14px; }
.dh-title { font-family: var(--display); font-size: 16px; font-weight: 600; }
.dh-meta { color: var(--muted); font-family: var(--mono); font-size: 11px; margin-top: 4px; }
.dh-meta b { color: var(--text-2); }

.block-h { font-size: 12px; font-weight: 600; color: var(--text-2); margin: 0 0 8px;
  text-transform: uppercase; letter-spacing: .4px; }
.parts { display: flex; flex-direction: column; gap: 8px; margin-bottom: 18px; }
.part { border: 1px solid var(--line-soft); border-radius: var(--r-s); padding: 9px 11px;
  background: var(--bg-2); }
.part-label { font-family: var(--mono); font-size: 9px; letter-spacing: .5px; text-transform: uppercase;
  color: var(--accent); }
.part-text { margin: 4px 0 0; font-size: 12.5px; color: var(--text-2); line-height: 1.5; white-space: pre-wrap; }

.raw-row { display: flex; justify-content: space-between; align-items: center; margin-top: 14px; }
.raw { margin: 8px 0 0; padding: 12px; background: var(--bg-2); border: 1px solid var(--line-soft);
  border-radius: var(--r-s); font-family: var(--mono); font-size: 11.5px; color: var(--text-2);
  white-space: pre-wrap; overflow-x: auto; line-height: 1.55; max-height: 340px; overflow-y: auto; }
.raw.script { color: var(--text); }

.f { display: flex; flex-direction: column; gap: 5px; padding: 6px 8px; font-size: 11px;
  color: var(--muted); font-family: var(--mono); text-transform: uppercase; letter-spacing: .3px; }
.f input, .f textarea { font-family: var(--display); font-size: 13px; text-transform: none; letter-spacing: 0;
  color: var(--text); background: var(--panel); border: 1px solid var(--line); border-radius: var(--r-s);
  padding: 7px 9px; }
.f input:focus, .f textarea:focus { outline: none; border-color: var(--accent-line-2); }
.f2 { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; }
.primary { width: calc(100% - 16px); margin: 8px; padding: 9px; border: 0; border-radius: var(--r-s);
  background: var(--accent-grad); color: #fff; font: inherit; font-weight: 600; cursor: pointer; }
.primary:disabled { opacity: .6; cursor: default; }
.hint { color: var(--muted); font-size: 11px; padding: 0 10px 8px; line-height: 1.5; }
.mini { border: 1px solid var(--line); background: var(--panel); color: var(--text-2); font: inherit;
  font-size: 11px; padding: 3px 8px; border-radius: var(--r-s); cursor: pointer; }
.mini:hover { border-color: var(--line-2); }

.placeholder { border: 1px dashed var(--line-2); border-radius: var(--r); padding: 40px; text-align: center; }
.placeholder h2 { margin: 0 0 8px; font-size: 18px; }
.placeholder p { margin: 0 auto; max-width: 440px; color: var(--muted); font-size: 13px; line-height: 1.6; }

@media (max-width: 860px) { .split { grid-template-columns: 1fr; } }
</style>
