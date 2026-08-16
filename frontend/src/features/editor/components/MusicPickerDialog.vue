<script setup>
defineOptions({ name: 'MusicPickerDialog' })
defineProps({ visible: Boolean })
const emit = defineEmits(['close'])
function onClose() {
  if (typeof window.editorCloseMusicPicker === 'function') window.editorCloseMusicPicker()
  emit('close')
}
function onUpload(el) {
  if (typeof window.editorUploadMusic === 'function') window.editorUploadMusic(el)
}
</script>

<template>
  <div v-if="visible" id="music-picker-dialog" class="no-data-overlay"
      style="display:flex;background:rgba(0,0,0,0.75);backdrop-filter:blur(6px)">
    <div
        style="width:420px;max-height:70vh;background:var(--bg-darker, #1a1a2e);border:1px solid var(--border, #2a2a3e);border-radius:12px;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 20px 60px rgba(0,0,0,0.5)">
      <div
          style="display:flex;align-items:center;justify-content:space-between;padding:16px 20px;border-bottom:1px solid var(--border, #2a2a3e)">
        <div>
          <div style="font-weight:600;font-size:14px;color:var(--text)">Add Background Music</div>
          <div style="font-size:11px;color:var(--text-muted);margin-top:2px">Select from library or upload</div>
        </div>
        <button @click="onClose"
            style="background:none;border:none;color:var(--text-muted);font-size:20px;cursor:pointer;padding:4px">&times;</button>
      </div>
      <div id="music-picker-list" style="flex:1;overflow-y:auto;padding:8px 12px;max-height:340px">
        <div style="text-align:center;padding:32px 16px;color:var(--text-muted);font-size:12px">
          <p style="margin-bottom:12px">No music files yet</p>
          <p style="font-size:11px;opacity:0.6">Built-in: resources/sounds/music/&lt;folder&gt;/<br>Uploads: output/musics/</p>
        </div>
      </div>
      <div style="padding:12px 16px;border-top:1px solid var(--border, #2a2a3e);display:flex;gap:8px">
        <label
            style="flex:1;display:flex;align-items:center;justify-content:center;gap:6px;padding:8px;background:var(--bg-surface);border:1px dashed var(--border);border-radius:8px;cursor:pointer;color:var(--text-secondary);font-size:12px">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
            <polyline points="17 8 12 3 7 8" />
            <line x1="12" y1="3" x2="12" y2="15" />
          </svg>
          Upload
          <input type="file" accept=".mp3,.wav,.ogg,.m4a" id="music-upload-input" style="display:none"
              @change="onUpload($event.target)">
        </label>
      </div>
    </div>
  </div>
</template>
