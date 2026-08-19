/**
 * Step 6.8 — the fidelity gate.
 *
 * Phase 6 ported the prototype's component layer one view at a time. This is
 * the check that keeps it ported, and that says how much of it is actually
 * done.
 *
 * The first version of this gate audited sixteen class *prefixes* — the
 * families Phase 6 named. That let 261 of the prototype's 593 in-scope classes
 * fall outside every family and go unchecked, and the app shipped without the
 * on-air pill, the accent shuffle, the avatar, the archive calendar's `cal-*`
 * set, the config rail and the narration player while the gate stayed green.
 * A gate whose coverage is a hand-kept list of prefixes measures the list, not
 * the prototype.
 *
 * So the unit here is the class, and the denominator is every class the
 * prototype declares. Each one either resolves in the app's CSS or is named in
 * `LEDGER` with a reason. Nothing falls between.
 *
 * What this deliberately does not do is compare declarations. The app spells
 * the prototype's inline literals as tokens, its `.toast.out` as a Vue
 * transition and its `.pv-status-dot.st-connecting` as a reduced-motion block —
 * every one correct, not one textually equal. Declaration drift is real but it
 * is a different check with a different tolerance.
 *
 * The Editor is out of scope by the phase's own terms: `ed-*` is its teal
 * identity, it lives in `features/editor/styles/editor.css`, and that file is
 * not scanned.
 */
import { readFileSync, readdirSync } from 'node:fs'
import { join, relative, resolve, sep } from 'node:path'

import { describe, expect, it } from 'vitest'

// Resolved from the Vitest root rather than `import.meta.url`: under the jsdom
// environment the module URL is not a `file:` URL, so `fileURLToPath` throws
// before a single test collects. `process.cwd()` is what the rest of the suite
// uses for the same reason (App.test.js, legacySelection.test.js).
const SRC = resolve(process.cwd(), 'src') + sep
const PROTOTYPE = resolve(process.cwd(), '..', 'prototype', 'scriptase-prototype.html')

/** The Editor keeps its own identity and its own stylesheet; neither is ported. */
const UNSCANNED = ['features/editor']

/** `ed-*` is the Editor's family and the one prefix excluded wholesale. */
const OUT_OF_SCOPE = /^ed-/

// ---------------------------------------------------------------------------
// The ledger. Every prototype class the app does not carry is named here with
// the reason it is not carried. Two kinds of entry live in it:
//
//   BEHAVIOUR — the app deliberately does not have the thing. These are
//     permanent and each has prose behind it in the feature's README.
//   UNPORTED  — Phase 6 has not reached it yet. These are debt, and the count
//     below is the number the next fidelity step has to bring down.
//
// The distinction is machine-readable so `npm run test` reports remaining port
// debt as a number rather than leaving it to be rediscovered from screenshots.
// ---------------------------------------------------------------------------

const BEHAVIOUR = 'behaviour'
const UNPORTED = 'unported'

/** Shared reasons, so a hundred entries do not become a hundred paragraphs. */
const WHY = {
  transcode: [BEHAVIOUR, 'format and quality selects with no transcode behind them (export-library/README.md)'],
  simulated: [BEHAVIOUR, 'a simulated encode; download is one fetch (export-library/README.md)'],
  noSecret: [BEHAVIOUR, 'a provider is discovered or excluded, never enabled, and stored secrets are never returned to the browser (providers/README.md)'],
  rowMenu: [BEHAVIOUR, 'the row context menu — ProductionPage.vue, the `.job` comment'],
  scroller: [BEHAVIOUR, "the prototype's queue reorder drag handle"],
  protoOnly: [BEHAVIOUR, "prototype-internal shorthand with no rendered counterpart — the app's markup does not emit it"],
  edModifier: [BEHAVIOUR, 'modifier class always scoped under an ed-* selector in the prototype; the Editor is excluded from the gate'],
  s1Player: [BEHAVIOUR, "the app uses s1-play / s1-wave-track for real narration audio; the prototype's generic play-btn is simulated-only and not emitted (script/README.md)"],
  mediaBound: [BEHAVIOUR, 'aspect ratio and watermark are Channel fields — the app binds them from data (--fr CSS variable, computed watermark position) rather than toggling presentation classes (channels/README.md)'],
  statusVocabulary: [BEHAVIOUR, 'the backend emits queued|running|paused|awaiting_approval|completed|failed|cancelled — these prototype states have no equivalent and the app renders from real Job statuses only (jobs/README.md)'],
  edCanvasChild: [BEHAVIOUR, 'always scoped under .ed-canvas in the prototype; the app editor displays scene identity in its own panel'],
}

/** class → key in WHY. */
const LEDGER = {
  // --- behaviour ---------------------------------------------------------
  // `plat` left the ledger when Production's channel picker gained the chips:
  // it is the prototype's `.ch-meta .row2 .plat` container, not shorthand.
  'exp-opt': 'transcode',
  'exp-opts': 'transcode',
  'exp-progress': 'simulated',
  'exp-watermark': 'simulated',
  track: 'simulated',
  'pv-enable': 'noSecret',
  'pv-secret': 'noSecret',
  'job-menu-btn': 'rowMenu',
  am: 'protoOnly',
  an: 'protoOnly',
  app: 'protoOnly',
  as: 'protoOnly',
  body: 'protoOnly',
  ci: 'protoOnly',
  ico: 'protoOnly',
  kk: 'protoOnly',
  ti: 'protoOnly',
  head: 'protoOnly',
  kick: 'protoOnly',
  welcomed: 'protoOnly',
  'editor-view': 'protoOnly',
  'cl-label': 'protoOnly',
  cavatar: 'protoOnly',
  stage: 'protoOnly',
  subtitle: 'protoOnly',
  'play-btn': 's1Player',
  wave: 's1Player',
  played: 'edModifier',
  tick: 'edModifier',
  audio: 'edModifier',
  caption: 'edModifier',

  // --- resolved in step 8.4 -----------------------------------------------
  'drag-handle': 'scroller',
  'r-1-1': 'mediaBound',
  'r-16-9': 'mediaBound',
  wm: 'mediaBound',
  thumb: 'mediaBound',
  'st-draft': 'statusVocabulary',
  'st-preparing': 'statusVocabulary',
  'st-stopped': 'statusVocabulary',
  'st-stopping': 'statusVocabulary',
  scenetag: 'edCanvasChild',
  'kb-focus': 'protoOnly',
  collapsed: 'protoOnly',
}

// ---------------------------------------------------------------------------
// Reading CSS. Both sides are read the same way, so neither can drift from the
// other by accident of parsing.
// ---------------------------------------------------------------------------

const STYLE_BLOCK = /<style[^>]*>([\s\S]*?)<\/style>/gi
const COMMENT = /\/\*[\s\S]*?\*\//g
// A rule's selector: everything between the end of the last statement and the
// `{` that opens this one. Excluding `;`, `}` and `@` is what stops the match
// running through a declaration or into an at-rule prelude.
const SELECTOR = /(?:^|[}\n;])\s*([^{}@;]+?)\s*\{/g
const CLASS = /\.(-?[A-Za-z_][\w-]*)/g

function styleBlocks(html) {
  return [...html.matchAll(STYLE_BLOCK)].map(match => match[1]).join('\n')
}

function classSelectors(css) {
  const found = new Set()
  for (const [, selector] of css.replace(COMMENT, '').matchAll(SELECTOR)) {
    for (const [, name] of selector.matchAll(CLASS)) found.add(name)
  }
  return found
}

function cssSources(dir = SRC) {
  const sources = []
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name)
    const rel = relative(SRC, path).split(sep).join('/')
    if (entry.isDirectory()) {
      if (!UNSCANNED.includes(rel)) sources.push(...cssSources(path))
    } else if (entry.name.endsWith('.css')) {
      sources.push(readFileSync(path, 'utf8'))
    } else if (entry.name.endsWith('.vue')) {
      sources.push(styleBlocks(readFileSync(path, 'utf8')))
    }
  }
  return sources
}

const PROTOTYPE_CLASSES = [...classSelectors(styleBlocks(readFileSync(PROTOTYPE, 'utf8')))].sort()
const IN_SCOPE = PROTOTYPE_CLASSES.filter(name => !OUT_OF_SCOPE.test(name))
const APP_CSS = cssSources().join('\n')
const APP_CLASSES = classSelectors(APP_CSS)

const REQUIRED = IN_SCOPE.filter(name => !(name in LEDGER))

/**
 * The app's CSS with every rule that styles `className` removed — what deleting
 * a ported rule looks like. Repeated until stable because two rules can share
 * the `}` this anchors on.
 */
function withoutRulesFor(css, className) {
  const rule = new RegExp(
    `([}\\n;]|^)\\s*([^{}@;]*\\.${className}(?![\\w-])[^{}@;]*)\\{[^{}]*\\}`,
    'gm',
  )
  let stripped = css
  let previous
  do {
    previous = stripped
    stripped = stripped.replace(rule, '$1')
  } while (stripped !== previous)
  return stripped
}

// ---------------------------------------------------------------------------

describe('every prototype class is accounted for', () => {
  it('resolves in the app or is named in the ledger', () => {
    const unaccounted = IN_SCOPE.filter(name => !APP_CLASSES.has(name) && !(name in LEDGER))
    expect(unaccounted).toEqual([])
  })

  it('covers the whole prototype, not a list of prefixes', () => {
    // The regression that let 261 classes go unchecked. Every in-scope class is
    // either required of the app or excused by name — there is no third state.
    const accounted = IN_SCOPE.filter(name => APP_CLASSES.has(name) || name in LEDGER)
    expect(accounted.length).toBe(IN_SCOPE.length)
  })
})

describe('the ledger stays honest', () => {
  it('names only classes the prototype still has', () => {
    const stale = Object.keys(LEDGER).filter(name => !PROTOTYPE_CLASSES.includes(name))
    expect(stale).toEqual([])
  })

  it('names nothing the app went on to implement', () => {
    // Porting a class means deleting its ledger entry, so debt cannot be paid
    // off silently and then forgotten.
    const answered = Object.keys(LEDGER).filter(name => APP_CLASSES.has(name))
    expect(answered).toEqual([])
  })

  it('gives every entry a reason that exists', () => {
    const dangling = Object.entries(LEDGER).filter(([, key]) => !(key in WHY))
    expect(dangling).toEqual([])
  })

  it('excludes nothing outside the prototype scope', () => {
    const editor = Object.keys(LEDGER).filter(name => OUT_OF_SCOPE.test(name))
    expect(editor).toEqual([])
  })
})

describe('remaining port debt is visible', () => {
  it('reports the unported count', () => {
    const debt = Object.entries(LEDGER)
      .filter(([, key]) => WHY[key][0] === UNPORTED)
      .map(([name]) => name)
      .sort()

    // Not a target to game: the number moves when a step ports a family and
    // deletes its entries. It is asserted so that porting work shows up as a
    // failing test the moment the ledger and the CSS disagree.
    expect(debt.length).toBe(0)
  })

  it('every reason names at least one class', () => {
    const used = new Set(Object.values(LEDGER))
    const unusedReasons = Object.keys(WHY).filter(key => !used.has(key))
    expect(unusedReasons).toEqual([])
  })
})

describe('the Editor stays outside the system', () => {
  it('keeps its family in its own stylesheet', () => {
    const editorClasses = PROTOTYPE_CLASSES.filter(name => OUT_OF_SCOPE.test(name))
    expect(editorClasses.length).toBeGreaterThan(0)
    // Scanned CSS excludes features/editor, so any hit here is a leak.
    expect(editorClasses.filter(name => APP_CLASSES.has(name))).toEqual([])
  })
})

describe('the gate is live', () => {
  it('fails once a ported rule is deleted', () => {
    const [ported] = REQUIRED
    const damaged = classSelectors(withoutRulesFor(APP_CSS, ported))
    expect(damaged.has(ported)).toBe(false)
  })

  it('fails for a sample across the whole required set', () => {
    // Sampled at a stride rather than exhaustively: the regex rebuild is the
    // expensive part and five hundred of them turns a fast gate into a slow one.
    const sample = REQUIRED.filter((_, index) => index % 37 === 0)
    expect(sample.length).toBeGreaterThan(5)
    for (const name of sample) {
      const damaged = classSelectors(withoutRulesFor(APP_CSS, name))
      expect(damaged.has(name), `${name} survived deletion`).toBe(false)
    }
  })
})
