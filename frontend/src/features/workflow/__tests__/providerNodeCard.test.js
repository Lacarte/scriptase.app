import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import NodeCard from '../components/NodeCard.vue'
import { useWorkflowStore } from '../stores/workflow.js'
import { useProviderCatalogStore } from '@/features/providers/stores/providerCatalog.js'

/**
 * A provider-backed node card names the provider it will actually run.
 *
 * The subtitle used to repeat `display_name`, which the node label already
 * shows — so "Text to Speech / Text to Speech" told the user nothing, and the
 * one thing they could not see on the canvas was which provider each node was
 * pointed at.
 *
 * Every provider and domain below is invented. That is the assertion: the card
 * reads the domain off the node's own `provider` field and the label off the
 * catalog, so a new provider — or a whole new domain — needs no edit to
 * NodeCard.vue (contracts.md §26).
 */

vi.mock('@vue-flow/core', () => ({
  Handle: { name: 'Handle', props: ['id', 'type', 'position'], template: '<div />' },
  Position: { Left: 'left', Right: 'right' },
}))

const NODE_TYPES = {
  'widget.forge': {
    type_version: 1,
    display_name: 'Widget Forge',
    category: 'ai',
    icon: 'sparkles',
    inputs: [],
    outputs: [],
    config_schema: [
      {
        name: 'provider_id',
        label: 'Provider',
        type: 'provider',
        provider_domain: 'widget',
        default: 'forge_alpha',
      },
    ],
  },
  'plain.node': {
    type_version: 1,
    display_name: 'Plain Node',
    category: 'utility',
    icon: 'cog',
    inputs: [],
    outputs: [],
    config_schema: [{ name: 'mode', label: 'Mode', type: 'options', options: ['a', 'b'] }],
  },
}

const CATALOG = {
  widget: {
    selected: 'forge_beta',
    default_provider: 'forge_alpha',
    providers: [
      { id: 'forge_alpha', label: 'Forge Alpha', availability: 'available', aliases: [] },
      { id: 'forge_beta', label: 'Forge Beta', availability: 'available', aliases: ['beta-legacy'] },
    ],
  },
}

function mountCard(nodeId) {
  return mount(NodeCard, {
    props: { id: nodeId, data: { nodeType: nodeTypeOf(nodeId), label: labelOf(nodeId) }, selected: false },
  })
}

let store
let catalog

function nodeTypeOf(id) {
  return store.nodes.find((n) => n.id === id).type
}

function labelOf(id) {
  return store.nodes.find((n) => n.id === id).name
}

function seedNode(id, type, configuration = {}) {
  store.nodes.push({ id, type, type_version: 1, name: NODE_TYPES[type].display_name, position: { x: 0, y: 0 }, configuration })
}

beforeEach(() => {
  setActivePinia(createPinia())
  store = useWorkflowStore()
  catalog = useProviderCatalogStore()
  store.nodeTypes = NODE_TYPES
  store.categories = { ai: { label: 'AI', color: '#a78bfa' }, utility: { label: 'Utility', color: '#94a3b8' } }
  catalog.catalogVersion = 'test-catalog'
  catalog.domains = CATALOG
})

describe('provider-backed node cards', () => {
  it('shows the configured provider label instead of repeating the type name', () => {
    seedNode('n_1', 'widget.forge', { provider_id: 'forge_beta' })
    const card = mountCard('n_1')

    expect(card.text()).toContain('Forge Beta')
    expect(card.text()).not.toContain('Widget Forge / Widget Forge')
    expect(card.find('.node-provider').exists()).toBe(true)
  })

  it('resolves a provider referenced by a legacy alias', () => {
    seedNode('n_2', 'widget.forge', { provider_id: 'beta-legacy' })

    expect(mountCard('n_2').text()).toContain('Forge Beta')
  })

  it('falls back to the schema default when the node stores no provider', () => {
    seedNode('n_3', 'widget.forge', {})

    expect(mountCard('n_3').text()).toContain('Forge Alpha')
  })

  it('shows the raw id when the catalog does not know the provider', () => {
    seedNode('n_4', 'widget.forge', { provider_id: 'forge_from_the_future' })

    // Better a true-but-unpolished id than an empty subtitle while the
    // catalog is still loading, or after a provider folder is removed.
    expect(mountCard('n_4').text()).toContain('forge_from_the_future')
  })

  it('leaves nodes without a provider field showing their type name', () => {
    seedNode('n_5', 'plain.node', { mode: 'a' })
    const card = mountCard('n_5')

    expect(card.text()).toContain('Plain Node')
    expect(card.find('.node-provider').exists()).toBe(false)
  })

  it('re-renders when the provider changes despite the memoized card', async () => {
    seedNode('n_6', 'widget.forge', { provider_id: 'forge_alpha' })
    const card = mountCard('n_6')
    expect(card.text()).toContain('Forge Alpha')

    // v-memo omitting the subtitle would leave the stale label painted.
    store.nodes.find((n) => n.id === 'n_6').configuration.provider_id = 'forge_beta'
    await card.vm.$nextTick()

    expect(card.text()).toContain('Forge Beta')
    expect(card.text()).not.toContain('Forge Alpha')
  })
})
