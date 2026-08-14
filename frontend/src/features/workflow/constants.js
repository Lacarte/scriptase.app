// MIME type carried by palette drags (contracts: dataTransfer carries the node type).
export const DRAG_MIME = 'application/x-sts-node-type'

// Handle colors by port type (control is intentionally muted).
export const PORT_COLORS = {
  control: '#6B7280',
  text: '#D1D5DB',
  script: '#4ECDC4',
  project_id: '#9CA3AF',
  project_settings: '#F59E0B',
  audio_file: '#A78BFA',
  tts_metadata: '#C4B5FD',
  alignment: '#60A5FA',
  segments: '#93C5FD',
  scenes: '#F472B6',
  image_prompts: '#F9A8D4',
  storyboard_images: '#FBBF24',
  animation_assets: '#FCD34D',
  captions: '#34D399',
  music_track: '#6EE7B7',
  editor_project: '#F87171',
  export_profile: '#FCA5A5',
  video_file: '#EF4444',
  generic_json: '#E5E7EB',
  dynamic: '#E5E7EB',
}
