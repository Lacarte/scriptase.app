import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ProviderSettingsForm from '../components/ProviderSettingsForm.vue'
import { api } from '@/shared/api/client.js'
import { clearOptionSourceCache } from '@/shared/composables/useOptionSources.js'

// Step 12.2 — every field, widget, label, option list, and visibility rule is
// read from the provider's own settings schema (contracts.md §22). A fixture
// schema below exercises the whole frozen widget vocabulary; no provider id
// appears in the component, so these fixtures are deliberately made up.

const FIXTURE_SCHEMA = {
  type: 'object',
  properties: {
    api_key: { type: 'string', label: 'API Key', ui: { type: 'password' } },
    plain_text: { type: 'string', label: 'Plain', description: 'Some help' },
    notes: { type: 'string', label: 'Notes', ui: { type: 'textarea' } },
    model: {
      type: 'string',
      label: 'Model',
      default: 'small',
      ui: { type: 'dropdown', options: ['small', { value: 'large', label: 'Large' }] },
    },
    region: { type: 'string', label: 'Region', ui: { type: 'select', options: ['eu'] } },
    speed: {
      type: 'number', label: 'Speed', default: 1, minimum: 0.5, maximum: 2,
      multipleOf: 0.1, ui: { type: 'slider' },
    },
    retries: { type: 'integer', label: 'Retries', default: 3 },
    blend: { type: 'boolean', label: 'Blend', default: false, ui: { type: 'toggle' } },
    implicit_flag: { type: 'boolean', label: 'Implicit' },
    from_the_future: { type: 'string', label: 'Future', ui: { type: 'hologram' } },
  },
  required: ['api_key', 'model'],
}

const CONDITIONAL_SCHEMA = {
  type: 'object',
  properties: {
    mode: { type: 'string', label: 'Mode', default: 'basic', ui: { type: 'dropdown', options: ['basic', 'advanced'] } },
    tuning: { type: 'string', label: 'Tuning', ui: { show_if: { mode: ['advanced'] } } },
    both: {
      type: 'string',
      label: 'Both',
      ui: { show_if: { mode: ['advanced'], blend: [true] } },
    },
    blend: { type: 'boolean', label: 'Blend', ui: { type: 'toggle' } },
  },
  required: [],
}

function mountForm(props = {}) {
  return mount(ProviderSettingsForm, {
    props: {
      modelValue: {},
      schema: FIXTURE_SCHEMA,
      errors: [],
      domain: 'demo',
      providerId: 'alpha',
      ...props,
    },
  })
}

function labels(wrapper) {
  return wrapper.findAll('.field-label').map((el) => el.text().replace('*', '').trim())
}

describe('provider settings renderer', () => {
  beforeEach(() => clearOptionSourceCache())
  afterEach(() => vi.restoreAllMocks())

  // ── The frozen widget vocabulary (§22.2) ───────────────────────────────

  it('renders every supported widget from schema metadata alone', () => {
    const wrapper = mountForm()

    expect(wrapper.find('#field-api_key').exists() || wrapper.find('.secret-stored').exists()).toBe(true)
    expect(wrapper.find('#field-plain_text').attributes('type')).toBe('text')
    expect(wrapper.find('#field-notes').element.tagName).toBe('TEXTAREA')
    expect(wrapper.find('#field-model').element.tagName).toBe('SELECT')
    expect(wrapper.find('#field-region').element.tagName).toBe('SELECT')
    expect(wrapper.find('#field-speed').attributes('type')).toBe('range')
    expect(wrapper.find('#field-retries').attributes('type')).toBe('number')
    expect(wrapper.find('#field-blend').attributes('type')).toBe('checkbox')
  })

  it('falls back to a widget the JSON type can actually hold', () => {
    // No `ui.type`: a boolean gets a checkbox, because a text input can only
    // ever produce a string and the server rejects that for a boolean.
    const wrapper = mountForm()
    expect(wrapper.find('#field-implicit_flag').attributes('type')).toBe('checkbox')
    expect(wrapper.find('#field-retries').attributes('type')).toBe('number')
  })

  it('renders an unknown widget as text with a warning, never an error', () => {
    const wrapper = mountForm()
    expect(wrapper.find('#field-from_the_future').attributes('type')).toBe('text')
    expect(wrapper.text()).toContain('does not recognize the widget')
  })

  it('marks only the schema-required fields', () => {
    const wrapper = mountForm()
    const required = wrapper
      .findAll('.field-label')
      .filter((el) => el.find('.required-badge').exists())
      .map((el) => el.text().replace('*', '').trim())
    // `plain_text` is not required; a password is not required by being secret.
    expect(required).toEqual(['API Key', 'Model'])
  })

  it('renders labels, descriptions, and dropdown options from metadata', () => {
    const wrapper = mountForm()
    expect(labels(wrapper)).toContain('Plain')
    expect(wrapper.text()).toContain('Some help')
    expect(wrapper.find('#field-model').findAll('option').map((o) => o.text()))
      .toEqual(['small', 'Large'])
  })

  it('keeps a stored value visible when the provider no longer offers it', () => {
    const wrapper = mountForm({ modelValue: { model: 'retired' } })
    expect(wrapper.find('#field-model').findAll('option').map((o) => o.text()))
      .toEqual(['retired (unavailable)', 'small', 'Large'])
  })

  it('emits the typed value with the right primitive type', async () => {
    const wrapper = mountForm()

    await wrapper.find('#field-plain_text').setValue('hello')
    await wrapper.find('#field-blend').setValue(true)
    await wrapper.find('#field-retries').setValue('7')

    const emitted = wrapper.emitted('update:modelValue')
    expect(emitted[0][0].plain_text).toBe('hello')
    expect(emitted[1][0].blend).toBe(true)
    expect(emitted[2][0].retries).toBe(7)
  })

  // ── Conditional visibility (§22.3) ─────────────────────────────────────

  it('hides a field whose show_if does not hold', async () => {
    const wrapper = mount(ProviderSettingsForm, {
      props: { modelValue: { mode: 'basic' }, schema: CONDITIONAL_SCHEMA, errors: [] },
    })
    expect(labels(wrapper)).not.toContain('Tuning')

    await wrapper.setProps({ modelValue: { mode: 'advanced' } })
    expect(labels(wrapper)).toContain('Tuning')
  })

  it('ANDs across show_if keys', async () => {
    const wrapper = mount(ProviderSettingsForm, {
      props: {
        modelValue: { mode: 'advanced', blend: false },
        schema: CONDITIONAL_SCHEMA,
        errors: [],
      },
    })
    expect(labels(wrapper)).not.toContain('Both')

    await wrapper.setProps({ modelValue: { mode: 'advanced', blend: true } })
    expect(labels(wrapper)).toContain('Both')
  })

  // ── Secrets are write-only (§22.6) ─────────────────────────────────────

  it('shows a stored secret as hidden and never as its value', () => {
    const wrapper = mountForm({ modelValue: { api_key: '***' } })
    expect(wrapper.find('.secret-stored').text()).toContain('Saved')
    expect(wrapper.find('#field-api_key').exists()).toBe(false)
    expect(wrapper.html()).not.toContain('value="***"')
  })

  it('only sends a secret once it is explicitly replaced', async () => {
    const wrapper = mountForm({ modelValue: { api_key: '***' } })

    await wrapper.find('.link-btn').trigger('click')
    expect(wrapper.emitted('update:modelValue')[0][0].api_key).toBe('')

    await wrapper.setProps({ modelValue: { api_key: '' } })
    await wrapper.find('#field-api_key').setValue('new-secret')
    expect(wrapper.emitted('update:modelValue')[1][0].api_key).toBe('new-secret')
  })

  it('restores the sentinel when the replacement is abandoned', async () => {
    const wrapper = mountForm({ modelValue: { api_key: '***' } })
    await wrapper.find('.link-btn').trigger('click')
    await wrapper.setProps({ modelValue: { api_key: '' } })

    await wrapper.find('.link-btn').trigger('click')
    const last = wrapper.emitted('update:modelValue').at(-1)[0]
    expect(last.api_key).toBe('***')
  })

  it('treats a secret by key name even without a password widget', () => {
    const wrapper = mount(ProviderSettingsForm, {
      props: {
        modelValue: { webhook_token: '***' },
        schema: { type: 'object', properties: { webhook_token: { type: 'string' } } },
        errors: [],
      },
    })
    expect(wrapper.find('.secret-stored').exists()).toBe(true)
  })

  // ── Async option sources (§22.4 + §23) ─────────────────────────────────

  it('resolves ui.options_source against its own provider', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({
      source: 'fixture_voices',
      context: { domain: 'demo', provider: 'alpha' },
      options: [{ value: 'alpha_one', label: 'Alpha One' }],
    })

    const wrapper = mountForm({
      schema: {
        type: 'object',
        properties: {
          voice: { type: 'string', label: 'Voice', ui: { options_source: 'fixture_voices' } },
        },
      },
    })
    await flushPromises()

    expect(api.get).toHaveBeenCalledWith(
      '/api/workflow/options/fixture_voices?domain=demo&provider=alpha',
    )
    expect(wrapper.find('#field-voice').findAll('option').map((o) => o.text()))
      .toEqual(['Alpha One'])
  })

  it('lets options_source win over static options', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ options: [{ value: 'live', label: 'Live' }] })

    const wrapper = mountForm({
      schema: {
        type: 'object',
        properties: {
          voice: {
            type: 'string',
            label: 'Voice',
            ui: { type: 'dropdown', options: ['stale'], options_source: 'fixture_voices' },
          },
        },
      },
    })
    await flushPromises()

    expect(wrapper.find('#field-voice').findAll('option').map((o) => o.text())).toEqual(['Live'])
  })

  it('surfaces an option-source failure in the standard envelope', async () => {
    vi.spyOn(api, 'get').mockRejectedValue(
      Object.assign(new Error('Provider offline'), { code: 'PROVIDER_UNAVAILABLE' }),
    )

    const wrapper = mountForm({
      schema: {
        type: 'object',
        properties: {
          voice: { type: 'string', label: 'Voice', ui: { options_source: 'fixture_voices' } },
        },
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('Provider offline [PROVIDER_UNAVAILABLE]')
  })

  // ── Validation feedback (§22.5) ────────────────────────────────────────

  it('renders each issue against its field with its severity', () => {
    const wrapper = mountForm({
      errors: [
        { field: 'api_key', severity: 'error', message: 'API Key is required' },
        { field: 'plain_text', severity: 'warning', message: 'Looks odd' },
      ],
    })
    expect(wrapper.find('.issue-message.error').text()).toBe('API Key is required')
    expect(wrapper.find('.issue-message.warning').text()).toBe('Looks odd')
  })

  it('surfaces issues about keys the schema no longer declares', () => {
    // The value is preserved server-side; silence would hide it entirely.
    const wrapper = mountForm({
      errors: [{ field: 'legacy_key', severity: 'warning', message: 'Unknown setting' }],
    })
    expect(wrapper.text()).toContain('Unknown setting')
  })
})
