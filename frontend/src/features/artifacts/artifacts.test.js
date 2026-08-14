import { describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

import {
  INPUT_SOURCES,
  bindingsForNode,
  makeBinding,
} from './api.js'
import AttemptHistory from './components/AttemptHistory.vue'
import * as artifactsApi from './api.js'

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

  it('defaults sample bindings with a port_type for Test Node', () => {
    expect(makeBinding('sample', { port_type: 'scenes' })).toEqual({
      source: 'sample',
      port_type: 'scenes',
    })
  })
})

describe('AttemptHistory (step 4.3)', () => {
  it('renders regenerated scene image versions side by side with generation axes', async () => {
    const history = {
      job_id: 'job_IMG001',
      scene_id: 'scn_AAAAAA',
      kind: 'image',
      attempt_count: 2,
      attempts: [
        {
          artifact_id: 'art_AAAAAA',
          version: 1,
          provider_instance_id: 'wavespeed_main',
          seed: 42,
          prompt_revision: 'flux-dev@2026-01',
          is_superseded: true,
          path: 'storyboard/job_IMG001/scn_AAAAAA_v1.png',
        },
        {
          artifact_id: 'art_BBBBBB',
          version: 2,
          provider_instance_id: 'wavespeed_fallback',
          seed: 99,
          prompt_revision: 'flux-dev@2026-03',
          is_superseded: false,
          path: 'storyboard/job_IMG001/scn_AAAAAA_v2.png',
        },
      ],
      comparison: {
        left: {
          artifact_id: 'art_AAAAAA',
          version: 1,
          provider_instance_id: 'wavespeed_main',
          seed: 42,
          prompt_revision: 'flux-dev@2026-01',
          path: 'storyboard/job_IMG001/scn_AAAAAA_v1.png',
        },
        right: {
          artifact_id: 'art_BBBBBB',
          version: 2,
          provider_instance_id: 'wavespeed_fallback',
          seed: 99,
          prompt_revision: 'flux-dev@2026-03',
          path: 'storyboard/job_IMG001/scn_AAAAAA_v2.png',
        },
        same_chain: true,
        axes: {
          provider_instance_id: {
            left: 'wavespeed_main',
            right: 'wavespeed_fallback',
            changed: true,
          },
          seed: { left: 42, right: 99, changed: true },
          prompt_revision: {
            left: 'flux-dev@2026-01',
            right: 'flux-dev@2026-03',
            changed: true,
          },
        },
        changed_axes: ['provider_instance_id', 'seed', 'prompt_revision'],
      },
    }

    const wrapper = mount(AttemptHistory, {
      props: { history },
    })
    await flushPromises()

    const text = wrapper.text()
    expect(wrapper.find('[data-testid="attempt-history"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="version-comparison"]').exists()).toBe(true)
    expect(text).toContain('v1')
    expect(text).toContain('v2')
    expect(text).toContain('wavespeed_main')
    expect(text).toContain('wavespeed_fallback')
    expect(text).toContain('42')
    expect(text).toContain('99')
    expect(text).toContain('flux-dev@2026-01')
    expect(text).toContain('flux-dev@2026-03')
    expect(text).toContain('Side-by-side comparison')
  })

  it('loads chain history from the API when jobId + kind are set', async () => {
    const spy = vi.spyOn(artifactsApi, 'getChainHistory').mockResolvedValue({
      attempt_count: 1,
      attempts: [
        {
          artifact_id: 'art_CCCCCC',
          version: 1,
          provider_instance_id: 'inst_a',
          seed: 1,
          prompt_revision: 'r1',
          is_superseded: false,
          path: 'storyboard/x.png',
        },
      ],
      comparison: null,
    })

    const wrapper = mount(AttemptHistory, {
      props: { jobId: 'job_X', kind: 'image', sceneId: 'scn_ZZZZZZ' },
    })
    await flushPromises()

    expect(spy).toHaveBeenCalledWith({
      jobId: 'job_X',
      kind: 'image',
      sceneId: 'scn_ZZZZZZ',
    })
    expect(wrapper.text()).toContain('inst_a')
    expect(wrapper.text()).toContain('r1')
    spy.mockRestore()
  })
})
