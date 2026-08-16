import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

// Step 14.2 — video-editor.js is ported verbatim and stays untested here. What
// is new, and therefore what these cases pin, is the boot bridge that replaced
// V2's Pinia stagingStore: sessionStorage plus the ?project= route query.

const STAGED = 'sts-staged-timeline'
const BOOT = 'sts-editor-boot-project'
const SCENES = 'sts-editor-scenes'
const ENTRY = 'sts-editor-entry-source'
const OPEN = 'sts-editor-last-saved-project-id'

const project = (id) => JSON.stringify({
  project_id: id,
  project_name: id,
  scenes: [{ scene_id: 0, duration: 3 }],
})

async function freshUseEditor() {
  vi.resetModules()
  const { useEditor } = await import('../composables/useEditor.js')
  return useEditor()
}

beforeEach(() => {
  sessionStorage.clear()
  localStorage.clear()
  // init() otherwise injects a <script> and polls for ten seconds.
  window.initEditor = vi.fn()
  window.resetEditor = vi.fn()
})

afterEach(() => {
  delete window.initEditor
  delete window.resetEditor
})

describe('boot payload from storage', () => {
  it('reads the staged timeline out of sessionStorage', async () => {
    sessionStorage.setItem(STAGED, project('pm_STAGED'))
    const editor = await freshUseEditor()

    await editor.init(document.createElement('div'))

    expect(editor.bootProject.value.project_id).toBe('pm_STAGED')
    expect(editor.projectName.value).toBe('pm_STAGED')
    expect(editor.sceneCount.value).toBe(1)
    expect(window.initEditor).toHaveBeenCalled()
  })

  it('falls back to the localStorage bridge keys in order', async () => {
    localStorage.setItem(SCENES, project('pm_SCENES'))
    localStorage.setItem(BOOT, project('pm_BOOT'))
    const editor = await freshUseEditor()

    await editor.init(document.createElement('div'))

    expect(editor.bootProject.value.project_id).toBe('pm_BOOT')
  })

  it('ignores a payload with no scenes', async () => {
    sessionStorage.setItem(STAGED, JSON.stringify({ project_id: 'pm_EMPTY', scenes: [] }))
    const editor = await freshUseEditor()

    await editor.init(document.createElement('div'))

    expect(editor.bootProject.value).toBeNull()
  })

  it('survives malformed bridge data', async () => {
    sessionStorage.setItem(STAGED, '{not json')
    const editor = await freshUseEditor()

    await editor.init(document.createElement('div'))

    expect(editor.bootProject.value).toBeNull()
    expect(window.initEditor).toHaveBeenCalled()
  })
})

describe('?project= route query', () => {
  it('names the project for the boot flow and clears stale staged scenes', async () => {
    sessionStorage.setItem(STAGED, project('pm_STALE'))
    localStorage.setItem(BOOT, project('pm_STALE'))
    localStorage.setItem(SCENES, project('pm_STALE'))
    const editor = await freshUseEditor()

    await editor.init(document.createElement('div'), { projectId: 'pm_WANTED' })

    expect(sessionStorage.getItem(STAGED)).toBeNull()
    expect(localStorage.getItem(BOOT)).toBeNull()
    expect(localStorage.getItem(SCENES)).toBeNull()
    expect(localStorage.getItem(OPEN)).toBe('pm_WANTED')
    // Anything but 'menu' tells video-editor.js to boot rather than show
    // the project picker.
    expect(sessionStorage.getItem(ENTRY)).not.toBe('menu')
    expect(editor.bootProject.value).toBeNull()
  })

  it('leaves the storage bridge alone when no project is named', async () => {
    sessionStorage.setItem(STAGED, project('pm_STAGED'))
    const editor = await freshUseEditor()

    await editor.init(document.createElement('div'))

    expect(sessionStorage.getItem(STAGED)).not.toBeNull()
    expect(localStorage.getItem(OPEN)).toBeNull()
  })
})

describe('lifecycle', () => {
  it('initializes once, and re-initializes only after reset', async () => {
    const editor = await freshUseEditor()

    await editor.init(document.createElement('div'))
    await editor.init(document.createElement('div'))
    expect(window.initEditor).toHaveBeenCalledTimes(1)

    editor.destroy()
    expect(window.resetEditor).toHaveBeenCalled()
    expect(editor.initialized.value).toBe(false)

    // Destroyed is sticky until reset(), so a stray init() stays a no-op.
    await editor.init(document.createElement('div'))
    expect(window.initEditor).toHaveBeenCalledTimes(1)

    editor.reset()
    await editor.init(document.createElement('div'))
    expect(window.initEditor).toHaveBeenCalledTimes(2)
  })

  it('loadProject hands the payload to the imperative editor', async () => {
    window.editorLoadScenes = vi.fn()
    const editor = await freshUseEditor()

    editor.loadProject(JSON.parse(project('pm_LATE')))

    expect(window.editorLoadScenes).toHaveBeenCalledWith(
      expect.objectContaining({ project_id: 'pm_LATE' }),
    )
    expect(editor.projectName.value).toBe('pm_LATE')
    delete window.editorLoadScenes
  })
})
