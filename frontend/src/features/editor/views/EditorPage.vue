<script setup>
import { ref, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useEditor } from '../composables/useEditor.js'
import { EDITOR_SHELL_HTML } from '../editor-shell-html.js' // dialogs now Vue components
import { initEditorInlineScripts } from '../editor-inline-scripts.js'
import ResetConfirmModal from '../components/ResetConfirmModal.vue'
import ExportJsonModal from '../components/ExportJsonModal.vue'
import ExportProgressModal from '../components/ExportProgressModal.vue'
import MusicPickerDialog from '../components/MusicPickerDialog.vue'
import ShareDialog from '../components/ShareDialog.vue'
import NoDataOverlay from '../components/NoDataOverlay.vue'
import AssetPickerDialog from '../components/AssetPickerDialog.vue'
import TTSPickerDialog from '../components/TTSPickerDialog.vue'
import '../styles/editor.css'

defineOptions({ name: 'EditorPage' })

const { init, destroy, reset } = useEditor()
const route = useRoute()
const router = useRouter()
const shellRef = ref(null)

// Dialog visibility state
const showResetModal = ref(false)
const showExportJsonModal = ref(false)
const showExportProgressModal = ref(false)
const showMusicPicker = ref(false)
const showShareDialog = ref(false)
const showNoData = ref(false)
const showAssetPicker = ref(false)
const showTTSPicker = ref(false)

// Bridge: expose show/hide on window so legacy video-editor.js can trigger dialogs
function setupDialogBridge() {
  window._vueShowResetModal = () => { showResetModal.value = true }
  window._vueHideResetModal = () => { showResetModal.value = false }
  window._vueShowExportJsonModal = () => { showExportJsonModal.value = true }
  window._vueHideExportJsonModal = () => { showExportJsonModal.value = false }
  window._vueShowExportProgressModal = () => { showExportProgressModal.value = true }
  window._vueHideExportProgressModal = () => { showExportProgressModal.value = false }
  window._vueShowMusicPicker = () => { showMusicPicker.value = true }
  window._vueHideMusicPicker = () => { showMusicPicker.value = false }
  window._vueShowShareDialog = () => { showShareDialog.value = true }
  window._vueHideShareDialog = () => { showShareDialog.value = false }
  window._vueShowNoData = () => { showNoData.value = true }
  window._vueHideNoData = () => { showNoData.value = false }
  window._vueShowAssetPicker = () => { showAssetPicker.value = true }
  window._vueHideAssetPicker = () => { showAssetPicker.value = false }
  window._vueShowTTSPicker = () => { showTTSPicker.value = true }
  window._vueHideTTSPicker = () => { showTTSPicker.value = false }

  /**
   * The way out.
   *
   * `/editor` is a `bare` route, so App.vue renders no topbar — the Editor
   * keeps its own teal identity, as the prototype intends. That left it with
   * no exit at all: the one back-arrow in the header was wired to the asset
   * picker and titled "Import Project", so the control that looked like the
   * way back was the one thing that was not.
   *
   * Opened through `Editor ↗` this is its own window, and closing it is what
   * the user means by back. Navigated to in the same tab there is nothing to
   * close, so it returns to Production — the prototype's "Back to batch".
   */
  window.editorGoBack = () => {
    if (window.opener && !window.opener.closed) {
      window.close()
      return
    }
    router.push({ name: 'production' })
  }
}

function cleanupDialogBridge() {
  const keys = [
    '_vueShowResetModal', '_vueHideResetModal',
    '_vueShowExportJsonModal', '_vueHideExportJsonModal',
    '_vueShowExportProgressModal', '_vueHideExportProgressModal',
    '_vueShowMusicPicker', '_vueHideMusicPicker',
    '_vueShowShareDialog', '_vueHideShareDialog',
    '_vueShowNoData', '_vueHideNoData',
    '_vueShowAssetPicker', '_vueHideAssetPicker',
    '_vueShowTTSPicker', '_vueHideTTSPicker',
    'editorGoBack',
  ]
  keys.forEach(k => delete window[k])
}

function onResetConfirm() {
  showResetModal.value = false
  if (typeof window.resetEditor === 'function') window.resetEditor()
}

onMounted(async () => {
  reset()
  setupDialogBridge()
  if (shellRef.value) {
    shellRef.value.innerHTML = EDITOR_SHELL_HTML
  }
  initEditorInlineScripts()
  await nextTick()
  if (shellRef.value) {
    const projectId = typeof route.query.project === 'string' ? route.query.project : null
    // Default to 'menu' (show asset import list) unless a project was named
    // in the URL, or another page already set the entry source.
    if (!projectId && !sessionStorage.getItem('sts-editor-entry-source')) {
      sessionStorage.setItem('sts-editor-entry-source', 'menu')
    }
    init(shellRef.value, { projectId })
  }
})

onBeforeUnmount(() => {
  cleanupDialogBridge()
  destroy()
})
</script>

<template>
  <div class="editor-page">
    <div
      id="editor-shell"
      ref="shellRef"
      class="editor-shell editor-shell-booting"
    />

    <!-- Vue-managed dialogs (migrated from editor-shell-html.js) -->
    <MusicPickerDialog :visible="showMusicPicker" @close="showMusicPicker = false" />
    <ShareDialog :visible="showShareDialog" @close="showShareDialog = false" />
    <NoDataOverlay :visible="showNoData" @close="showNoData = false" />
    <AssetPickerDialog :visible="showAssetPicker" @close="showAssetPicker = false" />
    <TTSPickerDialog :visible="showTTSPicker" @close="showTTSPicker = false" />
    <ResetConfirmModal :visible="showResetModal" @confirm="onResetConfirm" @cancel="showResetModal = false" />
    <ExportJsonModal :visible="showExportJsonModal" @close="showExportJsonModal = false" />
    <ExportProgressModal :visible="showExportProgressModal" @close="showExportProgressModal = false" />
  </div>
</template>

<style scoped>
/* 100% rather than V2's 100vh: this app renders the editor below a top nav
   bar, so a viewport-height page would overflow by exactly that bar. The
   route sets meta.fullHeight, which gives the shell a bounded height. */
.editor-page {
  position: relative;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  background: #040404;
}
</style>
