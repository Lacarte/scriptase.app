<script setup>
defineOptions({ name: 'ExportProgressModal' })
defineProps({ visible: Boolean })
const emit = defineEmits(['close'])
</script>

<template>
  <div v-if="visible" id="export-progress-modal" class="modal active">
    <div class="modal-content">
      <!-- Step 1: Profile Selector -->
      <div id="export-step-profile">
        <div class="modal-header">
          <h3>Export Video</h3>
          <button class="modal-close" id="close-export-profile" title="Close" @click="emit('close')">&times;</button>
        </div>
        <div class="modal-body">
          <div class="export-profile-grid" id="export-profile-grid">
            <button class="export-profile-card active" data-profile="yt_shorts">
              <svg class="ep-icon" width="24" height="24" viewBox="0 0 24 24" fill="currentColor"><path d="M10 15l5.19-3L10 9v6zm11.56-7.83c.13.47.22 1.1.28 1.9.07.8.1 1.49.1 2.09L22 12c0 2.19-.16 3.8-.44 4.83-.25.9-.83 1.48-1.73 1.73-.47.13-1.33.22-2.65.28-1.3.07-2.49.1-3.59.1L12 19c-4.19 0-6.8-.16-7.83-.44-.9-.25-1.48-.83-1.73-1.73-.13-.47-.22-1.1-.28-1.9-.07-.8-.1-1.49-.1-2.09L2 12c0-2.19.16-3.8.44-4.83.25-.9.83-1.48 1.73-1.73.47-.13 1.33-.22 2.65-.28 1.3-.07 2.49-.1 3.59-.1L12 5c4.19 0 6.8.16 7.83.44.9.25 1.48.83 1.73 1.73z"/></svg>
              <span class="ep-name">YouTube Shorts</span>
              <span class="ep-desc">9:16 · 1080×1920</span>
            </button>
            <button class="export-profile-card" data-profile="tiktok">
              <svg class="ep-icon" width="24" height="24" viewBox="0 0 24 24" fill="currentColor"><path d="M19.59 6.69a4.83 4.83 0 01-3.77-4.25V2h-3.45v13.67a2.89 2.89 0 01-2.88 2.5 2.89 2.89 0 01-2.89-2.89 2.89 2.89 0 012.89-2.89c.28 0 .54.04.79.1v-3.51a6.37 6.37 0 00-.79-.05A6.34 6.34 0 003.15 15.2a6.34 6.34 0 0010.86 4.43v-7.15a8.16 8.16 0 004.77 1.52v-3.4a4.85 4.85 0 01-.81-1.56 4.82 4.82 0 01-.38-2.35z"/></svg>
              <span class="ep-name">TikTok</span>
              <span class="ep-desc">9:16 · 1080×1920</span>
            </button>
            <button class="export-profile-card" data-profile="reels">
              <svg class="ep-icon" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="2" y="2" width="20" height="20" rx="5"/><path d="M2 8h20M8 2v6M12 12l3 2-3 2v-4z"/></svg>
              <span class="ep-name">Reels</span>
              <span class="ep-desc">9:16 · 1080×1920</span>
            </button>
            <button class="export-profile-card" data-profile="yt_landscape">
              <svg class="ep-icon" width="24" height="24" viewBox="0 0 24 24" fill="currentColor"><path d="M10 15l5.19-3L10 9v6zm11.56-7.83c.13.47.22 1.1.28 1.9.07.8.1 1.49.1 2.09L22 12c0 2.19-.16 3.8-.44 4.83-.25.9-.83 1.48-1.73 1.73-.47.13-1.33.22-2.65.28-1.3.07-2.49.1-3.59.1L12 19c-4.19 0-6.8-.16-7.83-.44-.9-.25-1.48-.83-1.73-1.73-.13-.47-.22-1.1-.28-1.9-.07-.8-.1-1.49-.1-2.09L2 12c0-2.19.16-3.8.44-4.83.25-.9.83-1.48 1.73-1.73.47-.13 1.33-.22 2.65-.28 1.3-.07 2.49-.1 3.59-.1L12 5c4.19 0 6.8.16 7.83.44.9.25 1.48.83 1.73 1.73z"/></svg>
              <span class="ep-name">YouTube</span>
              <span class="ep-desc">16:9 · 1920×1080</span>
            </button>
            <button class="export-profile-card" data-profile="square">
              <svg class="ep-icon" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M10 9l5 3-5 3V9z" fill="currentColor"/></svg>
              <span class="ep-name">Square</span>
              <span class="ep-desc">1:1 · 1080×1080</span>
            </button>
          </div>
        </div>
        <div class="modal-footer">
          <button id="start-export-btn" class="btn btn-stage">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:-2px;margin-right:4px"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
            Export
          </button>
        </div>
      </div>
      <!-- Step 2: Progress -->
      <div id="export-step-progress" style="display:none">
        <div class="modal-header">
          <h3 id="export-progress-title">Exporting Video...</h3>
        </div>
        <div class="modal-body">
          <div class="export-progress-container">
            <div class="progress-bar-container">
              <div class="progress-bar" id="export-progress-bar" style="width:0%"></div>
            </div>
            <div class="progress-info">
              <span id="export-progress-percent">0%</span>
              <span id="export-progress-message">Starting export...</span>
            </div>
          </div>
        </div>
        <div class="modal-footer" id="export-progress-footer">
          <button id="cancel-export" class="btn btn-secondary">Cancel</button>
          <button id="preview-export" class="btn btn-secondary hidden">Preview Video</button>
          <button id="open-export-folder" class="btn btn-secondary hidden" title="Open folder in file explorer">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:-2px;margin-right:4px"><path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z"/></svg>
            Open Folder
          </button>
          <button id="download-export" class="btn btn-stage hidden">Download MP4</button>
        </div>
      </div>
    </div>
  </div>
</template>
