<script setup>
import { ref, computed } from 'vue'
import { api } from '@/shared/api/client.js'
import { useToast } from '@/shared/composables/useToast.js'
import { formatBytes, fmtDuration } from '@/shared/utils/format.js'
import { aspectRatioFromDimensions } from '../composables/useExportLibrary.js'

defineOptions({ name: 'LibraryAnalytics' })

const props = defineProps({
  items: { type: Array, default: () => [] },
})

const toast = useToast()
const open = ref(false)
const activeTab = ref('overview') // overview | styles | pipeline | prompts
const promptProject = ref(null) // { project_id, scenes, style }
const promptLoading = ref(false)

function styleLabel(id) {
  if (!id) return 'Unknown'
  return id.replace(/[_-]/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

// ── Overview stats ──
const overview = computed(() => {
  const all = props.items
  if (!all.length) return null
  const now = Date.now()
  const DAY = 86400000

  const durations = all.map(i => i.duration || 0).filter(d => d > 0)
  const sizes = all.map(i => i.size_bytes || 0).filter(s => s > 0)
  const timings = all.map(i => i.pipeline_timing?.total || 0).filter(t => t > 0)

  const avgDur = durations.length ? durations.reduce((a, b) => a + b, 0) / durations.length : 0
  const shortest = durations.length ? Math.min(...durations) : 0
  const longest = durations.length ? Math.max(...durations) : 0
  const avgSize = sizes.length ? sizes.reduce((a, b) => a + b, 0) / sizes.length : 0
  const fastest = timings.length ? Math.min(...timings) : 0
  const avgPipeline = timings.length ? timings.reduce((a, b) => a + b, 0) / timings.length : 0
  const totalContentDuration = durations.reduce((a, b) => a + b, 0)
  const totalSize = sizes.reduce((a, b) => a + b, 0)

  // Rate: exports per day over last 7 days
  const weekItems = all.filter(i => i.modified_at && (now - new Date(i.modified_at).getTime()) < 7 * DAY)
  const dailyRate = weekItems.length > 0 ? (weekItems.length / 7).toFixed(1) : '0'

  // Scene stats
  const sceneCounts = all.map(i => i.scene_count || 0).filter(s => s > 0)
  const avgScenes = sceneCounts.length ? (sceneCounts.reduce((a, b) => a + b, 0) / sceneCounts.length).toFixed(1) : '0'

  // Today's count
  const todayStart = new Date(); todayStart.setHours(0,0,0,0)
  const todayItems = all.filter(i => i.modified_at && new Date(i.modified_at).getTime() >= todayStart.getTime())

  return { avgDur, shortest, longest, avgSize, fastest, avgPipeline, dailyRate, avgScenes, total: all.length, totalContentDuration, totalSize, todayCount: todayItems.length }
})

// ── Daily production chart (last 14 days) ──
const dailyChart = computed(() => {
  const DAY = 86400000
  const now = new Date(); now.setHours(23,59,59,999)
  const days = 14
  const buckets = Array.from({ length: days }, (_, i) => {
    const d = new Date(now.getTime() - (days - 1 - i) * DAY)
    d.setHours(0,0,0,0)
    return { date: d, count: 0, label: d.toLocaleDateString('en', { weekday: 'short' }), dayNum: d.getDate() }
  })
  for (const item of props.items) {
    const t = item.modified_at ? new Date(item.modified_at).getTime() : 0
    if (!t) continue
    for (const b of buckets) {
      if (t >= b.date.getTime() && t < b.date.getTime() + DAY) { b.count++; break }
    }
  }
  const max = Math.max(...buckets.map(b => b.count), 1)
  return { buckets, max }
})

// ── Hourly activity heatmap ──
const hourlyHeatmap = computed(() => {
  const hours = Array.from({ length: 24 }, (_, i) => ({ hour: i, count: 0 }))
  for (const item of props.items) {
    if (!item.modified_at) continue
    const h = new Date(item.modified_at).getHours()
    hours[h].count++
  }
  const max = Math.max(...hours.map(h => h.count), 1)
  return { hours, max }
})

// ── Production streak ──
const productionStreak = computed(() => {
  const DAY = 86400000
  const daySet = new Set()
  for (const item of props.items) {
    if (!item.modified_at) continue
    const d = new Date(item.modified_at)
    daySet.add(`${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`)
  }
  let streak = 0
  const now = new Date()
  for (let i = 0; i < 365; i++) {
    const d = new Date(now.getTime() - i * DAY)
    const key = `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`
    if (daySet.has(key)) streak++
    else if (i > 0) break // allow today to be 0 if it's early
  }
  return streak
})

// ── Style distribution ──
const styleDistribution = computed(() => {
  const counts = {}
  const durations = {}
  for (const item of props.items) {
    const s = item.style || 'unknown'
    counts[s] = (counts[s] || 0) + 1
    durations[s] = (durations[s] || 0) + (item.duration || 0)
  }
  const total = props.items.length || 1
  return Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .map(([style, count]) => ({
      style,
      label: styleLabel(style),
      count,
      pct: ((count / total) * 100).toFixed(0),
      totalDuration: durations[style] || 0,
    }))
})

// ── Pipeline step breakdown ──
const pipelineBreakdown = computed(() => {
  const steps = ['tts', 'timing', 'segment', 'scenes', 'assets', 'assemble', 'export']
  const stepLabels = { tts: 'TTS', timing: 'Alignment', segment: 'Segment', scenes: 'Scenes', assets: 'Assets', assemble: 'Build', export: 'Export' }
  const stepColors = { tts: '#4ECDC4', timing: '#56CCF2', segment: '#A78BFA', scenes: '#FFB347', assets: '#FF6B6B', assemble: '#26DE81', export: '#C084FC' }

  const sums = {}
  const counts = {}
  for (const step of steps) { sums[step] = 0; counts[step] = 0 }

  for (const item of props.items) {
    const t = item.pipeline_timing
    if (!t) continue
    for (const step of steps) {
      if (t[step] > 0) { sums[step] += t[step]; counts[step]++ }
    }
  }

  const maxAvg = Math.max(...steps.map(s => counts[s] ? sums[s] / counts[s] : 0), 1)
  return steps.map(step => {
    const avg = counts[step] ? sums[step] / counts[step] : 0
    return { step, label: stepLabels[step], color: stepColors[step], avg, pct: (avg / maxAvg) * 100, count: counts[step] }
  })
})

// ── Ratio distribution ──
const ratioDistribution = computed(() => {
  const counts = {}
  for (const item of props.items) {
    const r = aspectRatioFromDimensions(item.video_ratio || item.ratio) || 'Other'
    counts[r] = (counts[r] || 0) + 1
  }
  return Object.entries(counts).sort((a, b) => b[1] - a[1])
})

// ── Prompt inspection ──
async function loadPrompts(projectId) {
  if (promptProject.value?.project_id === projectId) { promptProject.value = null; return }
  promptLoading.value = true
  try {
    const data = await api.get(`/api/export/library/prompts/${projectId}`)
    promptProject.value = data
  } catch {
    toast.error('Failed to load prompts')
  } finally {
    promptLoading.value = false
  }
}

function copyText(text) {
  navigator.clipboard.writeText(text).then(() => toast.success('Copied')).catch(() => toast.error('Copy failed'))
}

// Recent exports for prompt browsing
const recentExports = computed(() => props.items.slice(0, 20))
</script>

<template>
  <div class="analytics-section">
    <button class="analytics-toggle" @click="open = !open">
      <div class="analytics-toggle-left">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 20V10"/><path d="M12 20V4"/><path d="M6 20v-6"/></svg>
        <span class="analytics-toggle-label">Analytics</span>
      </div>
      <svg class="analytics-chevron" :class="{ open }" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg>
    </button>

    <Transition name="analytics-expand">
      <div v-if="open" class="analytics-body">
        <!-- Tab bar -->
        <div class="a-tabs">
          <button v-for="t in [
            { id: 'overview', label: 'Overview' },
            { id: 'styles', label: 'Styles' },
            { id: 'pipeline', label: 'Pipeline' },
            { id: 'prompts', label: 'Prompts' },
          ]" :key="t.id" class="a-tab" :class="{ active: activeTab === t.id }" @click="activeTab = t.id">{{ t.label }}</button>
        </div>

        <!-- Overview tab -->
        <div v-if="activeTab === 'overview' && overview" class="a-panel">
          <!-- Top-line stats -->
          <div class="a-metrics-grid">
            <div class="a-metric a-metric--hero">
              <span class="a-metric-val" style="color:#4ECDC4;font-size:20px">{{ overview.total }}</span>
              <span class="a-metric-lbl">Total Exports</span>
            </div>
            <div class="a-metric a-metric--hero">
              <span class="a-metric-val" style="color:#26DE81;font-size:20px">{{ overview.todayCount }}</span>
              <span class="a-metric-lbl">Today</span>
            </div>
            <div class="a-metric a-metric--hero">
              <span class="a-metric-val" style="color:#FFB347;font-size:20px">{{ productionStreak }}d</span>
              <span class="a-metric-lbl">Streak</span>
            </div>
            <div class="a-metric a-metric--hero">
              <span class="a-metric-val" style="color:#A78BFA;font-size:20px">{{ fmtDuration(overview.totalContentDuration) }}</span>
              <span class="a-metric-lbl">Total Content</span>
            </div>
          </div>

          <!-- Daily production bar chart -->
          <div class="a-chart-section">
            <span class="a-section-label">Daily Production (14 days)</span>
            <div class="a-bar-chart">
              <div v-for="(b, i) in dailyChart.buckets" :key="i" class="a-bar-col" :title="`${b.dayNum}: ${b.count} exports`">
                <div class="a-bar-fill-wrap">
                  <div class="a-bar-fill" :style="{ height: (b.count / dailyChart.max * 100) + '%' }">
                    <span v-if="b.count > 0" class="a-bar-val">{{ b.count }}</span>
                  </div>
                </div>
                <span class="a-bar-label" :class="{ 'a-bar-label--today': i === dailyChart.buckets.length - 1 }">{{ b.dayNum }}</span>
              </div>
            </div>
          </div>

          <!-- Hourly heatmap -->
          <div class="a-chart-section">
            <span class="a-section-label">Activity by Hour</span>
            <div class="a-heatmap">
              <div v-for="h in hourlyHeatmap.hours" :key="h.hour" class="a-heat-cell"
                :style="{ opacity: h.count ? Math.max(0.15, h.count / hourlyHeatmap.max) : 0.04 }"
                :title="`${h.hour}:00 — ${h.count} exports`">
                <span v-if="h.hour % 6 === 0" class="a-heat-label">{{ h.hour }}</span>
              </div>
            </div>
          </div>

          <!-- Detail metrics -->
          <div class="a-metrics-grid a-metrics-grid--compact">
            <div class="a-metric">
              <span class="a-metric-val" style="color:#4ECDC4">{{ overview.dailyRate }}</span>
              <span class="a-metric-lbl">Exports / Day</span>
            </div>
            <div class="a-metric">
              <span class="a-metric-val" style="color:#A78BFA">{{ fmtDuration(overview.avgDur) }}</span>
              <span class="a-metric-lbl">Avg Duration</span>
            </div>
            <div class="a-metric">
              <span class="a-metric-val" style="color:#56CCF2">{{ formatBytes(overview.totalSize) }}</span>
              <span class="a-metric-lbl">Total Size</span>
            </div>
            <div class="a-metric">
              <span class="a-metric-val" style="color:#4ECDC4">{{ overview.avgScenes }}</span>
              <span class="a-metric-lbl">Avg Scenes</span>
            </div>
            <div class="a-metric">
              <span class="a-metric-val" style="color:#FF6B6B">{{ fmtDuration(overview.fastest) }}</span>
              <span class="a-metric-lbl">Fastest Export</span>
            </div>
            <div class="a-metric">
              <span class="a-metric-val" style="color:#C084FC">{{ fmtDuration(overview.avgPipeline) }}</span>
              <span class="a-metric-lbl">Avg Pipeline</span>
            </div>
            <div class="a-metric">
              <span class="a-metric-val" style="color:#26DE81">{{ fmtDuration(overview.shortest) }}</span>
              <span class="a-metric-lbl">Shortest</span>
            </div>
            <div class="a-metric">
              <span class="a-metric-val" style="color:#FFB347">{{ fmtDuration(overview.longest) }}</span>
              <span class="a-metric-lbl">Longest</span>
            </div>
          </div>
        </div>

        <!-- Styles tab -->
        <div v-if="activeTab === 'styles'" class="a-panel">
          <div class="a-style-list">
            <div v-for="s in styleDistribution" :key="s.style" class="a-style-row">
              <div class="a-style-info">
                <span class="a-style-name">{{ s.label }}</span>
                <span class="a-style-count">{{ s.count }}x</span>
              </div>
              <div class="a-style-bar-track">
                <div class="a-style-bar" :style="{ width: s.pct + '%', background: 'var(--accent)' }"></div>
              </div>
              <div class="a-style-meta">
                <span>{{ s.pct }}%</span>
                <span class="a-style-dur">{{ fmtDuration(s.totalDuration) }}</span>
              </div>
            </div>
          </div>
          <div v-if="ratioDistribution.length" class="a-ratio-chips">
            <span class="a-section-label">Ratios</span>
            <div class="a-chip-row">
              <span v-for="[ratio, count] in ratioDistribution" :key="ratio" class="a-chip">{{ ratio }} <b>{{ count }}</b></span>
            </div>
          </div>
        </div>

        <!-- Pipeline tab -->
        <div v-if="activeTab === 'pipeline'" class="a-panel">
          <div class="a-pipeline-list">
            <div v-for="s in pipelineBreakdown" :key="s.step" class="a-pipe-row">
              <span class="a-pipe-label" :style="{ color: s.color }">{{ s.label }}</span>
              <div class="a-pipe-bar-track">
                <div class="a-pipe-bar" :style="{ width: s.pct + '%', background: s.color }"></div>
              </div>
              <span class="a-pipe-val">{{ s.avg >= 1 ? fmtDuration(s.avg) : '—' }}</span>
            </div>
          </div>
          <p class="a-pipe-note">Average across {{ items.length }} exports. Bottleneck: the longest bar.</p>
        </div>

        <!-- Prompts tab -->
        <div v-if="activeTab === 'prompts'" class="a-panel">
          <p class="a-prompt-hint">Select a project to inspect its prompts and scene structure.</p>
          <div class="a-prompt-projects">
            <button v-for="item in recentExports" :key="item.project_id" class="a-prompt-btn"
              :class="{ active: promptProject?.project_id === item.project_id }"
              @click="loadPrompts(item.project_id)">
              <span class="a-prompt-btn-id">{{ item.project_id }}</span>
              <span class="a-prompt-btn-style">{{ styleLabel(item.style) }}</span>
            </button>
          </div>

          <div v-if="promptLoading" class="a-prompt-loading">Loading prompts...</div>

          <div v-if="promptProject && !promptLoading" class="a-prompt-detail">
            <div class="a-prompt-header">
              <span class="a-prompt-pid">{{ promptProject.project_id }}</span>
              <span class="a-prompt-style" :style="promptProject.style_color ? { color: promptProject.style_color } : {}">{{ promptProject.style_name || styleLabel(promptProject.style) }}</span>
              <span class="a-prompt-count">{{ promptProject.scenes.length }} scenes</span>
            </div>

            <!-- Style template info -->
            <div v-if="promptProject.style_description || promptProject.style_prompt" class="a-style-block">
              <div v-if="promptProject.style_description" class="a-prompt-block">
                <div class="a-prompt-block-head">
                  <span class="a-prompt-block-label">Style Description</span>
                </div>
                <p class="a-prompt-text">{{ promptProject.style_description }}</p>
              </div>
              <div v-if="promptProject.style_prompt" class="a-prompt-block a-prompt-block--style">
                <div class="a-prompt-block-head">
                  <span class="a-prompt-block-label">Style Prompt (Template)</span>
                  <button class="a-copy-btn" @click="copyText(promptProject.style_prompt)" title="Copy">
                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
                  </button>
                </div>
                <p class="a-prompt-text a-prompt-text--mono">{{ promptProject.style_prompt }}</p>
              </div>
            </div>

            <div v-for="scene in promptProject.scenes" :key="scene.index" class="a-scene-card">
              <div class="a-scene-head">
                <span class="a-scene-num">Scene {{ scene.index }}</span>
                <span v-if="scene.narrative_role" class="a-scene-role">{{ scene.narrative_role }}</span>
                <span v-if="scene.duration" class="a-scene-dur">{{ scene.duration.toFixed(1) }}s</span>
              </div>

              <!-- Script -->
              <div v-if="scene.script" class="a-prompt-block">
                <div class="a-prompt-block-head">
                  <span class="a-prompt-block-label">Script</span>
                  <button class="a-copy-btn" @click="copyText(scene.script)" title="Copy">
                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
                  </button>
                </div>
                <p class="a-prompt-text">{{ scene.script }}</p>
              </div>

              <!-- Image Prompt -->
              <div v-if="scene.image_prompt" class="a-prompt-block a-prompt-block--image">
                <div class="a-prompt-block-head">
                  <span class="a-prompt-block-label">Image Prompt</span>
                  <button class="a-copy-btn" @click="copyText(scene.image_prompt)" title="Copy">
                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
                  </button>
                </div>
                <p class="a-prompt-text a-prompt-text--mono">{{ scene.image_prompt }}</p>
              </div>

              <!-- Storyboard Prompt -->
              <div v-if="scene.storyboard_prompt" class="a-prompt-block a-prompt-block--storyboard">
                <div class="a-prompt-block-head">
                  <span class="a-prompt-block-label">Storyboard Prompt</span>
                  <button class="a-copy-btn" @click="copyText(scene.storyboard_prompt)" title="Copy">
                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
                  </button>
                </div>
                <p class="a-prompt-text a-prompt-text--mono">{{ scene.storyboard_prompt }}</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.analytics-section {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  margin-bottom: 12px;
  overflow: hidden;
}

.analytics-toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 12px 16px;
  background: none;
  border: none;
  color: var(--text);
  cursor: pointer;
  transition: background 0.15s;
}
.analytics-toggle:hover { background: rgba(255,255,255,0.02); }

.analytics-toggle-left {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--accent);
}
.analytics-toggle-label {
  font-size: 12px;
  font-weight: 700;
  font-family: var(--font-mono);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--text);
}
.analytics-chevron {
  color: var(--text-muted);
  transition: transform 0.2s;
}
.analytics-chevron.open { transform: rotate(180deg); }

/* Expand transition */
.analytics-expand-enter-active { animation: a-slide-in 0.2s ease-out; }
.analytics-expand-leave-active { animation: a-slide-out 0.15s ease-in forwards; }
@keyframes a-slide-in { from { opacity: 0; max-height: 0; } to { opacity: 1; max-height: 1200px; } }
@keyframes a-slide-out { from { opacity: 1; max-height: 1200px; } to { opacity: 0; max-height: 0; } }

.analytics-body {
  padding: 0 16px 16px;
}

/* Tabs */
.a-tabs {
  display: flex;
  gap: 2px;
  margin-bottom: 14px;
  padding: 2px;
  background: var(--bg-darkest);
  border-radius: 8px;
  border: 1px solid var(--border);
}
.a-tab {
  flex: 1;
  padding: 6px 10px;
  font-size: 10px;
  font-weight: 600;
  font-family: var(--font-mono);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-muted);
  background: none;
  border: 1px solid transparent;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s;
}
.a-tab:hover { color: var(--text); }
.a-tab.active {
  color: var(--accent);
  background: rgba(78, 205, 196, 0.08);
  border-color: rgba(78, 205, 196, 0.2);
}

/* Metrics grid */
.a-metrics-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
  margin-bottom: 16px;
}
.a-metrics-grid--compact { margin-bottom: 0; }
.a-metric {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  padding: 10px 6px;
  background: var(--bg-darkest);
  border: 1px solid var(--border);
  border-radius: 8px;
}
.a-metric--hero {
  padding: 14px 6px;
  background: linear-gradient(135deg, rgba(78,205,196,0.04), transparent);
  border-color: rgba(78,205,196,0.1);
}
.a-metric-val {
  font-family: var(--font-mono);
  font-size: 14px;
  font-weight: 700;
  line-height: 1;
}
.a-metric-lbl {
  font-family: var(--font-mono);
  font-size: 8px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  text-align: center;
}

/* Chart sections */
.a-chart-section {
  margin-bottom: 16px;
}
.a-chart-section .a-section-label {
  margin-bottom: 8px;
}

/* Daily bar chart */
.a-bar-chart {
  display: flex;
  align-items: flex-end;
  gap: 3px;
  height: 80px;
  padding: 4px 0;
}
.a-bar-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  height: 100%;
}
.a-bar-fill-wrap {
  flex: 1;
  width: 100%;
  display: flex;
  align-items: flex-end;
  justify-content: center;
}
.a-bar-fill {
  width: 100%;
  min-height: 2px;
  background: var(--accent);
  border-radius: 3px 3px 0 0;
  transition: height 0.4s ease;
  position: relative;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  opacity: 0.75;
}
.a-bar-fill:hover { opacity: 1; }
.a-bar-val {
  font-family: var(--font-mono);
  font-size: 8px;
  font-weight: 700;
  color: var(--accent);
  position: absolute;
  top: -12px;
  white-space: nowrap;
}
.a-bar-label {
  font-family: var(--font-mono);
  font-size: 8px;
  color: var(--text-muted);
  margin-top: 4px;
  opacity: 0.6;
}
.a-bar-label--today {
  color: var(--accent);
  opacity: 1;
  font-weight: 700;
}

/* Hourly heatmap */
.a-heatmap {
  display: flex;
  gap: 2px;
  height: 24px;
}
.a-heat-cell {
  flex: 1;
  background: var(--accent);
  border-radius: 3px;
  position: relative;
  transition: opacity 0.2s;
  cursor: default;
}
.a-heat-cell:hover { filter: brightness(1.3); }
.a-heat-label {
  position: absolute;
  bottom: -14px;
  left: 50%;
  transform: translateX(-50%);
  font-family: var(--font-mono);
  font-size: 7px;
  color: var(--text-muted);
  white-space: nowrap;
}

/* Style distribution */
.a-style-list { display: flex; flex-direction: column; gap: 8px; }
.a-style-row { display: flex; align-items: center; gap: 10px; }
.a-style-info { min-width: 120px; display: flex; align-items: center; gap: 6px; }
.a-style-name { font-size: 11px; font-weight: 600; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100px; }
.a-style-count { font-family: var(--font-mono); font-size: 10px; color: var(--text-muted); }
.a-style-bar-track { flex: 1; height: 6px; background: var(--bg-darkest); border-radius: 3px; overflow: hidden; }
.a-style-bar { height: 100%; border-radius: 3px; transition: width 0.3s ease; }
.a-style-meta { display: flex; gap: 8px; min-width: 80px; justify-content: flex-end; }
.a-style-meta span { font-family: var(--font-mono); font-size: 10px; color: var(--text-muted); }
.a-style-dur { color: var(--accent) !important; }

.a-ratio-chips { margin-top: 16px; }
.a-section-label { font-family: var(--font-mono); font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: var(--text-muted); margin-bottom: 6px; display: block; }
.a-chip-row { display: flex; flex-wrap: wrap; gap: 6px; }
.a-chip {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-secondary);
  background: var(--bg-darkest);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 3px 8px;
}
.a-chip b { color: var(--accent); margin-left: 4px; }

/* Pipeline breakdown */
.a-pipeline-list { display: flex; flex-direction: column; gap: 8px; }
.a-pipe-row { display: flex; align-items: center; gap: 10px; }
.a-pipe-label { font-family: var(--font-mono); font-size: 10px; font-weight: 700; min-width: 70px; text-transform: uppercase; letter-spacing: 0.04em; }
.a-pipe-bar-track { flex: 1; height: 8px; background: var(--bg-darkest); border-radius: 4px; overflow: hidden; }
.a-pipe-bar { height: 100%; border-radius: 4px; transition: width 0.4s ease; opacity: 0.8; }
.a-pipe-val { font-family: var(--font-mono); font-size: 10px; color: var(--text-muted); min-width: 50px; text-align: right; }
.a-pipe-note { font-size: 10px; color: var(--text-muted); margin-top: 10px; font-style: italic; }

/* Prompts tab */
.a-prompt-hint { font-size: 11px; color: var(--text-muted); margin: 0 0 10px; }
.a-prompt-projects { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 12px; max-height: 120px; overflow-y: auto; }
.a-prompt-btn {
  display: flex; flex-direction: column; gap: 1px; padding: 5px 10px; font-size: 10px;
  background: var(--bg-darkest); border: 1px solid var(--border); border-radius: 6px;
  color: var(--text-muted); cursor: pointer; transition: all 0.15s; text-align: left;
}
.a-prompt-btn:hover { border-color: var(--accent); color: var(--text); }
.a-prompt-btn.active { border-color: var(--accent); background: rgba(78,205,196,0.06); color: var(--accent); }
.a-prompt-btn-id { font-family: var(--font-mono); font-weight: 700; font-size: 9px; }
.a-prompt-btn-style { font-size: 9px; opacity: 0.7; }
.a-prompt-loading { font-size: 11px; color: var(--text-muted); font-family: var(--font-mono); padding: 12px 0; }

.a-prompt-detail { margin-top: 8px; }
.a-prompt-header {
  display: flex; align-items: center; gap: 10px; padding: 8px 12px;
  background: var(--bg-darkest); border: 1px solid var(--border); border-radius: 8px; margin-bottom: 10px;
}
.a-prompt-pid { font-family: var(--font-mono); font-size: 11px; font-weight: 700; color: var(--accent); }
.a-prompt-style { font-size: 10px; color: var(--text-secondary); }
.a-prompt-count { font-family: var(--font-mono); font-size: 10px; color: var(--text-muted); margin-left: auto; }

.a-scene-card {
  background: var(--bg-darkest); border: 1px solid var(--border); border-radius: 8px;
  padding: 10px 12px; margin-bottom: 6px;
}
.a-scene-head {
  display: flex; align-items: center; gap: 8px; margin-bottom: 6px;
}
.a-scene-num { font-family: var(--font-mono); font-size: 10px; font-weight: 700; color: var(--accent); }
.a-scene-role { font-size: 9px; color: var(--text-muted); background: rgba(167,139,250,0.1); border: 1px solid rgba(167,139,250,0.2); border-radius: 4px; padding: 1px 6px; }
.a-scene-dur { font-family: var(--font-mono); font-size: 9px; color: var(--text-muted); margin-left: auto; }

.a-style-block {
  background: var(--bg-darkest); border: 1px solid var(--border); border-radius: 8px;
  padding: 10px 12px; margin-bottom: 10px;
}
.a-prompt-block { margin-top: 6px; }
.a-prompt-block--style { border-left: 2px solid rgba(255,179,71,0.3); padding-left: 8px; margin-top: 10px; }
.a-prompt-block--image { border-left: 2px solid rgba(78,205,196,0.3); padding-left: 8px; }
.a-prompt-block--storyboard { border-left: 2px solid rgba(167,139,250,0.3); padding-left: 8px; }
.a-prompt-block-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 3px; }
.a-prompt-block-label { font-family: var(--font-mono); font-size: 8px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-muted); }
.a-copy-btn {
  display: flex; align-items: center; padding: 2px 4px; background: none; border: 1px solid var(--border);
  border-radius: 3px; color: var(--text-muted); cursor: pointer; transition: all 0.15s;
}
.a-copy-btn:hover { color: var(--accent); border-color: var(--accent); }
.a-prompt-text { font-size: 11px; color: var(--text-secondary); line-height: 1.5; margin: 0; word-break: break-word; }
.a-prompt-text--mono { font-family: var(--font-mono); font-size: 10px; }

@media (max-width: 700px) {
  .a-metrics-grid { grid-template-columns: repeat(2, 1fr); }
}
</style>
