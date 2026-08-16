<script setup>
defineOptions({ name: 'AssetPickerDialog' })
defineProps({ visible: Boolean })
const emit = defineEmits(['close'])
function onClose() {
  if (typeof window.editorCloseAssetPicker === 'function') window.editorCloseAssetPicker()
  emit('close')
}
</script>

<template>
  <div v-if="visible" id="asset-picker-dialog" class="no-data-overlay"
      style="display:flex;background:rgba(0,0,0,0.75);backdrop-filter:blur(6px)">
    <div
        style="width:420px;max-height:70vh;background:var(--bg-darker, #1a1a2e);border:1px solid var(--border, #2a2a3e);border-radius:12px;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 20px 60px rgba(0,0,0,0.5)">
      <div
          style="display:flex;align-items:center;justify-content:space-between;padding:16px 20px;border-bottom:1px solid var(--border, #2a2a3e)">
        <div>
          <h3 style="margin:0;font-size:14px;font-weight:600;color:var(--text, #e0e0e0)">Import Project</h3>
          <p style="margin:2px 0 0;font-size:11px;color:var(--text-muted, #666)">Load a saved editor project or asset project</p>
        </div>
        <button @click="onClose"
            style="background:none;border:none;cursor:pointer;color:var(--text-muted, #666);padding:4px;border-radius:4px;transition:color 0.15s"
            onmouseover="this.style.color='var(--text, #e0e0e0)'"
            onmouseout="this.style.color='var(--text-muted, #666)'">&times;</button>
      </div>
      <div id="asset-picker-list" style="flex:1;overflow-y:auto;padding:8px"></div>
    </div>
  </div>
</template>
