<script setup>
import { computed } from 'vue'

const props = defineProps({
  score: { type: Object, default: null },
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

const gauge = computed(() => {
  const circumference = 2 * Math.PI * 22
  const value = Math.min(100, Math.max(0, Number(props.score?.score) || 0))
  return `${circumference * (value / 100)} ${circumference}`
})
</script>

<template>
  <section class="virality-panel" aria-label="Script virality score" data-testid="virality-panel">
    <div v-if="analyzing" class="virality-scan" role="status">
      <span class="spinner" aria-hidden="true" /> Analyzing hook, pacing, loops &amp; CTA…
    </div>

    <template v-else-if="score">
      <header class="virality-head">
        <div class="gauge" :data-band="score.band">
          <svg width="52" height="52" aria-hidden="true">
            <circle cx="26" cy="26" r="22" fill="none" stroke="var(--raise)" stroke-width="5" />
            <circle cx="26" cy="26" r="22" fill="none" stroke="currentColor" stroke-width="5" stroke-linecap="round" :stroke-dasharray="gauge" />
          </svg>
          <span>{{ score.score }}</span>
        </div>
        <div class="virality-title">
          <div><strong>Virality score</strong> <span class="grade" :class="`grade-${score.band}`">{{ score.band }}</span></div>
          <small>{{ stale ? 'Text changed since this score was run.' : 'Advisory only — it never blocks saving.' }}</small>
        </div>
        <button class="btn xs" type="button" @click="$emit('analyze')">{{ stale ? 'Check current text' : 'Re-check' }}</button>
      </header>

      <div class="dimension-list" data-testid="virality-dimensions">
        <div v-for="dimension in dimensions" :key="dimension.id" class="dimension">
          <div class="dimension-top"><span>{{ dimension.label }}</span><b :style="{ color: color(dimension.percent) }">{{ dimension.percent }}%</b></div>
          <div class="dimension-bar" role="img" :aria-label="`${dimension.label} scored ${dimension.percent} percent`">
            <span :style="{ width: `${dimension.percent}%`, background: color(dimension.percent) }" />
          </div>
          <div v-if="dimension.reasons.length" class="reason-list">
            <span v-for="reason in dimension.reasons" :key="reason.code" :class="reason.positive ? 'good' : 'bad'">
              {{ reason.positive ? '✓ ' : '' }}{{ reason.label }}
            </span>
          </div>
        </div>
      </div>
    </template>

    <div v-else class="virality-empty">
      <strong>Virality score not run</strong>
      <span>Check how this script is likely to perform — hook, pacing, open loops and CTA.</span>
      <button class="btn sm" type="button" @click="$emit('analyze')">Analyze script</button>
    </div>
  </section>
</template>

<style scoped>
.virality-panel { margin-top: 16px; overflow: hidden; border: 1px solid var(--line); border-radius: var(--r); background: linear-gradient(180deg, var(--panel), var(--bg-2)); }
.virality-head { display: flex; align-items: center; gap: 14px; padding: 15px 18px; border-bottom: 1px solid var(--line-soft); }
.gauge { position: relative; width: 52px; height: 52px; flex: none; color: var(--muted); }
.gauge[data-band="poor"] { color: var(--fail); }.gauge[data-band="weak"] { color: var(--warn); }.gauge[data-band="solid"] { color: var(--run); }.gauge[data-band="strong"] { color: var(--ok); }
.gauge svg { transform: rotate(-90deg); }.gauge span { position: absolute; inset: 0; display: grid; place-items: center; font: 600 18px var(--display); }
.virality-title { min-width: 0; flex: 1; }.virality-title > div { display: flex; align-items: center; gap: 9px; font: 14px var(--display); }.virality-title small { display: block; margin-top: 3px; color: var(--muted); font-size: 11.5px; }
.grade { padding: 2px 8px; border-radius: 20px; font: 10px var(--mono); letter-spacing: .5px; text-transform: uppercase; }.grade-poor { color: var(--fail); background: var(--fail-dim); }.grade-weak { color: var(--warn); background: var(--warn-dim); }.grade-solid { color: var(--run); background: var(--run-dim); }.grade-strong { color: var(--ok); background: var(--ok-dim); }
.dimension-list { padding: 6px 18px 16px; }.dimension { padding: 11px 0; border-bottom: 1px solid var(--line-soft); }.dimension:last-child { border-bottom: 0; }.dimension-top { display: flex; justify-content: space-between; margin-bottom: 8px; color: var(--text-2); font-size: 12.5px; }.dimension-top b { font: 600 11.5px var(--mono); }
.dimension-bar { height: 5px; overflow: hidden; border-radius: 3px; background: var(--raise); }.dimension-bar span { display: block; height: 100%; border-radius: 3px; transition: width .6s var(--ease-spring); }
.reason-list { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 9px; }.reason-list span { display: inline-flex; padding: 3px 9px; border-radius: 5px; font-size: 10.5px; }.reason-list .bad { color: var(--warn); background: var(--warn-dim); box-shadow: inset 0 0 0 1px var(--warn-line); }.reason-list .good { color: var(--ok); background: var(--ok-dim); box-shadow: inset 0 0 0 1px var(--ok-line); }
.virality-empty { display: flex; flex-direction: column; align-items: center; padding: 24px 18px; color: var(--muted); text-align: center; font-size: 12.5px; line-height: 1.6; }.virality-empty strong { color: var(--text-2); font: 600 13px var(--display); }.virality-empty .btn { margin-top: 12px; }
.virality-scan { display: flex; align-items: center; gap: 8px; padding: 20px 18px; color: var(--run); font: 11px var(--mono); }.spinner { width: 12px; height: 12px; border: 2px solid var(--run-dim); border-top-color: var(--run); border-radius: 50%; animation: spin .7s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .spinner { animation: none; }.dimension-bar span { transition: none; } }
@media (max-width: 560px) { .virality-head { align-items: flex-start; flex-wrap: wrap; }.virality-head .btn { margin-left: 66px; } }
</style>
