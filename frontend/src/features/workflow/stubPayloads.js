/**
 * Per-port-type validation for editable Sample Input payloads (step 2.5).
 * Mirrors the structural rules of studio/workflows/sample_data.py so the
 * inspector can flag broken sample data live; the server stays authoritative
 * (it additionally verifies that fixture references actually exist).
 */

const PROJECT_ID_RE = /^p[pm]_[A-Za-z0-9]{6}$/

function isFinite_(value) {
  return typeof value === 'number' && Number.isFinite(value)
}

function isInt(value) {
  return Number.isInteger(value)
}

function isObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

/**
 * File references inside sample payloads must stay inside the bundled
 * fixture folder: relative, no drive letters, no parent traversal.
 * (Existence is checked server-side — the browser has no fixture list.)
 */
function refError(ref, label) {
  if (typeof ref !== 'string' || !ref.trim()) {
    return `${label} must be a non-empty fixture-relative path`
  }
  const normalized = ref.replace(/\\/g, '/')
  if (
    normalized.startsWith('/')
    || normalized.startsWith('~')
    || /^[A-Za-z]:/.test(normalized)
    || normalized.split('/').includes('..')
  ) {
    return `${label} must stay inside the bundled sample fixtures`
  }
  return null
}

function checkRef(ref, label, problems) {
  const message = refError(ref, label)
  if (message) problems.push(message)
}

function checkArtifactRefs(payload, problems) {
  const refs = payload.artifact_refs
  if (refs === undefined) return
  if (!Array.isArray(refs)) {
    problems.push('artifact_refs must be a list of fixture-relative paths')
    return
  }
  refs.forEach((ref, index) => checkRef(ref, `artifact_refs[${index}]`, problems))
}

function requireObject(payload, problems, typeName) {
  if (!isObject(payload)) {
    problems.push(`A ${typeName} payload must be a JSON object`)
    return false
  }
  return true
}

function validateString(payload, problems, label, maxLength = 10000) {
  if (typeof payload !== 'string' || !payload.trim()) {
    problems.push(`A ${label} payload must be a non-empty string`)
  } else if (payload.length > maxLength) {
    problems.push(`A ${label} payload must stay under ${maxLength} characters`)
  }
}

const VALIDATORS = {
  text: (payload, problems) => validateString(payload, problems, 'text'),
  script: (payload, problems) => validateString(payload, problems, 'script'),
  export_profile: (payload, problems) => validateString(payload, problems, 'export_profile', 80),

  project_id(payload, problems) {
    if (typeof payload !== 'string' || !PROJECT_ID_RE.test(payload)) {
      problems.push('A project_id payload must match pp_XXXXXX or pm_XXXXXX')
    }
  },

  project_settings(payload, problems) {
    if (!requireObject(payload, problems, 'project_settings')) return
    const logo = payload.logo
    if (logo !== undefined && logo !== null) {
      if (!isObject(logo)) problems.push('logo must be an object reference')
      else if (logo.path) checkRef(logo.path, 'logo.path', problems)
    }
  },

  audio_file(payload, problems) {
    if (!requireObject(payload, problems, 'audio_file')) return
    checkRef(payload.wav_path, 'wav_path', problems)
    if (!isFinite_(payload.duration_seconds) || payload.duration_seconds <= 0) {
      problems.push('duration_seconds must be a positive number')
    }
  },

  tts_metadata(payload, problems) {
    if (!requireObject(payload, problems, 'tts_metadata')) return
    for (const key of ['folder', 'filename']) {
      if (typeof payload[key] !== 'string' || !payload[key]) {
        problems.push(`${key} must be a non-empty string`)
      }
    }
    checkRef(payload.wav_path, 'wav_path', problems)
    if (!isFinite_(payload.duration_seconds) || payload.duration_seconds <= 0) {
      problems.push('duration_seconds must be a positive number')
    }
    if (!isInt(payload.words) || payload.words <= 0) {
      problems.push('words must be a positive integer')
    }
  },

  alignment(payload, problems) {
    if (!requireObject(payload, problems, 'alignment')) return
    if (typeof payload.transcript !== 'string' || !payload.transcript.trim()) {
      problems.push('transcript must be a non-empty string')
    }
    const words = payload.alignment
    if (!Array.isArray(words) || !words.length) {
      problems.push('alignment must be a non-empty list of timed words')
      return
    }
    let previousBegin = -Infinity
    for (let i = 0; i < words.length; i += 1) {
      const word = words[i]
      if (!isObject(word) || typeof word.word !== 'string') {
        problems.push(`alignment[${i}] must be {word, begin, end}`)
        return
      }
      if (!isFinite_(word.begin) || !isFinite_(word.end) || word.begin < 0 || word.end < word.begin) {
        problems.push(`alignment[${i}] has invalid word timings`)
        return
      }
      if (word.begin < previousBegin) {
        problems.push('alignment words must be ordered by start time')
        return
      }
      previousBegin = word.begin
    }
  },

  segments(payload, problems) {
    if (!requireObject(payload, problems, 'segments')) return
    const segments = payload.segments
    if (!Array.isArray(segments) || !segments.length) {
      problems.push('segments must be a non-empty list')
      return
    }
    let previousEnd = -Infinity
    for (let i = 0; i < segments.length; i += 1) {
      const segment = segments[i]
      if (!isObject(segment)) {
        problems.push(`segments[${i}] must be an object`)
        return
      }
      if (!isFinite_(segment.start) || !isFinite_(segment.end)
        || segment.start < 0 || segment.end < segment.start) {
        problems.push(`segments[${i}] has invalid start/end times`)
        return
      }
      if (segment.start < previousEnd - 1e-6) {
        problems.push('segments must be ordered and non-overlapping')
        return
      }
      if (typeof segment.words !== 'string') {
        problems.push(`segments[${i}].words must be a string`)
        return
      }
      previousEnd = segment.end
    }
  },

  scenes(payload, problems) {
    if (!requireObject(payload, problems, 'scenes')) return
    const scenes = payload.scenes
    if (!Array.isArray(scenes) || !scenes.length) {
      problems.push('scenes must be a non-empty list')
      return
    }
    const seen = new Set()
    for (let i = 0; i < scenes.length; i += 1) {
      const scene = scenes[i]
      if (!isObject(scene)) {
        problems.push(`scenes[${i}] must be an object`)
        return
      }
      if (!isInt(scene.index) || seen.has(scene.index)) {
        problems.push('every scene needs a stable unique integer index')
        return
      }
      seen.add(scene.index)
      if (typeof scene.image_prompt !== 'string' || !scene.image_prompt.trim()) {
        problems.push(`scenes[${i}].image_prompt must be a non-empty string`)
        return
      }
    }
  },

  image_prompts(payload, problems) {
    if (!requireObject(payload, problems, 'image_prompts')) return
    const prompts = payload.prompts
    if (!Array.isArray(prompts) || !prompts.length) {
      problems.push('prompts must be a non-empty list')
      return
    }
    for (let i = 0; i < prompts.length; i += 1) {
      const item = prompts[i]
      if (!isObject(item) || !isInt(item.index)
        || typeof item.image_prompt !== 'string' || !item.image_prompt.trim()) {
        problems.push(`prompts[${i}] must be {index, image_prompt}`)
        return
      }
    }
  },

  storyboard_images(payload, problems) {
    if (!requireObject(payload, problems, 'storyboard_images')) return
    const counts = readCounts(payload, problems, 'storyboard_images')
    const statuses = payload.scene_statuses
    if (!isObject(statuses)) {
      problems.push('scene_statuses must be an object keyed by scene')
      return
    }
    let readySeen = 0
    let errorSeen = 0
    for (const [key, status] of Object.entries(statuses)) {
      if (!isObject(status) || typeof status.status !== 'string') {
        problems.push(`scene_statuses[${key}] must carry a status string`)
        return
      }
      if (status.status === 'ready') {
        readySeen += 1
        if ('local_path' in status) {
          checkRef(status.local_path, `scene_statuses[${key}].local_path`, problems)
        }
      } else if (status.status === 'error') {
        errorSeen += 1
      }
    }
    if (counts) {
      const [total, ready, errors] = counts
      if (Object.keys(statuses).length !== total || readySeen !== ready || errorSeen !== errors) {
        problems.push('storyboard counts must match the listed scene statuses')
      }
    }
  },

  animation_assets(payload, problems) {
    if (!requireObject(payload, problems, 'animation_assets')) return
    const counts = readCounts(payload, problems, 'animation_assets')
    const scenes = payload.scenes
    if (!isObject(scenes) || !Object.keys(scenes).length) {
      problems.push('scenes must be a non-empty object keyed by scene')
      return
    }
    let readySeen = 0
    for (const [key, scene] of Object.entries(scenes)) {
      if (!isObject(scene) || !Array.isArray(scene.local_files)) {
        problems.push(`scenes[${key}] must carry a local_files list`)
        return
      }
      if (scene.local_files.length) readySeen += 1
      scene.local_files.forEach(
        (ref, index) => checkRef(ref, `scenes[${key}].local_files[${index}]`, problems),
      )
    }
    if (counts) {
      const [total, ready] = counts
      if (Object.keys(scenes).length !== total || readySeen !== ready) {
        problems.push('animation asset counts must match the listed scenes')
      }
    }
  },

  captions(payload, problems) {
    if (!requireObject(payload, problems, 'captions')) return
    const captions = payload.captions
    if (!Array.isArray(captions) || !captions.length) {
      problems.push('captions must be a non-empty list')
      return
    }
    let previousStart = -Infinity
    for (let i = 0; i < captions.length; i += 1) {
      const caption = captions[i]
      if (!isObject(caption) || typeof caption.text !== 'string') {
        problems.push(`captions[${i}] must carry a text string`)
        return
      }
      if (!isFinite_(caption.start) || !isFinite_(caption.end)
        || caption.start < 0 || caption.end < caption.start) {
        problems.push(`captions[${i}] has invalid timings`)
        return
      }
      if (caption.start < previousStart) {
        problems.push('captions must be ordered by start time')
        return
      }
      previousStart = caption.start
    }
  },

  music_track(payload, problems) {
    if (!requireObject(payload, problems, 'music_track')) return
    checkRef(payload.track_ref, 'track_ref', problems)
    if (!isFinite_(payload.volume) || payload.volume < 0 || payload.volume > 1) {
      problems.push('volume must be a number between 0 and 1')
    }
  },

  editor_project(payload, problems) {
    if (!requireObject(payload, problems, 'editor_project')) return
    if (typeof payload.project_id !== 'string' || !payload.project_id) {
      problems.push('project_id must be a non-empty string')
    }
    const scenes = payload.scenes
    if (!Array.isArray(scenes) || !scenes.length) {
      problems.push('scenes must be a non-empty list')
      return
    }
    if (payload.scene_count !== scenes.length) {
      problems.push('scene_count must match the scenes list')
    }
    if (!isFinite_(payload.total_duration) || payload.total_duration <= 0) {
      problems.push('total_duration must be a positive number')
    }
    scenes.forEach((scene, index) => {
      if (!isObject(scene)) problems.push(`scenes[${index}] must be an object`)
      else if (scene.mediaUrl) checkRef(scene.mediaUrl, `scenes[${index}].mediaUrl`, problems)
    })
    ;(payload.audio_tracks || []).forEach((track, index) => {
      if (isObject(track) && track.path) {
        checkRef(track.path, `audio_tracks[${index}].path`, problems)
      }
    })
  },

  video_file(payload, problems) {
    if (!requireObject(payload, problems, 'video_file')) return
    checkRef(payload.path, 'path', problems)
  },

  generic_json(payload, problems) {
    if (payload === null || payload === undefined) {
      problems.push('A generic_json payload cannot be null')
    }
  },
}

function readCounts(payload, problems, typeName) {
  const values = []
  for (const key of ['total', 'ready', 'errors']) {
    const value = payload[key]
    if (!isInt(value) || value < 0) {
      problems.push(`${typeName}.${key} must be a non-negative integer`)
      return null
    }
    values.push(value)
  }
  const [total, ready, errors] = values
  if (ready + errors > total) {
    problems.push(`${typeName} ready+errors cannot exceed total`)
    return null
  }
  return values
}

/**
 * @returns {string[]} plain-language problems; empty == payload acceptable.
 */
export function validateStubPayload(portType, payload) {
  const validator = VALIDATORS[portType]
  if (!validator) return [`Unsupported sample data type: ${portType}`]
  const problems = []
  validator(payload, problems)
  if (isObject(payload)) checkArtifactRefs(payload, problems)
  return problems
}
