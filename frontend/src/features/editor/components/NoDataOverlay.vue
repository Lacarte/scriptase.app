<script setup>
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'

defineOptions({ name: 'NoDataOverlay' })
const props = defineProps({ visible: Boolean })
const emit = defineEmits(['close'])
const router = useRouter()

const loading = ref(false)
const items = ref([])
const fetchError = ref('')

function goBack() { router.push('/production') }

watch(() => props.visible, (vis) => {
  if (vis) fetchProjects()
})

async function fetchProjects() {
  loading.value = true
  fetchError.value = ''
  items.value = []

  try {
    const [libraryRes, editorRes] = await Promise.all([
      fetch('/api/export/library').then(r => r.ok ? r.json() : []).catch(() => []),
      fetch('/api/editor/projects').then(r => r.ok ? r.json() : []).catch(() => []),
    ])

    const editorMap = {}
    for (const ep of editorRes) {
      if (ep?.project_id) editorMap[ep.project_id] = ep
    }

    // Deduplicate library items by project_id, keeping the most recent
    const libraryByProject = {}
    for (const item of libraryRes) {
      const pid = item?.project_id
      if (!pid) continue
      const existing = libraryByProject[pid]
      if (!existing || (item.modified_at || '') > (existing.modified_at || '')) {
        libraryByProject[pid] = item
      }
    }

    const merged = []
    const seen = new Set()

    // Library items first (completed work)
    for (const [pid, lib] of Object.entries(libraryByProject)) {
      seen.add(pid)
      const editor = editorMap[pid]
      merged.push({
        project_id: pid,
        project_name: lib.project_name || editor?.project_name || pid,
        channel_name: lib.channel_name || '',
        scene_count: lib.scene_count || editor?.scene_count || 0,
        duration: lib.duration || editor?.total_duration || 0,
        preview: lib.preview_url || editor?.preview || '',
        time: lib.completed_at || lib.modified_at || editor?.saved_at || '',
        has_editor: !!editor,
        has_wip: editor?.has_wip || false,
        source: 'library',
        style: lib.style || '',
      })
    }

    // Editor-only projects (saved but never exported)
    for (const ep of editorRes) {
      const pid = ep.project_id
      if (seen.has(pid)) continue
      seen.add(pid)
      merged.push({
        project_id: pid,
        project_name: ep.project_name || pid,
        channel_name: '',
        scene_count: ep.scene_count || 0,
        duration: ep.total_duration || 0,
        preview: ep.preview || '',
        time: ep.saved_at || '',
        has_editor: true,
        has_wip: ep.has_wip || false,
        source: 'editor',
        style: '',
      })
    }

    merged.sort((a, b) => {
      const ta = new Date(a.time || 0).getTime() || 0
      const tb = new Date(b.time || 0).getTime() || 0
      return tb - ta
    })

    items.value = merged
  } catch (e) {
    fetchError.value = e.message || 'Failed to load projects'
  } finally {
    loading.value = false
  }
}

function timeAgo(ts) {
  if (!ts) return ''
  const parsed = new Date(ts).getTime()
  if (!Number.isFinite(parsed)) return ''
  const diff = (Date.now() - parsed) / 1000
  if (diff < 60) return 'just now'
  if (diff < 3600) return Math.floor(diff / 60) + 'm ago'
  if (diff < 86400) return Math.floor(diff / 3600) + 'h ago'
  return Math.floor(diff / 86400) + 'd ago'
}

function formatDuration(secs) {
  if (!secs || secs <= 0) return ''
  const m = Math.floor(secs / 60)
  const s = Math.floor(secs % 60)
  return m > 0 ? `${m}:${String(s).padStart(2, '0')}` : `${s}s`
}

function openProject(project) {
  emit('close')
  if (project.has_editor) {
    window.loadProjectFromServer?.(project.project_id)
  } else {
    window.editorImportAssetProject?.(project.project_id)
  }
}
</script>

<template>
  <div v-if="visible" id="no-data-overlay" class="no-data-overlay" style="display:flex">
    <!-- Empty state: no projects anywhere -->
    <div
      v-if="!loading && !fetchError && items.length === 0"
      class="no-data-content"
      style="display:flex;flex-direction:column;align-items:center;justify-content:center;gap:16px;padding:40px 20px;text-align:center"
    >
      <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="opacity:0.4">
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
        <polyline points="7 10 12 15 17 10" />
        <line x1="12" y1="15" x2="12" y2="3" />
      </svg>
      <h2 style="margin:0;font-size:18px;font-weight:600;color:var(--text,#e0e0e0)">No Projects Yet</h2>
      <p style="margin:0;font-size:13px;color:var(--text-muted,#666);max-width:280px">
        Run a production job to create your first video, then open it here to edit.
      </p>
      <button class="no-data-back-btn" @click="goBack">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
          <path d="M19 12H5" /><path d="M12 19l-7-7 7-7" />
        </svg>
        Back to Production
      </button>
    </div>

    <!-- Project list -->
    <div v-else style="max-width:440px;width:100%;padding:0 20px">
      <div
        class="overlay-project-panel"
        style="max-height:70vh;background:var(--bg-darker,#1a1a2e);border:1px solid var(--border,#2a2a3e);border-radius:12px;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 20px 60px rgba(0,0,0,0.5)"
      >
        <div style="padding:16px 20px;border-bottom:1px solid var(--border,#2a2a3e)">
          <h3 style="margin:0;font-size:14px;font-weight:600;color:var(--text,#e0e0e0)">Recent Projects</h3>
          <p style="margin:2px 0 0;font-size:11px;color:var(--text-muted,#666)">Completed jobs and saved editor projects</p>
        </div>
        <div style="flex:1;overflow-y:auto;padding:8px">
          <!-- Loading state -->
          <p v-if="loading" style="text-align:center;color:var(--text-muted,#666);font-size:12px;padding:24px 0">
            Loading...
          </p>
          <!-- Error state -->
          <p v-else-if="fetchError" style="text-align:center;color:#FF6B6B;font-size:11px;padding:24px 0">
            {{ fetchError }}
          </p>
          <!-- Project items -->
          <template v-else>
            <div
              v-for="p in items"
              :key="p.project_id"
              class="overlay-project-row"
              @click="openProject(p)"
            >
              <div style="display:flex;align-items:center;gap:10px">
                <div v-if="p.preview" class="overlay-thumb">
                  <img :src="p.preview" style="width:100%;height:100%;object-fit:cover" />
                </div>
                <div v-else class="overlay-thumb overlay-thumb-empty">
                  <svg width="18" height="18" fill="none" stroke="var(--text-muted,#666)" stroke-width="1.5" viewBox="0 0 24 24" style="opacity:0.4">
                    <rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/>
                  </svg>
                </div>
                <div style="flex:1;min-width:0">
                  <div style="display:flex;align-items:center;gap:6px;margin-bottom:2px">
                    <span class="overlay-project-name">{{ p.project_name || p.project_id }}</span>
                    <!-- Saved badge -->
                    <svg v-if="p.has_editor" width="12" height="12" fill="none" stroke="var(--accent,#4ECDC4)" stroke-width="2" viewBox="0 0 24 24" style="flex-shrink:0;opacity:0.8" title="Saved editor project">
                      <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/>
                    </svg>
                    <!-- Library/export dot -->
                    <span v-if="p.source === 'library'" style="width:6px;height:6px;border-radius:50%;background:#4ECDC4;flex-shrink:0" title="Exported"></span>
                  </div>
                  <div class="overlay-meta">
                    <span style="color:#4ECDC4">{{ p.scene_count }} scene{{ p.scene_count !== 1 ? 's' : '' }}</span>
                    <template v-if="p.duration > 0">
                      <span style="opacity:0.3">/</span>
                      <span>{{ formatDuration(p.duration) }}</span>
                    </template>
                    <template v-if="p.channel_name">
                      <span style="opacity:0.3">/</span>
                      <span style="color:#A78BFA">{{ p.channel_name }}</span>
                    </template>
                    <span style="opacity:0.3">/</span>
                    <span v-if="p.has_wip" style="color:var(--accent,#4ECDC4);opacity:0.8">edited {{ timeAgo(p.time) }}</span>
                    <span v-else>{{ timeAgo(p.time) }}</span>
                  </div>
                </div>
                <svg width="14" height="14" fill="none" :stroke="p.has_editor ? 'var(--accent,#4ECDC4)' : 'var(--text-muted,#666)'" stroke-width="1.5" viewBox="0 0 24 24" style="flex-shrink:0;opacity:0.4"><path d="M9 18l6-6-6-6"/></svg>
              </div>
            </div>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.no-data-back-btn {
  margin-top: 20px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  background: rgba(78, 205, 196, 0.1);
  border: 1px solid rgba(78, 205, 196, 0.3);
  border-radius: 8px;
  color: var(--accent, #4ECDC4);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}
.no-data-back-btn:hover {
  background: rgba(78, 205, 196, 0.2);
  border-color: var(--accent, #4ECDC4);
}
.overlay-project-row {
  cursor: pointer;
  padding: 10px 14px;
  border-radius: 8px;
  border: 1px solid transparent;
  transition: all 0.15s;
  margin-bottom: 4px;
}
.overlay-project-row:hover {
  background: var(--bg-darkest, #111);
  border-color: var(--border, #2a2a3e);
}
.overlay-thumb {
  width: 40px;
  height: 40px;
  border-radius: 6px;
  overflow: hidden;
  flex-shrink: 0;
  border: 1px solid var(--border, #2a2a3e);
}
.overlay-thumb-empty {
  background: var(--bg-darkest, #111);
  display: flex;
  align-items: center;
  justify-content: center;
}
.overlay-project-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--text, #e0e0e0);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.overlay-meta {
  display: flex;
  gap: 6px;
  align-items: center;
  font-size: 10px;
  font-family: 'JetBrains Mono', monospace;
  color: var(--text-muted, #666);
  flex-wrap: wrap;
}
</style>
