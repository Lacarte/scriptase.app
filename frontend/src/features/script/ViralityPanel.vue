<script setup>
import { computed } from 'vue'

const props = defineProps({
  score: { type: Object, default: null },
  // The LLM judge's second opinion (same shape as `score`), or null; `llmError`
  // explains a missing one.
  llmScore: { type: Object, default: null },
  llmError: { type: String, default: '' },
  analyzing: { type: Boolean, default: false },
  stale: { type: Boolean, default: false },
})

defineEmits(['analyze'])

const labels = {
  hook: 'Hook',
  opening_line: 'Opening line',
  pacing: 'Pacing',
  open_loops: 'Open loops',
  cta: 'Call to action',
  balance: 'Section balance',
}

function humanize(value) {
  const text = String(value || '').replace(/_/g, ' ').trim()
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : ''
}

function percent(value) {
  return Math.round(Math.min(1, Math.max(0, Number(value) || 0)) * 100)
}

function color(value) {
  if (value >= 70) return 'var(--ok)'
  if (value >= 45) return 'var(--run)'
  if (value >= 25) return 'var(--warn)'
  return 'var(--fail)'
}

function reasons(items) {
  const seen = new Set()
  return (Array.isArray(items) ? items : []).flatMap(reason => {
    if (!reason?.code || seen.has(reason.code)) return []
    seen.add(reason.code)
    return [{
      code: reason.code,
      label: humanize(reason.code),
      positive: reason.impact === 'positive',
    }]
  })
}

const dimensions = computed(() => (Array.isArray(props.score?.dimensions) ? props.score.dimensions : [])
  .filter(item => item?.id)
  .map(item => ({
    id: item.id,
    label: labels[item.id] || humanize(item.id),
    percent: percent(item.score),
    reasons: reasons(item.reasons),
  })))

function dasharray(value, radius) {
  const circumference = 2 * Math.PI * radius
  const v = Math.min(100, Math.max(0, Number(value) || 0))
  return `${circumference * (v / 100)} ${circumference}`
}

const gauge = computed(() => dasharray(props.score?.score, 23))
const llmGauge = computed(() => dasharray(props.llmScore?.score, 23))
const llmSummary = computed(() => String(props.llmScore?.metrics?.summary || '').trim())
</script>

<template>
  <section class="s1-vir" :class="{ analyzing }" aria-label="Script virality score" data-testid="virality-panel">
    <div v-if="analyzing" class="s1-vir-scan" role="status">
      <span class="sp" aria-hidden="true" /> Analyzing hook, pacing, loops &amp; CTA…
    </div>

    <template v-else-if="score">
      <div class="s1-vir-head">
        <div class="s1-vir-gauges">
          <div class="s1-vir-gauge" :data-band="score.band">
            <div class="s1-vir-ring">
              <svg viewBox="0 0 54 54" width="54" height="54" aria-hidden="true">
                <circle cx="27" cy="27" r="23" fill="none" stroke="var(--raise)" stroke-width="4" />
                <circle cx="27" cy="27" r="23" fill="none" stroke="currentColor" stroke-width="4" stroke-linecap="round" :stroke-dasharray="gauge" />
              </svg>
              <div class="score">{{ score.score }}</div>
            </div>
            <span class="s1-vir-gtag">Structural</span>
          </div>

          <!-- The LLM judge's second opinion, when present. Same size as the
               structural gauge — the two are peers, not primary/secondary. -->
          <div v-if="llmScore" class="s1-vir-gauge" :data-band="llmScore.band">
            <div class="s1-vir-ring">
              <svg viewBox="0 0 54 54" width="54" height="54" aria-hidden="true">
                <circle cx="27" cy="27" r="23" fill="none" stroke="var(--raise)" stroke-width="4" />
                <circle cx="27" cy="27" r="23" fill="none" stroke="currentColor" stroke-width="4" stroke-linecap="round" :stroke-dasharray="llmGauge" />
              </svg>
              <div class="score">{{ llmScore.score }}</div>
            </div>
            <span class="s1-vir-gtag">LLM judge</span>
          </div>
          <div v-else-if="llmError" class="s1-vir-gauge na" title="LLM judge unavailable">
            <div class="s1-vir-ring">
              <svg viewBox="0 0 54 54" width="54" height="54" aria-hidden="true">
                <circle cx="27" cy="27" r="23" fill="none" stroke="var(--raise)" stroke-width="4" />
              </svg>
              <div class="score">—</div>
            </div>
            <span class="s1-vir-gtag">LLM judge</span>
          </div>
        </div>

        <div class="vt">
          <div class="tt">Virality score <span class="grade" :class="`grade-${score.band}`">{{ score.band }}</span></div>
          <div class="sub">{{ stale ? 'Text changed since this score was run.' : 'Advisory only — this channel sets no virality threshold.' }}</div>
          <div v-if="llmSummary" class="s1-vir-llm-note">“{{ llmSummary }}”</div>
          <div v-else-if="llmError" class="s1-vir-llm-miss">LLM second opinion unavailable — {{ llmError }}</div>
        </div>
        <button class="btn xs s1-vir-recheck" type="button" @click="$emit('analyze')">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M21 12a9 9 0 1 1-2.6-6.4" /><path d="M21 3v6h-6" /></svg>
          {{ stale ? 'Check current text' : 'Re-check' }}
        </button>
      </div>

      <div class="s1-vir-body" data-testid="virality-dimensions">
        <div v-for="dimension in dimensions" :key="dimension.id" class="s1-vir-dim">
          <div class="top"><span class="nm">{{ dimension.label }}</span><span class="pc" :style="{ color: color(dimension.percent) }">{{ dimension.percent }}%</span></div>
          <div class="s1-vir-bar" role="img" :aria-label="`${dimension.label} scored ${dimension.percent} percent`">
            <div class="fill" :style="{ width: `${dimension.percent}%`, background: color(dimension.percent) }" />
          </div>
          <div v-if="dimension.reasons.length" class="s1-vir-issues">
            <span v-for="reason in dimension.reasons" :key="reason.code" class="s1-vir-chip" :class="reason.positive ? 'good' : 'bad'">
              {{ reason.positive ? '✓ ' : '' }}{{ reason.label }}
            </span>
          </div>
        </div>
      </div>
    </template>

    <div v-else class="s1-vir-empty">
      <div class="big">Virality score not run</div>
      Check how this script is likely to perform — hook, pacing, open loops and CTA.
    </div>
  </section>
</template>

<style scoped>
.s1-vir { margin-top: 16px; border: 1px solid var(--line); border-radius: var(--r); background: linear-gradient(180deg, var(--panel), var(--bg-2)); overflow: hidden; }
.s1-vir-head { display: flex; align-items: flex-start; gap: 16px; padding: 16px 18px; border-bottom: 1px solid var(--line-soft); }
.s1-vir-gauges { display: flex; align-items: flex-start; gap: 16px; flex: none; }
.s1-vir-gauge { flex: none; color: var(--muted); display: flex; flex-direction: column; align-items: center; gap: 5px; }
/* The ring + number share a fixed square; the number is centered INSIDE it. */
.s1-vir-ring { position: relative; width: 54px; height: 54px; }
.s1-vir-gauge[data-band="poor"] { color: var(--fail); }
.s1-vir-gauge[data-band="weak"] { color: var(--warn); }
.s1-vir-gauge[data-band="solid"] { color: var(--run); }
.s1-vir-gauge[data-band="strong"] { color: var(--ok); }
.s1-vir-gauge.na { color: var(--faint); }
.s1-vir-gauge svg { display: block; transform: rotate(-90deg); }
.s1-vir-gauge .score { position: absolute; inset: 0; display: grid; place-items: center; font-family: var(--display); font-weight: 700; font-size: 17px; line-height: 1; letter-spacing: -.5px; color: var(--text); }
.s1-vir-gauge.na .score { color: var(--faint); }
.s1-vir-gtag { font-family: var(--mono); font-size: 8px; letter-spacing: .4px; text-transform: uppercase; color: var(--muted); white-space: nowrap; }
.s1-vir-head .vt { flex: 1; min-width: 0; }
.s1-vir-llm-note { margin-top: 6px; font-size: 11.5px; font-style: italic; color: var(--text-2); line-height: 1.5; }
.s1-vir-llm-miss { margin-top: 6px; font-size: 11px; color: var(--warn); }
.s1-vir-head .vt .tt { font-family: var(--display); font-weight: 600; font-size: 14px; display: flex; align-items: center; gap: 9px; }
.s1-vir-head .vt .grade { font-family: var(--mono); font-size: 10px; letter-spacing: .5px; text-transform: uppercase; padding: 2px 8px; border-radius: 20px; }
.s1-vir-head .vt .sub { font-size: 11.5px; color: var(--muted); margin-top: 3px; }
.s1-vir-recheck { flex: none; }

.grade-poor { color: var(--fail); background: var(--fail-dim); }
.grade-weak { color: var(--warn); background: var(--warn-dim); }
.grade-solid { color: var(--run); background: var(--run-dim); }
.grade-strong { color: var(--ok); background: var(--ok-dim); }

.s1-vir-body { padding: 6px 18px 16px; }
.s1-vir-dim { padding: 11px 0; border-bottom: 1px solid var(--line-soft); }
.s1-vir-dim:last-child { border-bottom: none; }
.s1-vir-dim .top { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.s1-vir-dim .top .nm { font-size: 12.5px; color: var(--text-2); font-weight: 500; }
.s1-vir-dim .top .pc { font-family: var(--mono); font-size: 11.5px; font-weight: 600; }
.s1-vir-bar { height: 5px; border-radius: 3px; background: var(--raise); overflow: hidden; }
.s1-vir-bar .fill { height: 100%; border-radius: 3px; width: 0%; transition: width .6s cubic-bezier(.4, 0, .2, 1); }
.s1-vir-issues { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 9px; }
.s1-vir-chip { font-size: 10.5px; padding: 3px 9px; border-radius: 5px; display: inline-flex; align-items: center; gap: 5px; }
.s1-vir-chip.bad { color: var(--warn); background: var(--warn-dim); box-shadow: inset 0 0 0 1px var(--warn-line); }
.s1-vir-chip.good { color: var(--ok); background: var(--ok-dim); box-shadow: inset 0 0 0 1px var(--ok-line); }
.s1-vir-empty { padding: 26px 18px; text-align: center; color: var(--muted); font-size: 12.5px; line-height: 1.6; }
.s1-vir-empty .big { font-family: var(--display); font-size: 13px; color: var(--text-2); font-weight: 600; margin-bottom: 4px; }
.s1-vir.analyzing .s1-vir-body { opacity: .45; }
.s1-vir-scan { font-family: var(--mono); font-size: 11px; color: var(--run); display: flex; align-items: center; gap: 8px; padding: 20px 18px; }
.s1-vir-scan .sp { width: 12px; height: 12px; border: 2px solid var(--run-dim); border-top-color: var(--run); border-radius: 50%; animation: spin .7s linear infinite; }

@keyframes spin { to { transform: rotate(360deg); } }

@media (prefers-reduced-motion: reduce) {
  .s1-vir-scan .sp { animation: none; }
  .s1-vir-bar .fill { transition: none; }
}

@media (max-width: 560px) {
  .s1-vir-head { align-items: flex-start; flex-wrap: wrap; }
  .s1-vir-recheck { margin-left: 66px; }
}
</style>
