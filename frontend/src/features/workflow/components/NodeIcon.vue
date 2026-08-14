<script setup>
defineProps({ icon: { type: String, default: '' } })

// Minimal inline icon set keyed by registry icon names.
const PATHS = {
  play: 'M8 5.14v13.72L19 12 8 5.14z',
  briefcase: 'M4 7h16v13H4zM8 7V4h8v3',
  'file-text': 'M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-6-6zM14 2v6h6M8 13h8M8 17h5',
  'folder-open': 'M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v1H5.2L3 19V7zM3 19l2.5-8h16L19 19H3z',
  mic: 'M12 1a3 3 0 00-3 3v8a3 3 0 006 0V4a3 3 0 00-3-3zM19 10v2a7 7 0 01-14 0v-2M12 19v4',
  clock: 'M12 22a10 10 0 100-20 10 10 0 000 20zM12 6v6l4 2',
  scissors: 'M6 9a3 3 0 100-6 3 3 0 000 6zM6 21a3 3 0 100-6 3 3 0 000 6zM20 4L8.12 15.88M14.47 14.48L20 20M8.12 8.12L12 12',
  film: 'M4 11v8a2 2 0 002 2h12a2 2 0 002-2v-8M4 11V7a2 2 0 012-2h12a2 2 0 012 2v4M4 11h16',
  grid: 'M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z',
  image: 'M3 3h18v18H3zM8.5 10a1.5 1.5 0 100-3 1.5 1.5 0 000 3zM21 15l-5-5L5 21',
  type: 'M4 7V4h16v3M9 20h6M12 4v16',
  music: 'M9 18V5l12-2v13M9 18a3 3 0 11-6 0 3 3 0 016 0zM21 16a3 3 0 11-6 0 3 3 0 016 0z',
  layers: 'M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5',
  sliders: 'M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6',
  download: 'M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3',
  flag: 'M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1v18',
  flask: 'M10 2v6L4 20a1.5 1.5 0 001.4 2h13.2A1.5 1.5 0 0020 20L14 8V2M8 2h8',
  eye: 'M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8zM12 15a3 3 0 100-6 3 3 0 000 6z',
}
</script>

<template>
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
       stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <path :d="PATHS[icon] || 'M4 4h16v16H4z'" />
  </svg>
</template>
