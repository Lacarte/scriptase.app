<script setup>
defineOptions({ name: 'ShareDialog' })
defineProps({ visible: Boolean })
const emit = defineEmits(['close'])
function onClose() { emit('close') }
</script>

<template>
  <div v-if="visible" id="project-share-modal" class="modal active">
    <div class="modal-content modal-sm" style="border-radius:16px;overflow:hidden">
      <!-- Header with gradient accent -->
      <div style="position:relative;padding:20px 20px 16px;background:linear-gradient(135deg,rgba(78,205,196,0.08) 0%,rgba(78,205,196,0.02) 100%);border-bottom:1px solid var(--border)">
        <button class="modal-close" id="close-share-modal" title="Close" style="position:absolute;top:12px;right:12px" @click="onClose">&times;</button>
        <div style="display:flex;align-items:center;gap:12px">
          <div style="width:40px;height:40px;border-radius:10px;background:linear-gradient(135deg,var(--accent),#3BA99C);display:flex;align-items:center;justify-content:center;flex-shrink:0;box-shadow:0 4px 12px rgba(78,205,196,0.25)">
            <svg width="18" height="18" fill="none" stroke="#fff" stroke-width="2" viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>
          </div>
          <div style="min-width:0;flex:1">
            <div style="font-size:15px;font-weight:700;color:var(--text);letter-spacing:-0.02em">Export, Import &amp; Share</div>
            <div style="display:flex;align-items:center;gap:6px;margin-top:2px">
              <span id="share-project-name" style="font-size:12px;font-weight:600;color:var(--accent);font-family:'JetBrains Mono',monospace"></span>
              <span style="opacity:0.3">/</span>
              <span id="share-project-meta" style="font-size:11px;color:var(--text-muted)"></span>
            </div>
          </div>
        </div>
      </div>
      <!-- Actions -->
      <div style="padding:14px 16px 18px;display:flex;flex-direction:column;gap:6px">
        <!-- Export Video -->
        <div>
          <button id="share-export-video" class="btn btn-secondary" style="display:flex;align-items:center;gap:12px;padding:12px 14px;text-align:left;width:100%;justify-content:flex-start;border-radius:10px;transition:all 0.15s ease">
            <div style="flex-shrink:0;width:34px;height:34px;border-radius:8px;background:rgba(255,107,107,0.1);display:flex;align-items:center;justify-content:center">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#FF6B6B" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polygon points="23 7 16 12 23 17 23 7"/><rect x="1" y="5" width="15" height="14" rx="2" ry="2"/>
              </svg>
            </div>
            <div style="flex:1;min-width:0">
              <div style="font-size:13px;font-weight:600">Export Video</div>
              <div style="font-size:10px;color:var(--text-muted);font-weight:400;margin-top:1px">Render &amp; download as MP4</div>
            </div>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;opacity:0.4"><path d="M9 18l6-6-6-6"/></svg>
          </button>
        </div>
        <!-- Divider -->
        <div style="height:1px;background:var(--border);margin:2px 8px;opacity:0.5"></div>
        <!-- Export ZIP -->
        <div>
          <button id="share-export-zip" class="btn btn-secondary" style="display:flex;align-items:center;gap:12px;padding:12px 14px;text-align:left;width:100%;justify-content:flex-start;border-radius:10px;transition:all 0.15s ease">
            <div id="share-export-icon" style="flex-shrink:0;width:34px;height:34px;border-radius:8px;background:rgba(78,205,196,0.1);display:flex;align-items:center;justify-content:center">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
              </svg>
            </div>
            <div style="flex:1;min-width:0">
              <div id="share-export-label" style="font-size:13px;font-weight:600">Export ZIP</div>
              <div id="share-export-desc" style="font-size:10px;color:var(--text-muted);font-weight:400;margin-top:1px">Download project with all assets, audio &amp; data</div>
            </div>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;opacity:0.4"><path d="M9 18l6-6-6-6"/></svg>
          </button>
          <div id="share-export-progress" style="display:none;margin:6px 16px 2px">
            <div style="height:3px;border-radius:2px;background:var(--bg-darkest);overflow:hidden">
              <div id="share-export-bar" style="height:100%;width:0%;border-radius:2px;transition:width 0.3s ease"></div>
            </div>
            <div id="share-export-status" style="font-size:10px;color:var(--text-muted);margin-top:4px"></div>
          </div>
        </div>
        <!-- Divider -->
        <div style="height:1px;background:var(--border);margin:2px 8px;opacity:0.5"></div>
        <!-- Import ZIP -->
        <div>
          <button id="share-import-zip" class="btn btn-secondary" style="display:flex;align-items:center;gap:12px;padding:12px 14px;text-align:left;width:100%;justify-content:flex-start;border-radius:10px;transition:all 0.15s ease">
            <div id="share-import-icon" style="flex-shrink:0;width:34px;height:34px;border-radius:8px;background:rgba(167,139,250,0.1);display:flex;align-items:center;justify-content:center">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#A78BFA" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>
              </svg>
            </div>
            <div style="flex:1;min-width:0">
              <div id="share-import-label" style="font-size:13px;font-weight:600">Import ZIP</div>
              <div id="share-import-desc" style="font-size:10px;color:var(--text-muted);font-weight:400;margin-top:1px">Restore a project from a shared ZIP file</div>
            </div>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;opacity:0.4"><path d="M9 18l6-6-6-6"/></svg>
          </button>
          <div id="share-import-progress" style="display:none;margin:6px 16px 2px">
            <div style="height:3px;border-radius:2px;background:var(--bg-darkest);overflow:hidden">
              <div id="share-import-bar" style="height:100%;width:0%;border-radius:2px;transition:width 0.3s ease"></div>
            </div>
            <div id="share-import-status" style="font-size:10px;color:var(--text-muted);margin-top:4px"></div>
          </div>
        </div>
      </div>
      <input type="file" id="share-import-file" accept=".zip" style="display:none" />
    </div>
  </div>
</template>
