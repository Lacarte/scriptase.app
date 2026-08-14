import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ConfigField from '../components/ConfigField.vue'
import { expressionOptions, expressionSyntaxError } from '../expressions.js'

describe('workflow expressions', () => {
  it('offers only upstream data outputs plus project and variables', () => {
    const nodes = [
      { id: 'source', name: 'Source', type: 'source' },
      { id: 'target', name: 'Target', type: 'target' },
      { id: 'later', name: 'Later', type: 'source' },
    ]
    const edges = [{ source_node: 'source', target_node: 'target' }]
    const types = {
      source: { outputs: [{ id: 'value', type: 'generic_json' }, { id: 'control', type: 'control' }] },
      target: { outputs: [] },
    }
    const options = expressionOptions(nodes[1], nodes, edges, types, { count: 2 })
    expect(options.map((option) => option.value)).toEqual(['{{ nodes.source.outputs.value }}'])
  })

  it('inserts an expression and renders a whole-value expression editor', async () => {
    const option = { value: '{{ nodes.source.outputs.value }}', label: 'Source · value' }
    const wrapper = mount(ConfigField, {
      props: {
        field: { name: 'delay', type: 'number', default: 1 },
        value: 1,
        expressionOptions: [option],
      },
    })
    await wrapper.get('[aria-label="Insert expression"]').setValue(option.value)
    expect(wrapper.emitted('update').at(-1)).toEqual([option.value])
    await wrapper.setProps({ value: option.value })
    expect(wrapper.get('.cfg-expression').element.value).toBe(option.value)
    expect(wrapper.find('input[type="number"]').exists()).toBe(false)
  })

  it('rejects interpolation and arbitrary access syntax', () => {
    expect(expressionSyntaxError('prefix {{ workflow.project_id }}')).toMatch(/whole-value/)
    expect(expressionSyntaxError('{{ env.PATH }}')).toMatch(/whole-value/)
    expect(expressionSyntaxError('{{ variables.safe }}')).toBe('')
  })
})
