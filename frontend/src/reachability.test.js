/**
 * Step 9.6 — the reachability guard.
 *
 * 8,267 lines went unreachable and stayed that way for eight phases while
 * every suite was green. Nothing measured it, so nothing reported it.
 *
 * This test walks imports from main.js and fails when a source file under
 * src/ cannot be reached. Tests are excluded from the graph deliberately:
 * a module reachable only from its own test is dead product code with a
 * test keeping it alive, which is the exact condition this guard exists to
 * catch.
 */
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { dirname, extname, join, relative, resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

const SRC = resolve(process.cwd(), 'src')
const ENTRY = join(SRC, 'main.js')
const SOURCE_EXTS = new Set(['.js', '.vue'])

// ---------------------------------------------------------------------------
// Enumerate source files
// ---------------------------------------------------------------------------

/** True for test files: *.test.js, *.spec.js, or anything inside __tests__/. */
function isTestFile(absPath) {
  const rel = relative(SRC, absPath).replace(/\\/g, '/')
  if (rel.includes('__tests__/')) return true
  return /\.(test|spec)\.[jt]sx?$/.test(rel.split('/').pop())
}

/** All .js and .vue files under src/ that are not test infrastructure. */
function enumerateSourceFiles(dir) {
  const result = []
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) {
      if (entry.name === 'node_modules') continue
      result.push(...enumerateSourceFiles(full))
    } else if (entry.isFile() && SOURCE_EXTS.has(extname(entry.name))) {
      if (!isTestFile(full)) result.push(resolve(full))
    }
  }
  return result
}

// ---------------------------------------------------------------------------
// Import graph walk
// ---------------------------------------------------------------------------

/** Extract every <script> / <script setup> block from a Vue SFC. */
function extractScript(vue) {
  const blocks = []
  for (const m of vue.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)) {
    blocks.push(m[1])
  }
  return blocks.join('\n')
}

/** Strip JS comments so commented-out imports are not followed. */
function stripComments(code) {
  return code
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\/\/.*$/gm, '')
}

/** Return every import/export specifier that points at a local module. */
function extractSpecifiers(code) {
  const clean = stripComments(code)
  const specs = new Set()
  for (const line of clean.split('\n')) {
    // import/export ... from '...'  (handles multi-line destructured imports
    // because the `from '...'` always lands on its own line)
    let m = line.match(/\bfrom\s+['"]([^'"]+)['"]/)
    if (m) { specs.add(m[1]); continue }

    // Side-effect import: import '...'
    m = line.match(/^\s*import\s+['"]([^'"]+)['"]/)
    if (m) { specs.add(m[1]); continue }

    // Dynamic import: import('...')
    for (const d of line.matchAll(/import\(\s*['"]([^'"]+)['"]\s*\)/g)) {
      specs.add(d[1])
    }
  }
  // Only follow local paths and the @/ alias; skip bare specifiers (npm).
  return [...specs].filter(s => s.startsWith('.') || s.startsWith('@/'))
}

/** Resolve a specifier to an absolute source-file path, or null. */
function resolveSpecifier(specifier, fromFile) {
  let base
  if (specifier.startsWith('@/')) {
    base = SRC
    specifier = specifier.slice(2)
  } else {
    base = dirname(fromFile)
  }

  const direct = resolve(base, specifier)

  // Exact path with a recognised extension
  if (existsSync(direct) && statSync(direct).isFile()) {
    return SOURCE_EXTS.has(extname(direct)) ? direct : null
  }

  // Try each source extension
  for (const ext of SOURCE_EXTS) {
    const candidate = direct + ext
    if (existsSync(candidate)) return candidate
  }

  // Try index files inside a directory
  if (existsSync(direct) && statSync(direct).isDirectory()) {
    for (const ext of SOURCE_EXTS) {
      const candidate = join(direct, 'index' + ext)
      if (existsSync(candidate)) return candidate
    }
  }

  return null
}

/**
 * BFS from entry, following every import. Returns the set of normalised
 * absolute paths reachable from the entry point (test files excluded).
 */
function walkImports(entry) {
  const visited = new Set()
  const queue = [resolve(entry)]

  while (queue.length > 0) {
    const file = queue.shift()
    if (visited.has(file)) continue
    visited.add(file)

    const raw = readFileSync(file, 'utf8')
    const code = extname(file) === '.vue' ? extractScript(raw) : raw

    for (const spec of extractSpecifiers(code)) {
      const resolved = resolveSpecifier(spec, file)
      if (resolved && !visited.has(resolved) && !isTestFile(resolved)) {
        queue.push(resolved)
      }
    }
  }

  return visited
}

// ---------------------------------------------------------------------------
// The test
// ---------------------------------------------------------------------------

function rel(absPath) {
  return relative(SRC, absPath).replace(/\\/g, '/')
}

describe('reachability guard', () => {
  it('every source file is reachable from main.js', () => {
    const allSources = new Set(enumerateSourceFiles(SRC))
    const reachable = walkImports(ENTRY)

    const unreachable = [...allSources]
      .filter(f => !reachable.has(f))
      .map(rel)
      .sort()

    expect(
      unreachable,
      [
        `${unreachable.length} source file(s) unreachable from main.js:`,
        ...unreachable.map(n => `  ${n}`),
      ].join('\n'),
    ).toEqual([])
  })
})
