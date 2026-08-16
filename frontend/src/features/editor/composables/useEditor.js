import { ref, readonly, shallowRef } from 'vue'

/* ------------------------------------------------------------------ */
/*  useEditor — singleton composable                                   */
/*  Wraps the imperative video-editor.js lifecycle.                    */
/*  Heavy lifting stays in the original JS; this is a thin bridge.    */
/* ------------------------------------------------------------------ */

const initialized = ref(false)
const projectName = ref('No project loaded')
const sceneCount = ref(0)
const saveStatus = ref('')      // '', 'saving', 'saved', 'save-error'
const canUndo = ref(false)
const canRedo = ref(false)

/** Raw boot payload read from storage (if any) */
const bootProject = shallowRef(null)

let _containerEl = null
let _destroyed = false

/* ---------- Storage bridge ----------
 * video-editor.js boots itself from these keys; nothing else in this app
 * writes them. V2 fronted them with a Pinia store that only wrapped the same
 * reads and writes, so the store is gone and the keys are the contract.
 */

const STAGED_KEY = 'sts-staged-timeline'          // sessionStorage
const BOOT_KEY = 'sts-editor-boot-project'        // localStorage
const SCENES_KEY = 'sts-editor-scenes'            // localStorage
const ENTRY_SOURCE_KEY = 'sts-editor-entry-source' // sessionStorage, one-shot
const OPEN_PROJECT_KEY = 'sts-editor-last-saved-project-id' // localStorage

function getStoredBootProject() {
  const candidates = [
    sessionStorage.getItem(STAGED_KEY),
    localStorage.getItem(BOOT_KEY),
    localStorage.getItem(SCENES_KEY),
  ]

  for (const raw of candidates) {
    if (!raw) continue
    try {
      const data = JSON.parse(raw)
      if (data && Array.isArray(data.scenes) && data.scenes.length) {
        return data
      }
    } catch { /* ignore malformed bridge data */ }
  }

  return null
}

/**
 * Point the boot flow at one specific saved project.
 *
 * The route carries `?project=<id>` (workflow's "Open in Timeline Editor").
 * Stale staged scenes from an earlier session would otherwise win the boot
 * race in video-editor.js, so they are dropped: the URL is the instruction.
 */
function stageProjectId(projectId) {
  try {
    sessionStorage.removeItem(STAGED_KEY)
    localStorage.removeItem(BOOT_KEY)
    localStorage.removeItem(SCENES_KEY)
    localStorage.setItem(OPEN_PROJECT_KEY, projectId)
    // Any value other than 'menu' means "boot a project, don't show the picker".
    sessionStorage.setItem(ENTRY_SOURCE_KEY, 'project')
  } catch { /* storage full or unavailable */ }
}

/* ---------- Public API -------------- */

/**
 * Initialize the imperative editor inside the given container element.
 * Dynamically imports video-editor.js and calls window.initEditor().
 */
async function init(containerEl, { projectId = null } = {}) {
  if (initialized.value || _destroyed) return
  _containerEl = containerEl

  if (projectId) stageProjectId(projectId)

  // Read boot data from storage
  bootProject.value = getStoredBootProject()
  if (bootProject.value) {
    projectName.value = bootProject.value.project_name
      || bootProject.value.source_folder
      || 'Untitled'
    sceneCount.value = bootProject.value.scenes?.length ?? 0
  }

  // The editor scripts live in public/ as classic ES modules, so they cannot
  // be import()ed through the bundler — they are loaded by <script> tag and
  // expose their entry points on window.
  if (typeof window.initEditor !== 'function') {
    try {
      const s = document.createElement('script')
      s.type = 'module'
      s.src = `${import.meta.env.BASE_URL}js/editor/video-editor.js`
      document.head.appendChild(s)
      // Poll for window.initEditor — module scripts execute asynchronously
      await new Promise((resolve, reject) => {
        let elapsed = 0
        const iv = setInterval(() => {
          if (typeof window.initEditor === 'function') {
            clearInterval(iv)
            resolve()
          } else if ((elapsed += 50) > 10000) {
            clearInterval(iv)
            reject(new Error('Editor module did not load within 10s'))
          }
        }, 50)
      })
    } catch (e) {
      console.warn('[useEditor] Could not load video-editor.js:', e.message)
    }
  }

  if (typeof window.initEditor === 'function') {
    // initEditor() handles its own boot flow (load from storage / show picker).
    // Do NOT call editorLoadScenes again via _onEditorReady — that causes a
    // double-bootstrap race where the second run conflicts with the first.
    window.initEditor()
    initialized.value = true
  } else {
    console.warn('[useEditor] Editor module not available')
  }
}

/**
 * Load a project payload into the already-initialized editor.
 */
function loadProject(projectData) {
  if (!projectData) return
  bootProject.value = projectData

  projectName.value = projectData.project_name
    || projectData.source_folder
    || 'Untitled'
  sceneCount.value = projectData.scenes?.length ?? 0

  if (typeof window.editorLoadScenes === 'function') {
    window.editorLoadScenes(projectData)
  }
}

/**
 * Tear down the editor (called on unmount).
 */
function destroy() {
  _destroyed = true
  _containerEl = null
  initialized.value = false
  // Reset the imperative editor module state so it can re-init on next visit
  if (typeof window.resetEditor === 'function') {
    window.resetEditor()
  }
}

/**
 * Reset the singleton so it can be re-initialized (e.g. after route leave + return).
 */
function reset() {
  _destroyed = false
}

export function useEditor() {
  return {
    initialized: readonly(initialized),
    projectName: readonly(projectName),
    sceneCount: readonly(sceneCount),
    saveStatus: readonly(saveStatus),
    canUndo: readonly(canUndo),
    canRedo: readonly(canRedo),
    bootProject: readonly(bootProject),
    init,
    destroy,
    reset,
    loadProject,
  }
}
