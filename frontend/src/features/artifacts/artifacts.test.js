import { describe, expect, it } from 'vitest'
import {
  INPUT_SOURCES,
  bindingsForNode,
  makeBinding,
} from './api.js'

describe('artifacts input picker helpers (step 4.1)', () => {
  it('exposes the §9.1 source vocabulary', () => {
    expect(INPUT_SOURCES).toEqual([
      'current_job',
      'job',
      'library',
      'upload',
      'manual',
      'sample',
      'run_deps',
    ])
  })

  it('builds a library binding with artifact id', () => {
    expect(makeBinding('library', { artifact_id: 'art_ABCDEF' })).toEqual({
      source: 'library',
      artifact_id: 'art_ABCDEF',
    })
  })

  it('nests port bindings under a node id for the run body', () => {
    const body = bindingsForNode('n_animator', {
      scenes: makeBinding('job', {
        job_id: 'job_OTHER1',
        artifact_id: 'art_SCENE1',
      }),
      storyboard: makeBinding('library', { artifact_id: 'art_IMAGE1' }),
    })
    expect(body).toEqual({
      n_animator: {
        scenes: {
          source: 'job',
          job_id: 'job_OTHER1',
          artifact_id: 'art_SCENE1',
        },
        storyboard: {
          source: 'library',
          artifact_id: 'art_IMAGE1',
        },
      },
    })
  })
})
