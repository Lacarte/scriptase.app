import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { h } from 'vue'

import ArchiveCalendar from '@/shared/components/ArchiveCalendar.vue'

const NOW = Date.parse('2026-08-18T12:00:00Z')
const HOUR = 60 * 60 * 1000

function item(id, name, ageHours) {
  return { id, name, completed_at: new Date(NOW - ageHours * HOUR).toISOString() }
}

function mountCalendar(props = {}) {
  return mount(ArchiveCalendar, {
    props: {
      items: [
        item('recent', 'Fresh Cut', 3),
        item('old-one', 'Hidden History', 49),
        item('old-two', 'Second Archive', 48),
      ],
      now: NOW,
      noun: 'job',
      ...props,
    },
    slots: {
      item: ({ item: row, archived }) => h('div', {
        class: 'test-item',
        'data-id': row.id,
        'data-archived': String(archived),
      }, row.name),
    },
  })
}

describe('ArchiveCalendar', () => {
  it('keeps recent items full-size and packs items at least 48 hours old by date', () => {
    const wrapper = mountCalendar()

    expect(wrapper.find('[data-id="recent"]').exists()).toBe(true)
    expect(wrapper.find('[data-id="old-one"]').exists()).toBe(false)
    expect(wrapper.findAll('.cal-cell')).toHaveLength(1)
    expect(wrapper.find('.cal-count').text()).toBe('2')
  })

  it('reveals and hides every item on a clicked archive date', async () => {
    const wrapper = mountCalendar()

    await wrapper.find('.cal-cell').trigger('click')
    expect(wrapper.find('[data-id="old-one"]').attributes('data-archived')).toBe('true')
    expect(wrapper.find('[data-id="old-two"]').exists()).toBe(true)
    expect(wrapper.find('.cal-cell').attributes('aria-expanded')).toBe('true')

    await wrapper.find('.archive-day-head button').trigger('click')
    expect(wrapper.find('[data-id="old-one"]').exists()).toBe(false)
  })

  it('keeps the archive strip at the bottom when nothing is older than 48 hours', () => {
    const wrapper = mountCalendar({
      items: [item('recent', 'Fresh Cut', 3)],
    })
    expect(wrapper.find('.archive-strip').exists()).toBe(true)
    expect(wrapper.find('.ash-title').text()).toContain('Archive · 0 finished jobs')
    expect(wrapper.findAll('.cal-cell')).toHaveLength(0)
  })

  it('finds an archived item by name without opening its date first', async () => {
    const wrapper = mountCalendar({ searchQuery: 'hidden history' })

    expect(wrapper.find('.archive-strip').exists()).toBe(false)
    expect(wrapper.find('[data-id="old-one"]').exists()).toBe(true)
    expect(wrapper.find('[data-id="old-two"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('Found in archive · 1')
  })
})
