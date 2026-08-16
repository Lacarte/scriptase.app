<script setup>
defineOptions({ name: 'ResetConfirmModal' })
defineProps({ visible: Boolean })
const emit = defineEmits(['confirm', 'cancel'])
</script>

<template>
  <div v-if="visible" id="reset-confirm-modal" class="modal" style="display:flex">
    <div class="modal-content" style="max-width:380px;border-radius:14px;overflow:hidden">
      <div style="padding:24px 24px 0;text-align:center">
        <div style="width:48px;height:48px;border-radius:50%;background:rgba(255,107,107,0.12);display:inline-flex;align-items:center;justify-content:center;margin-bottom:14px">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#FF6B6B" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 105.64-11.36L1 10"/>
          </svg>
        </div>
        <h3 style="margin:0 0 8px;font-size:1rem;font-weight:600;color:var(--text)">Reset to Initial?</h3>
        <p style="margin:0;font-size:0.78rem;color:var(--text-muted);line-height:1.5">All edits — effects, audio, captions, text, and timing changes — will be discarded. This cannot be undone.</p>
      </div>
      <div style="display:flex;gap:10px;padding:20px 24px 24px;justify-content:center">
        <button id="reset-cancel-btn" style="flex:1;padding:9px 0;border-radius:8px;border:1px solid var(--border);background:var(--bg-surface);color:var(--text-muted);font-size:0.78rem;font-weight:500;cursor:pointer" @click="emit('cancel')">Cancel</button>
        <button id="reset-confirm-btn" style="flex:1;padding:9px 0;border-radius:8px;border:none;background:#FF6B6B;color:#fff;font-size:0.78rem;font-weight:600;cursor:pointer" @click="emit('confirm')">Reset Project</button>
      </div>
    </div>
  </div>
</template>
