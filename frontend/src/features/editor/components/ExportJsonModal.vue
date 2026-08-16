<script setup>
defineOptions({ name: 'ExportJsonModal' })
defineProps({ visible: Boolean })
const emit = defineEmits(['close'])
</script>

<template>
  <div v-if="visible" id="export-modal" class="modal active">
    <div class="modal-content modal-lg">
      <div class="modal-header">
        <h3>Export JSON</h3>
        <button class="modal-close" id="close-export-modal" title="Close" @click="emit('close')">&times;</button>
      </div>
      <div class="modal-body">
        <pre id="export-json" class="json-preview"></pre>
      </div>
      <div class="modal-footer">
        <button id="copy-export-json" class="btn btn-secondary">Copy JSON</button>
        <button id="download-export-json" class="btn btn-stage">Download JSON</button>
      </div>
    </div>
  </div>
</template>
