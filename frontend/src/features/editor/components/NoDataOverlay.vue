<script setup>
import { useRouter } from 'vue-router'
defineOptions({ name: 'NoDataOverlay' })
defineProps({ visible: Boolean })
const router = useRouter()
// V2 sent this back to /pipeline; Production is the equivalent view here.
function goBack() { router.push('/production') }
</script>

<template>
  <div v-if="visible" id="no-data-overlay" class="no-data-overlay" style="display:flex">
    <div class="no-data-content" id="no-data-empty" style="display:none">
      <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="opacity:0.4">
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
        <polyline points="7 10 12 15 17 10" />
        <line x1="12" y1="15" x2="12" y2="3" />
      </svg>
      <h2>No Assets Available</h2>
      <p>Import a project from the Asset Manager to get started.</p>
      <button class="no-data-back-btn" @click="goBack">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
          <path d="M19 12H5" /><path d="M12 19l-7-7 7-7" />
        </svg>
        Back to Studio
      </button>
    </div>
    <div style="max-width:440px;width:100%;padding:0 20px">
      <div id="no-data-asset-list"
          style="max-height:70vh;background:var(--bg-darker, #1a1a2e);border:1px solid var(--border, #2a2a3e);border-radius:12px;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 20px 60px rgba(0,0,0,0.5)">
        <div style="padding:16px 20px;border-bottom:1px solid var(--border, #2a2a3e)">
          <h3 style="margin:0;font-size:14px;font-weight:600;color:var(--text, #e0e0e0)">Projects</h3>
          <p style="margin:2px 0 0;font-size:11px;color:var(--text-muted, #666)">Select a project to load into the editor</p>
        </div>
        <div id="no-data-asset-items" style="flex:1;overflow-y:auto;padding:8px">
          <p style="text-align:center;color:var(--text-muted,#666);font-size:12px;padding:24px 0">Loading...</p>
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
</style>
