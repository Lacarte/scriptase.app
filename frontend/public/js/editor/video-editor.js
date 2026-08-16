/**
 * Video Editor - Stage 2
 * Receives staged timeline data from Stage 1 and provides video editing capabilities
 */

import { SCENE_COLORS, formatTimestamp, showToast } from './utils.js';
import { CanvasPreview } from './preview.js';
import { ExportAPI, EXPORT_PROFILES, prepareExportData, validateExportData } from './export-api.js';

// Export API instance
const exportAPI = new ExportAPI();

// Settings manager (iframe-local mirror of server JSON)
const STS = {
    _cache: {}, _defaults: {},
    get(key) {
        const v = this._cache[key];
        if (v !== undefined) return v;
        const ls = localStorage.getItem(key);
        if (ls !== null) return ls === 'true' ? true : ls === 'false' ? false : (isNaN(ls) ? ls : +ls);
        return this._defaults[key] ?? null;
    },
    set(key, value) {
        this._cache[key] = value;
        clearTimeout(this._saveTimer);
        this._saveTimer = setTimeout(() => {
            fetch('/api/settings', { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(this._cache) }).catch(() => {});
        }, 300);
    },
    _saveTimer: null,
};
// Init from server + app-config
Promise.all([
    fetch('/app-config.json').then(r => r.json()).catch(() => ({})),
    fetch('/api/settings').then(r => r.json()).catch(() => ({})),
]).then(([cfg, srv]) => {
    STS._defaults = cfg.defaults || {};
    STS._cache = { ...STS._defaults, ...srv };
});

/**
 * Format seconds to HH:MM:SS:MS timecode (e.g. 00:01:19:04)
 */
function formatTimecode(seconds) {
    if (isNaN(seconds) || seconds == null || seconds < 0) seconds = 0;
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    const ms = Math.floor((seconds % 1) * 100);
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}:${String(ms).padStart(2, '0')}`;
}

// Scene type icons - flat outline style SVG icons
const SCENE_ICONS = {
    hook: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><path d="M14 2v6h6"/><path d="M9 13h6M9 17h4"/>
    </svg>`,
    buildup: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <rect x="4" y="14" width="4" height="6" rx="1"/><rect x="10" y="10" width="4" height="10" rx="1"/><rect x="16" y="6" width="4" height="14" rx="1"/>
    </svg>`,
    text: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <path d="M6 4h12M12 4v16M8 20h8"/>
    </svg>`,
    peak: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <path d="M12 4l2.5 5h5.5l-4.5 3.5 1.7 5.5-5.2-3.5-5.2 3.5 1.7-5.5L4 9h5.5z"/>
    </svg>`,
    transition: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <path d="M5 12h14"/><path d="M13 6l6 6-6 6"/>
    </svg>`,
    cta: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <rect x="3" y="7" width="18" height="10" rx="2"/><path d="M9 12h6M12 9v6"/>
    </svg>`,
    speaker: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <circle cx="12" cy="8" r="4"/><path d="M5 20c0-4 3.5-6 7-6s7 2 7 6"/>
    </svg>`,
    final_statement: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <rect x="4" y="4" width="16" height="16" rx="2"/><path d="M8 12l3 3 5-6"/>
    </svg>`,
    default: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <rect x="4" y="4" width="16" height="16" rx="2"/><circle cx="9" cy="9" r="2"/><path d="M20 16l-5-5-7 9"/>
    </svg>`
};

// LocalStorage keys
const STORAGE_KEYS = {
    ZOOM_LEVEL: 'sts-editor-zoom',
    TIMELINE_HEIGHT: 'sts-editor-height',
    LOOP_STATE: 'sts-editor-loop',
    PROJECT_EDITS: 'sts-project-edits-',  // + projectId
    PROJECT_HISTORY: 'sts-project-history-'  // + projectId
};

// Maximum history entries per project
const MAX_HISTORY_ENTRIES = 50;

const LOCAL_CAPTION_PRESETS = {
    bold_popup: { font_family: 'Montserrat', font_size: 64, font_weight: '800', color: '#FFFFFF', stroke_color: 'none', stroke_width: 0, position_y: 65, animation: 'pop', text_transform: 'uppercase', shadow_color: '#000000', shadow_blur: 8, shadow_offset_x: 2, shadow_offset_y: 2 },
    popup_highlight: { font_family: 'Montserrat', font_size: 64, font_weight: '800', color: '#FFFFFF', stroke_color: 'none', stroke_width: 0, position_y: 75, animation: 'pop', text_transform: 'uppercase', shadow_color: '#000000', shadow_blur: 8, shadow_offset_x: 2, shadow_offset_y: 2, highlight: true, highlight_color: '#4ECDC4' },
    popup_highlight_box: { font_family: 'Montserrat', font_size: 64, font_weight: '800', color: '#FFFFFF', stroke_color: 'none', stroke_width: 0, position_y: 75, animation: 'pop', text_transform: 'uppercase', shadow_color: '#000000', shadow_blur: 8, shadow_offset_x: 2, shadow_offset_y: 2, highlight: true, highlight_mode: 'box', highlight_color: '#2563EB' },
    subtitle_bar: { font_family: 'Inter', font_size: 48, font_weight: '600', color: '#FFFFFF', stroke_color: 'none', stroke_width: 0, position_y: 85, animation: 'none', text_transform: 'none', bg_bar: true, shadow_color: '#000000', shadow_blur: 6, shadow_offset_x: 1, shadow_offset_y: 1 },
    karaoke: { font_family: 'Bebas Neue', font_size: 72, font_weight: '400', color: '#FFFFFF', stroke_color: 'none', stroke_width: 0, position_y: 70, animation: 'none', text_transform: 'uppercase', highlight: true, shadow_color: '#000000', shadow_blur: 10, shadow_offset_x: 2, shadow_offset_y: 2 },
    minimal: { font_family: 'DM Sans', font_size: 42, font_weight: '500', color: '#FFFFFF', stroke_color: 'none', stroke_width: 0, position_y: 80, animation: 'none', text_transform: 'none', shadow_color: '#000000', shadow_blur: 6, shadow_offset_x: 1, shadow_offset_y: 1 },
    focus_word_scale: { font_family: 'Montserrat', font_size: 68, font_weight: '800', color: '#FFFFFF', stroke_color: '#000000', stroke_width: 3, background: 'none', position_y: 75, position_x: 50, text_align: 'center', animation: 'pop', text_transform: 'uppercase', shadow_color: 'rgba(0,0,0,0.85)', shadow_blur: 10, shadow_offset_x: 2, shadow_offset_y: 3, highlight: true, highlight_mode: 'text', highlight_color: '#FFD400', current_word_scale: 1.16 },
    left_block_white: { font_family: 'Bebas Neue', font_size: 84, font_weight: '700', color: '#FFFFFF', stroke_color: 'none', stroke_width: 0, background: 'none', position_y: 74, position_x: 9, text_align: 'left', animation: 'hard_cut', text_transform: 'uppercase', wrap_words_per_line: 3, lead_word_line: true, random_line_emphasis: true, random_line_scale: 1.22, random_line_chance: 1.0, random_line_targets: [1, 3], word_by_word_reveal: true, letter_spacing: 0, shadow_color: 'rgba(0,0,0,0.9)', shadow_blur: 9, shadow_offset_x: 2, shadow_offset_y: 3, edge_fade_ms: 110 },
    center_block_white: { font_family: 'Bebas Neue', font_size: 84, font_weight: '700', color: '#FFFFFF', stroke_color: 'none', stroke_width: 0, background: 'none', position_y: 74, position_x: 50, text_align: 'center', animation: 'hard_cut', text_transform: 'uppercase', wrap_words_per_line: 3, lead_word_line: true, random_line_emphasis: true, random_line_scale: 1.22, random_line_chance: 1.0, random_line_targets: [1, 3], word_by_word_reveal: true, letter_spacing: 0, shadow_color: 'rgba(0,0,0,0.9)', shadow_blur: 9, shadow_offset_x: 2, shadow_offset_y: 3, edge_fade_ms: 110 },
    right_block_white: { font_family: 'Bebas Neue', font_size: 84, font_weight: '700', color: '#FFFFFF', stroke_color: 'none', stroke_width: 0, background: 'none', position_y: 74, position_x: 91, text_align: 'right', animation: 'hard_cut', text_transform: 'uppercase', wrap_words_per_line: 3, lead_word_line: true, random_line_emphasis: true, random_line_scale: 1.22, random_line_chance: 1.0, random_line_targets: [1, 3], word_by_word_reveal: true, letter_spacing: 0, shadow_color: 'rgba(0,0,0,0.9)', shadow_blur: 9, shadow_offset_x: 2, shadow_offset_y: 3, edge_fade_ms: 110 },
    single_line: { font_family: 'Montserrat', font_size: 80, font_weight: '900', color: '#FFFFFF', stroke_color: 'none', stroke_width: 0, background: 'none', position_y: 81, animation: 'hard_cut', text_transform: 'uppercase', letter_spacing: -2, blend_mode: 'difference', shadow_color: 'rgba(0,0,0,1.00)', shadow_blur: 10, shadow_offset_x: 3, shadow_offset_y: 3, diff_strength: 0.59, overlay_strength: 0.37, overlay_color: '#ffffff', edge_fade_ms: 90 },
    single_line_highlight: { font_family: 'Montserrat', font_size: 64, font_weight: '900', color: 'rgba(255,255,255,0.35)', stroke_color: 'none', stroke_width: 0, background: 'none', position_y: 81, animation: 'hard_cut', text_transform: 'uppercase', letter_spacing: -2, shadow_color: '#000000', shadow_blur: 8, shadow_offset_x: 2, shadow_offset_y: 2, highlight: true, highlight_color: '#FFFFFF' },
};
let captionPresetMap = { ...LOCAL_CAPTION_PRESETS };

// ---------------------------------------------------------------------------
// Text display mode & tone-based animation presets
// ---------------------------------------------------------------------------

const TEXT_DISPLAY_MODES = {
    full: 'Complete Text',
    emphasis: 'Emphasis Words'
};

// Stop-words filtered out in emphasis mode
const EMPHASIS_STOP_WORDS = new Set([
    'a', 'an', 'the', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
    'am', 'do', 'does', 'did', 'has', 'have', 'had', 'having',
    'i', 'me', 'my', 'we', 'our', 'you', 'your', 'he', 'she', 'it',
    'him', 'her', 'his', 'its', 'they', 'them', 'their',
    'this', 'that', 'these', 'those', 'what', 'which', 'who', 'whom',
    'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'from',
    'up', 'out', 'if', 'or', 'and', 'but', 'not', 'no', 'nor',
    'so', 'as', 'just', 'about', 'into', 'than', 'then', 'also',
    'very', 'can', 'will', 'would', 'could', 'should', 'may', 'might',
    'shall', 'must', 'here', 'there', 'when', 'where', 'how', 'all',
    'each', 'both', 'few', 'more', 'most', 'some', 'any', 'such',
    'only', 'own', 'same', 'too', 'still', 'already', 'yet'
]);

/**
 * Extract emphasis words from text by removing articles and low-sentiment words.
 * Returns the filtered string.
 */
function extractEmphasisWords(text) {
    if (!text) return '';
    const words = text.split(/\s+/);
    const kept = words.filter(w => {
        const clean = w.replace(/[^a-zA-Z]/g, '').toLowerCase();
        return clean.length > 0 && !EMPHASIS_STOP_WORDS.has(clean);
    });
    return kept.length > 0 ? kept.join(' ') : text;
}

// Animation presets mapped to story tones
// ── Hook Animations (unified scene animation + word emphasis) ──
// Each hook pairs a scene-level animation key with a word emphasis key.
const HOOK_ANIMATIONS = {
    // ── Reveal family (blur/fade in variations) ──
    creep_reveal:       { label: 'Creep Reveal',       animation: 'blur_in',     emphasis: 'fade_stagger',    tone: 'suspenseful' },
    slow_reveal:        { label: 'Slow Reveal',        animation: 'stoic_fade',  emphasis: 'fade_stagger',    tone: 'dramatic' },
    soft_reveal:        { label: 'Soft Reveal',        animation: 'fade',        emphasis: 'fade_stagger',    tone: 'wholesome' },
    deep_reveal:        { label: 'Deep Reveal',        animation: 'blur_in',     emphasis: 'rise_word',       tone: 'cinematic' },
    // ── Rise family (text rises into place) ──
    epic_rise:          { label: 'Epic Rise',          animation: 'rise',        emphasis: 'fade_stagger',    tone: 'epic' },
    gentle_rise:        { label: 'Gentle Rise',        animation: 'rise',        emphasis: 'rise_word',       tone: 'inspirational' },
    // ── Cinematic family ──
    movie_title:        { label: 'Movie Title',        animation: 'movie_title', emphasis: 'fade_stagger',    tone: 'cinematic' },
    title_card:         { label: 'Title Card',         animation: 'movie_title', emphasis: 'underline_sweep', tone: 'epic' },
    // ── Atmospheric family ──
    drift_fade:         { label: 'Drift Fade',         animation: 'drift',       emphasis: 'fade_stagger',    tone: 'nostalgic' },
    glow_emerge:        { label: 'Glow Emerge',        animation: 'glow_pulse',  emphasis: 'glow_color',      tone: 'dramatic' },
    breathe_in:         { label: 'Breathe In',         animation: 'breathe',     emphasis: 'fade_stagger',    tone: 'meditative' },
    // ── Impact family (hard entries) ──
    hard_cut:           { label: 'Hard Cut',           animation: 'hard_cut',    emphasis: 'fade_stagger',    tone: 'urgent' },
    drop_in:            { label: 'Drop In',            animation: 'drop_in',     emphasis: 'fade_stagger',    tone: 'dramatic' },
    slam_in:            { label: 'Slam In',            animation: 'slam',        emphasis: 'scale_burst',     tone: 'motivational' },
    // ── Slide family ──
    slide_in:           { label: 'Slide In',           animation: 'slide_left',  emphasis: 'fade_stagger',    tone: 'educational' },
    slide_up:           { label: 'Slide Up',           animation: 'slide_up',    emphasis: 'fade_stagger',    tone: 'inspirational' },
    // ── Dark / tension family ──
    flicker_in:         { label: 'Flicker In',         animation: 'flicker',     emphasis: 'fade_stagger',    tone: 'suspenseful' },
    glitch_in:          { label: 'Glitch In',          animation: 'glitch',      emphasis: 'neon',            tone: 'dark' },
    void_emerge:        { label: 'Void Emerge',        animation: 'stoic_fade',  emphasis: 'disintegrate',    tone: 'horror' },
};

// Per-tone subgroups: pipeline picks randomly from these
const TONE_HOOK_GROUP = {
    suspenseful:   ['creep_reveal', 'flicker_in', 'slow_reveal'],
    dramatic:      ['slow_reveal', 'drop_in', 'glow_emerge', 'deep_reveal'],
    epic:          ['epic_rise', 'movie_title', 'title_card'],
    comedic:       ['hard_cut', 'slide_in', 'drop_in'],
    inspirational: ['gentle_rise', 'soft_reveal', 'slide_up'],
    educational:   ['slide_in', 'soft_reveal', 'hard_cut'],
    horror:        ['void_emerge', 'glitch_in', 'flicker_in'],
    wholesome:     ['soft_reveal', 'breathe_in', 'gentle_rise'],
    romantic:      ['soft_reveal', 'gentle_rise', 'breathe_in'],
    nostalgic:     ['drift_fade', 'slow_reveal', 'creep_reveal'],
    melancholic:   ['drift_fade', 'slow_reveal', 'creep_reveal'],
    meditative:    ['breathe_in', 'soft_reveal', 'drift_fade'],
    philosophical: ['slow_reveal', 'breathe_in', 'drift_fade'],
    stoic:         ['slow_reveal', 'hard_cut', 'deep_reveal'],
    motivational:  ['slam_in', 'epic_rise', 'drop_in'],
    urgent:        ['hard_cut', 'flicker_in', 'slam_in'],
    dark:          ['glitch_in', 'void_emerge', 'flicker_in'],
    mysterious:    ['creep_reveal', 'drift_fade', 'deep_reveal'],
    cinematic:     ['movie_title', 'deep_reveal', 'epic_rise'],
};

/**
 * Resolve a hook animation ID into its animation + emphasis keys.
 */
function _resolveHookParts(hookId) {
    const hook = HOOK_ANIMATIONS[hookId];
    if (hook) return { animation: hook.animation, emphasis: hook.emphasis };
    return { animation: 'fade', emphasis: 'none' };
}

/**
 * Return the first hook from the current project's tone group.
 */
function getDefaultHookAnimation() {
    const tone = EditorState.project?.storyTone || '';
    const group = TONE_HOOK_GROUP[tone];
    return group ? group[0] : 'dramatic_slam';
}

// Legacy compat aliases
function getDefaultTextAnimation() { return _resolveHookParts(getDefaultHookAnimation()).animation; }
function getDefaultWordEmphasis() { return _resolveHookParts(getDefaultHookAnimation()).emphasis; }

/**
 * Migrate legacy scenes (text_animation + text_emphasis) to text_hook_animation.
 */
function _migrateToHookAnimation(scene) {
    if (scene.text_hook_animation && HOOK_ANIMATIONS[scene.text_hook_animation]) return;
    const anim = scene.text_animation || '';
    const emph = scene.text_emphasis || '';
    // Find a hook that matches both, or just the animation
    for (const [id, h] of Object.entries(HOOK_ANIMATIONS)) {
        if (h.animation === anim && h.emphasis === emph) { scene.text_hook_animation = id; return; }
    }
    for (const [id, h] of Object.entries(HOOK_ANIMATIONS)) {
        if (h.animation === anim) { scene.text_hook_animation = id; return; }
    }
    scene.text_hook_animation = getDefaultHookAnimation();
}

/**
 * Build <option> HTML for the hook animation select dropdown.
 */
function _buildHookAnimationOptions(selectedId) {
    const tone = EditorState.project?.storyTone || '';
    const recommended = TONE_HOOK_GROUP[tone] || [];
    let html = '';

    if (recommended.length) {
        html += '<optgroup label="Recommended">';
        for (const id of recommended) {
            const h = HOOK_ANIMATIONS[id];
            if (!h) continue;
            const sel = id === selectedId ? ' selected' : '';
            html += '<option value="' + id + '"' + sel + ' title="' + h.animation + ' + ' + h.emphasis + '">' + h.label + '</option>';
        }
        html += '</optgroup>';
    }

    html += '<optgroup label="All Hooks">';
    for (const [id, h] of Object.entries(HOOK_ANIMATIONS)) {
        if (recommended.includes(id)) continue;
        const sel = id === selectedId ? ' selected' : '';
        html += '<option value="' + id + '"' + sel + ' title="' + h.animation + ' + ' + h.emphasis + '">' + h.label + '</option>';
    }
    html += '</optgroup>';
    return html;
}

function prettifyPresetName(presetId) {
    return String(presetId || '')
        .replace(/_/g, ' ')
        .replace(/\b\w/g, c => c.toUpperCase());
}

async function loadCaptionPresetOptions(selectEl, selectedId = 'bold_popup') {
    if (!selectEl) return;

    let apiPresets = [];
    try {
        const res = await fetch('/api/captions/presets');
        if (res.ok) apiPresets = await res.json();
    } catch (_) {}

    const fetchedMap = {};
    for (const preset of apiPresets) {
        if (!preset || !preset.id) continue;
        fetchedMap[preset.id] = preset;
    }
    captionPresetMap = { ...LOCAL_CAPTION_PRESETS, ...fetchedMap };

    const seen = new Set();
    const ordered = [];
    for (const preset of apiPresets) {
        if (!preset || !preset.id || seen.has(preset.id)) continue;
        seen.add(preset.id);
        ordered.push({ id: preset.id, name: preset.name || prettifyPresetName(preset.id) });
    }
    for (const presetId of Object.keys(LOCAL_CAPTION_PRESETS)) {
        if (seen.has(presetId)) continue;
        seen.add(presetId);
        ordered.push({ id: presetId, name: prettifyPresetName(presetId) });
    }

    selectEl.innerHTML = '';
    for (const item of ordered) {
        const opt = document.createElement('option');
        opt.value = item.id;
        opt.textContent = item.name;
        selectEl.appendChild(opt);
    }

    const activeId = captionPresetMap[selectedId] ? selectedId : (ordered[0]?.id || 'bold_popup');
    selectEl.value = activeId;
}

// ---------------------------------------------------------------------------
// Universal Audio Track System
// ---------------------------------------------------------------------------
let _audioTrackIdCounter = 0;
function nextAudioTrackId() { return `at_${++_audioTrackIdCounter}`; }

const AUDIO_TRACK_COLORS = {
    voice: 'rgba(78, 205, 196, 0.8)',
    music: 'rgba(167, 139, 250, 0.8)',
    fx: 'rgba(255, 183, 77, 0.8)',
    sfx: 'rgba(255, 183, 77, 0.8)',
};
const DEFAULT_MUSIC_DUCKING_LEVEL = 0.15;

function normalizeAudioTrackType(type = 'voice') {
    const normalized = String(type || 'voice').toLowerCase();
    return normalized === 'fx' ? 'sfx' : normalized;
}

function isSfxTrackType(type = '') {
    return normalizeAudioTrackType(type) === 'sfx';
}

function getVolumeStorageKeys(type = 'voice') {
    const normalized = normalizeAudioTrackType(type);
    return normalized === 'sfx'
        ? ['sts-vol-sfx', 'sts-vol-fx']
        : [`sts-vol-${normalized}`];
}

/**
 * Read user-configured ducking default from settings (saved by SettingsPage),
 * fall back to DEFAULT_MUSIC_DUCKING_LEVEL.
 */
function getUserDuckingDefault() {
    try {
        const v = localStorage.getItem('sts-music-ducking');
        if (v != null) {
            const n = parseFloat(v);
            if (!isNaN(n) && n > 0 && n <= 1) return n;
        }
    } catch (_) {}
    return DEFAULT_MUSIC_DUCKING_LEVEL;
}
const MIN_MUSIC_DUCKING_LEVEL = 0.12;
const MIN_TEXT_OVERLAY_DURATION = 0.5;

function getPathFileName(path) {
    const clean = String(path || '').split('#')[0].split('?')[0];
    const parts = clean.split('/').filter(Boolean);
    return parts.length ? parts[parts.length - 1] : '';
}

function normalizeVoiceAudioConfig(audioLike = {}) {
    if (!audioLike) return null;
    const url = audioLike.url || audioLike.path || '';
    const sourceFile = getPathFileName(url) || audioLike.source_file || audioLike.file || '';
    return {
        url,
        source_file: sourceFile,
        duration: Number(audioLike.duration) || 0,
        trimmedDuration: audioLike.trimmedDuration ?? audioLike.trimmed_duration ?? null,
        timelineOffset: audioLike.timelineOffset ?? audioLike.timeline_offset ?? 0,
        startOffset: audioLike.startOffset ?? audioLike.start_offset ?? 0
    };
}

function getDefaultVoiceAudioFallbacks(projectId, sourceFolder = '') {
    const folder = sourceFolder || projectId || '';
    return [
        folder ? `/output/alignments/${folder}/voice.wav` : '',
        folder ? `/output/alignments/${folder}/voice.mp3` : '',
        folder ? `/output/tts/${folder}/voice.wav` : '',
        folder ? `/output/tts/${folder}/voice.mp3` : ''
    ].filter(Boolean);
}

async function resolveDefaultVoiceAudio(projectId, sourceFolder, stagedAudio) {
    const normalized = normalizeVoiceAudioConfig(stagedAudio);
    if (normalized?.url) return normalized;

    if (sourceFolder) {
        try {
            const res = await fetch(`/api/scenes/audio/${encodeURIComponent(sourceFolder)}`, {
                signal: AbortSignal.timeout(4000)
            });
            if (res.ok) {
                const resolved = normalizeVoiceAudioConfig(await res.json());
                if (resolved?.url) return resolved;
            }
        } catch (error) {
            console.warn('Voice audio lookup failed:', sourceFolder, error);
        }
    }

    const fallbackUrl = getDefaultVoiceAudioFallbacks(projectId, sourceFolder)[0] || '';
    return fallbackUrl ? normalizeVoiceAudioConfig({ url: fallbackUrl }) : null;
}

function _getSavedVolume(type) {
    try {
        for (const key of getVolumeStorageKeys(type)) {
            const v = parseFloat(localStorage.getItem(key));
            if (!isNaN(v)) return v;
        }
        return null;
    } catch {
        return null;
    }
}
function _saveVolume(type, vol) {
    try {
        const keys = getVolumeStorageKeys(type);
        keys.forEach(key => localStorage.setItem(key, vol));
    } catch {}
}

function createAudioTrack(overrides = {}) {
    const type = normalizeAudioTrackType(overrides.type || 'voice');
    const savedVol = _getSavedVolume(type);
    const defaults = {
        id: nextAudioTrackId(),
        label: 'Audio',
        type,                    // 'voice' | 'music' | 'sfx'
        file: null,
        path: null,
        duration: 0,
        timelineOffset: 0,
        startOffset: 0,
        trimmedDuration: null,
        volume: 1.0,
        loop: false,
        duckingEnabled: false,
        duckingLevel: DEFAULT_MUSIC_DUCKING_LEVEL,
        fadeIn: 0,
        fadeOut: 0,
        loaded: false,
        error: false,
        muted: false,
        element: null,           // HTML Audio element
        color: AUDIO_TRACK_COLORS[type] || AUDIO_TRACK_COLORS.voice,
        clips: null,             // Multi-clip array for SFX tracks: [{id, file, path, label, duration, offset, element}]
    };
    // Apply saved volume if no explicit volume override
    if (savedVol !== null && !('volume' in overrides)) {
        defaults.volume = savedVol;
    }
    return {
        ...defaults,
        ...overrides,
        type,
        color: overrides.color || defaults.color,
    };
}

let _nextClipId = 1;
function nextClipId() { return `clip_${_nextClipId++}`; }

/**
 * Add a clip to a multi-clip FX track. Creates the audio element and wires metadata.
 */
function addClipToFxTrack(track, sfx, offset) {
    if (!track.clips) track.clips = [];
    const clip = {
        id: nextClipId(),
        file: sfx.filename,
        path: sfx.path,
        label: sfx.label || sfx.filename || 'FX',
        duration: sfx.duration || 0,
        offset: Math.round(Math.max(0, offset) * 1000) / 1000,
        element: null,
    };
    const audio = new Audio(sfx.path);
    clip.element = audio;
    audio.addEventListener('loadedmetadata', () => {
        clip.duration = audio.duration;
        renderAllAudioTracks();
    });
    track.clips.push(clip);
    // Mark track as loaded if it has clips
    track.loaded = true;
    return clip;
}

function getVoiceTrack() {
    return EditorState.audioTracks.find(t => t.type === 'voice');
}
function _getAudioForPersist() {
    const vt = getVoiceTrack();
    if (vt?.path) {
        const audio = normalizeVoiceAudioConfig({
            url: vt.path,
            source_file: vt.file || '',
            duration: vt.duration || 0,
            trimmedDuration: vt.trimmedDuration || null,
            timelineOffset: vt.timelineOffset || 0,
            startOffset: vt.startOffset || 0
        });
        if (audio?.url) return { audio };
    }
    const savedAudio = normalizeVoiceAudioConfig(EditorState.savedAudioSettings);
    if (savedAudio?.url) return { audio: savedAudio };
    return {};
}
function getAudioTrackById(id) {
    return EditorState.audioTracks.find(t => t.id === id);
}

function getTrackStartOffset(track) {
    return Math.max(0, Number(track?.startOffset) || 0);
}

function getTrackTimelineOffset(track) {
    return Math.max(0, Number(track?.timelineOffset) || 0);
}

function getTrackMinDuration(track) {
    return Math.min(1, Math.max(0.1, Number(track?.duration) || 1));
}

function getTrackVisibleDuration(track) {
    if (!track) return 0;
    const duration = Math.max(0, Number(track.duration) || 0);
    const requested = Number(track.trimmedDuration);

    if (track.loop) {
        return requested > 0 ? requested : duration;
    }

    const maxVisible = Math.max(0, duration - getTrackStartOffset(track));
    if (requested > 0) {
        return Math.min(requested, maxVisible || requested);
    }
    return maxVisible;
}

function getTrackSourceEnd(track) {
    return getTrackStartOffset(track) + getTrackVisibleDuration(track);
}

function getTrackTimelineDuration(track, timelineFallback = 0) {
    if (!track) return 0;
    if (track.loop && !(Number(track.trimmedDuration) > 0)) {
        return Math.max(0, timelineFallback - getTrackTimelineOffset(track));
    }
    return getTrackVisibleDuration(track);
}

function getTrackTimelineEnd(track, timelineFallback = 0) {
    return getTrackTimelineOffset(track) + getTrackTimelineDuration(track, timelineFallback);
}

function applyTrackTrimState(track, nextState = {}) {
    if (!track) return null;

    const duration = Math.max(0, Number(track.duration) || 0);
    const minDuration = getTrackMinDuration(track);
    let timelineOffset = Math.max(0, Number(nextState.timelineOffset ?? track.timelineOffset) || 0);
    let startOffset = Math.max(0, Number(nextState.startOffset ?? track.startOffset) || 0);
    let trimmedDuration = Number(nextState.trimmedDuration ?? track.trimmedDuration);

    if (track.loop) {
        if (duration > 0) startOffset = Math.min(startOffset, duration);
        if (!(trimmedDuration > 0)) trimmedDuration = duration || minDuration;
        trimmedDuration = Math.max(minDuration, trimmedDuration);
    } else {
        startOffset = Math.min(startOffset, Math.max(0, duration - minDuration));
        const maxVisible = Math.max(minDuration, duration - startOffset);
        if (!(trimmedDuration > 0)) trimmedDuration = maxVisible;
        trimmedDuration = Math.min(Math.max(minDuration, trimmedDuration), maxVisible);
    }

    track.timelineOffset = Math.round(timelineOffset * 1000) / 1000;
    track.startOffset = Math.round(startOffset * 1000) / 1000;
    track.trimmedDuration = Math.round(trimmedDuration * 1000) / 1000;
    return {
        timelineOffset: track.timelineOffset,
        startOffset: track.startOffset,
        trimmedDuration: track.trimmedDuration
    };
}

function getTrackPlaybackTime(track, timelineTime) {
    const timelineOffset = getTrackTimelineOffset(track);
    const startOffset = getTrackStartOffset(track);
    const clipTime = Math.max(0, timelineTime - timelineOffset);
    if (track?.loop) {
        const duration = Math.max(0.1, Number(track.duration) || 0.1);
        return (startOffset + clipTime) % duration;
    }
    return Math.min(startOffset + clipTime, getTrackSourceEnd(track));
}

function getSceneTextOffset(scene) {
    return Math.max(0, Number(scene?.text_timeline_offset) || 0);
}

function getSceneTextDuration(scene) {
    if (!scene) return 0;
    const maxDuration = Math.max(0, Number(scene.duration) || 0);
    const offset = getSceneTextOffset(scene);
    const requested = Number(scene.text_overlay_duration);
    const remaining = Math.max(0, maxDuration - offset);
    if (requested > 0) return Math.min(requested, remaining || requested);
    return remaining;
}

function getSceneTextValue(scene) {
    if (!scene) return '';
    if (scene.type === 'text' || scene.type === 'cta') {
        return String(scene.text_content || scene.script || '').trim();
    }
    return String(scene.text_content || '').trim();
}

function hasSceneTextOverlay(scene) {
    return !!getSceneTextValue(scene);
}

function getSceneTextTimelineStart(sceneIndex) {
    const scene = EditorState.scenes[sceneIndex];
    return getSceneStartTime(sceneIndex) + getSceneTextOffset(scene);
}

function normalizeSceneTextOverlay(scene) {
    if (!scene) return;
    const duration = Math.max(0, Number(scene.duration) || 0);
    const maxOffset = Math.max(0, duration - MIN_TEXT_OVERLAY_DURATION);
    scene.text_timeline_offset = Math.min(maxOffset, Math.max(0, Number(scene.text_timeline_offset) || 0));
    const maxOverlayDuration = Math.max(MIN_TEXT_OVERLAY_DURATION, duration - scene.text_timeline_offset);
    scene.text_overlay_duration = Math.min(
        maxOverlayDuration,
        Math.max(MIN_TEXT_OVERLAY_DURATION, Number(scene.text_overlay_duration) || maxOverlayDuration)
    );
    if (typeof scene.text_background_enabled !== 'boolean') {
        scene.text_background_enabled = scene.type === 'text' || scene.type === 'cta';
    }
    if (!scene.text_background_color) scene.text_background_color = '#000000';
}

function getNextSceneId() {
    const maxId = EditorState.scenes.reduce((max, scene) => {
        const id = Number(scene?.id);
        return Number.isFinite(id) ? Math.max(max, id) : max;
    }, 0);
    return maxId + 1;
}

function cloneScene(scene) {
    return JSON.parse(JSON.stringify(scene));
}

function clearSceneTextOverlay(scene) {
    if (!scene) return;
    scene.text_content = null;
    scene.text_timeline_offset = 0;
    scene.text_overlay_duration = null;
    scene.text_background_enabled = false;
    scene.text_background_color = '#000000';
}

function hasSceneBackgroundMedia(scene) {
    return !!(scene && (scene.mediaUrl || scene.videoThumb || scene.image));
}

function getSceneThumbSource(scene) {
    if (!scene) return null;
    const isVid = scene.isVideo || isVideoFile(scene.mediaUrl);
    if (isVid) {
        // Prefer extracted/cached data-URL or server-assigned thumb
        if (scene.videoThumb) return scene.videoThumb;
        // Derive server-side _thumb.jpg path from video URL (never return raw .mp4)
        const vidUrl = scene.mediaUrl || scene.image_url;
        if (vidUrl) {
            const dotIdx = vidUrl.lastIndexOf('.');
            if (dotIdx !== -1) return vidUrl.substring(0, dotIdx) + '_thumb.jpg';
        }
        return null;
    }
    if (scene.mediaUrl) return scene.mediaUrl;
    if (scene.image_url) return scene.image_url;
    if (scene.image && EditorState.project?.id) {
        return `working-assets/${EditorState.project.id}/${scene.image}`;
    }
    return null;
}

function getSceneClipThumbMarkup(scene, icon) {
    const isTextScene = scene.type === 'text' || scene.type === 'cta';
    const textBadge = isTextScene ? '<span class="scene-thumb-text-badge">TXT</span>' : '';
    const thumbSrc = getSceneThumbSource(scene);

    // Text scenes: solid black unless scene background mode AND image exists
    if (isTextScene) {
        if (!scene.text_background_enabled && thumbSrc) {
            // Scene background mode with valid image
            return `
                <div class="scene-clip-thumb scene-thumb-has-text">
                    <img src="${thumbSrc}" alt="Scene ${scene.id}">
                    ${textBadge}
                </div>
            `;
        }
        // Solid color mode (default) or no image available — always solid
        const solidBgColor = scene.text_background_color || '#000000';
        return `
            <div class="scene-clip-thumb scene-thumb-solid" style="--thumb-solid-color: ${solidBgColor}">
                ${textBadge}
            </div>
        `;
    }

    const isVid = scene.isVideo || isVideoFile(scene.mediaUrl);
    const typeBadge = isVid && thumbSrc
        ? '<span class="media-video-badge" data-tooltip="Video"><svg width="8" height="8" viewBox="0 0 24 24" fill="currentColor"><polygon points="6,4 20,12 6,20"/></svg></span>'
        : thumbSrc
            ? '<span class="media-image-badge" data-tooltip="Image"><svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg></span>'
            : '';
    const mediaMarkup = thumbSrc
        ? `<img src="${thumbSrc}" alt="Scene ${scene.id}" onerror="this.style.display='none'">`
        : icon;

    return `
        <div class="scene-clip-thumb">
            ${mediaMarkup}
            ${typeBadge}
        </div>
    `;
}

function syncTimelineAfterSceneStructureChange(selectSceneId = null, selectAsOverlay = false) {
    EditorState.project.sceneCount = EditorState.scenes.length;
    normalizeTimelineDurations();
    recalculateDuration();
    renderTimeline();
    if (EditorState.preview) {
        EditorState.preview.setScenes(EditorState.scenes);
        EditorState.preview.seek(EditorState.playbackPosition);
    }
    if (selectSceneId !== null) {
        if (selectAsOverlay) {
            selectTextOverlay(selectSceneId);
        } else {
            selectScene(selectSceneId);
        }
    } else {
        renderSceneProperties();
    }
    saveProjectEdits();
}

function convertTextOverlayToScene(sceneId) {
    const sceneIndex = EditorState.scenes.findIndex(s => s.id === sceneId);
    const scene = EditorState.scenes[sceneIndex];
    if (!scene) return;

    normalizeSceneTextOverlay(scene);
    const textContent = getSceneTextValue(scene);
    if (!textContent) {
        showToast('This scene has no text overlay to convert', 'info');
        return;
    }

    const startOffset = getSceneTextOffset(scene);
    const overlayDuration = getSceneTextDuration(scene);
    const beforeDuration = Math.max(0, Math.round(startOffset * 1000) / 1000);
    const afterDuration = Math.max(0, Math.round((scene.duration - startOffset - overlayDuration) * 1000) / 1000);
    const originalScene = cloneScene(scene);
    const replacement = [];
    const originalTransition = cloneScene(scene.transition || { type: 'none', duration: 0 });

    if (beforeDuration >= 0.1) {
        const beforeScene = cloneScene(originalScene);
        beforeScene.duration = beforeDuration;
        beforeScene.transition = { type: 'none', duration: 0 };
        clearSceneTextOverlay(beforeScene);
        replacement.push(beforeScene);
    }

    const textScene = {
        id: getNextSceneId(),
        type: 'text',
        duration: overlayDuration,
        text_content: textContent,
        script: textContent,
        text_color: originalScene.text_color,
        text_size: originalScene.text_size,
        font_family: originalScene.font_family,
        font_style: originalScene.font_style,
        text_align: originalScene.text_align,
        vertical_align: originalScene.vertical_align,
        text_x: originalScene.text_x,
        text_y: originalScene.text_y,
        text_background_enabled: true,
        text_background_color: originalScene.text_background_color || '#000000',
        text_timeline_offset: 0,
        text_overlay_duration: overlayDuration,
        visual_fx: originalScene.visual_fx || 'static',
        image_prompt: originalScene.image_prompt || '',
        mediaUrl: originalScene.mediaUrl || null,
        image_url: originalScene.mediaUrl || originalScene.image_url || null,
        image: originalScene.image || '',
        mediaLoaded: !!originalScene.mediaLoaded,
        isVideo: !!originalScene.isVideo,
        videoThumb: originalScene.videoThumb || null,
        status: originalScene.status || 'ready',
        timestamp: originalScene.timestamp || 0,
        narrative_role: originalScene.narrative_role || '',
        filler_shift: 0,
        segment_start: null,
        segment_end: null,
        segment_duration: null,
        transition: afterDuration >= 0.1 ? { type: 'none', duration: 0 } : originalTransition
    };
    replacement.push(textScene);

    if (afterDuration >= 0.1) {
        const afterScene = cloneScene(originalScene);
        afterScene.id = getNextSceneId() + 1;
        afterScene.duration = afterDuration;
        afterScene.transition = originalTransition;
        clearSceneTextOverlay(afterScene);
        replacement.push(afterScene);
    }

    EditorState.scenes.splice(sceneIndex, 1, ...replacement);
    syncTimelineAfterSceneStructureChange(textScene.id, false);
    showToast('Converted text overlay to scene', 'success');
}

function convertTextSceneToOverlay(sceneId) {
    const sceneIndex = EditorState.scenes.findIndex(s => s.id === sceneId);
    const scene = EditorState.scenes[sceneIndex];
    const hostScene = sceneIndex > 0 ? EditorState.scenes[sceneIndex - 1] : null;
    if (!scene || !hostScene) {
        showToast('A text scene needs a visual scene before it', 'warning');
        return;
    }
    if (hostScene.type === 'text' || hostScene.type === 'cta') {
        showToast('The previous scene must be an image or video scene', 'warning');
        return;
    }
    if (getSceneTextValue(hostScene)) {
        showToast('The previous scene already has a text overlay', 'warning');
        return;
    }

    const textContent = getSceneTextValue(scene);
    hostScene.text_content = textContent;
    hostScene.text_color = scene.text_color;
    hostScene.text_size = scene.text_size;
    hostScene.font_family = scene.font_family;
    hostScene.font_style = scene.font_style;
    hostScene.text_align = scene.text_align;
    hostScene.vertical_align = scene.vertical_align;
    hostScene.text_x = scene.text_x;
    hostScene.text_y = scene.text_y;
    hostScene.text_background_enabled = !!scene.text_background_enabled;
    hostScene.text_background_color = scene.text_background_color || '#000000';
    hostScene.text_timeline_offset = hostScene.duration;
    hostScene.text_overlay_duration = scene.duration;
    hostScene.duration = Math.round((hostScene.duration + scene.duration) * 1000) / 1000;
    normalizeSceneTextOverlay(hostScene);

    EditorState.scenes.splice(sceneIndex, 1);
    syncTimelineAfterSceneStructureChange(hostScene.id, true);
    showToast('Converted text scene to overlay', 'success');
}

function getTextToolSelectedScene() {
    if (EditorState.selectedTextOverlaySceneId != null) {
        return EditorState.scenes.find(scene => scene.id === EditorState.selectedTextOverlaySceneId) || null;
    }
    if (EditorState.selectedScene?.id != null) {
        return EditorState.scenes.find(scene => scene.id === EditorState.selectedScene.id) || null;
    }
    return null;
}

function getTextOverlayTargetScene() {
    const scene = getTextToolSelectedScene();
    if (!scene || scene.type === 'text' || scene.type === 'cta') return null;
    return scene;
}

function getTextToolInsertIndex() {
    const selectedScene = getTextToolSelectedScene();
    if (!selectedScene) return EditorState.scenes.length;
    const idx = EditorState.scenes.findIndex(scene => scene.id === selectedScene.id);
    return idx >= 0 ? idx + 1 : EditorState.scenes.length;
}

function getTextToolPayload() {
    const textarea = document.getElementById('text-tool-content');
    const durationInput = document.getElementById('text-tool-duration');
    const text = (textarea?.value || '').trim();
    const duration = Math.max(MIN_TEXT_OVERLAY_DURATION, parseFloat(durationInput?.value || '2') || 2);
    const modeFullBtn = document.getElementById('text-tool-mode-full');
    const displayMode = modeFullBtn?.classList.contains('active') ? 'full' : 'emphasis';
    const animationSelect = document.getElementById('text-tool-animation');
    const animation = animationSelect?.value || getDefaultTextAnimation();
    return { textarea, text, duration, displayMode, animation };
}

function buildTextSceneFromTool(text, duration, displayMode, animation) {
    const scene = {
        id: getNextSceneId(),
        type: 'text',
        duration,
        text_content: text,
        script: text,
        text_color: 'white',
        text_size: 72,
        font_family: 'Inter',
        font_style: 'bold',
        text_align: 'center',
        vertical_align: 'center',
        // Default text_y places new text scenes in the upper third of the frame.
        // 30% gives "title card / hero text" energy: clearly above center, with
        // captions at 75-85% creating breathing room below. Reset-position button
        // (clears text_y) still falls back to vertical_align: center.
        text_y: 30,
        text_background_enabled: true,
        text_background_color: '#000000',
        text_hide_captions: true,
        text_display_mode: displayMode || 'emphasis',
        text_hook_animation: getDefaultHookAnimation(),
        text_animation: _resolveHookParts(getDefaultHookAnimation()).animation,
        text_emphasis: _resolveHookParts(getDefaultHookAnimation()).emphasis,
        text_timeline_offset: 0,
        text_overlay_duration: duration,
        visual_fx: 'static',
        image_prompt: '',
        mediaUrl: null,
        image_url: null,
        image: '',
        mediaLoaded: false,
        isVideo: false,
        videoThumb: null,
        status: 'ready',
        timestamp: 0,
        narrative_role: '',
        filler_shift: 0,
        segment_start: null,
        segment_end: null,
        segment_duration: null,
        transition: { type: 'none', duration: 0 }
    };
    normalizeSceneTextOverlay(scene);
    return scene;
}

function renderTextToolState() {
    const targetEl = document.getElementById('text-tool-target');
    const addSceneBtn = document.getElementById('text-add-scene');
    const addOverlayBtn = document.getElementById('text-add-overlay');
    if (!targetEl || !addSceneBtn || !addOverlayBtn) return;

    const { text } = getTextToolPayload();
    const selectedScene = getTextToolSelectedScene();
    const overlayTarget = getTextOverlayTargetScene();
    const hasOverlay = overlayTarget ? hasSceneTextOverlay(overlayTarget) : false;

    let message = 'Create a standalone text scene or select an image/video scene to place text directly on it.';
    if (!EditorState.project) {
        message = 'Load a project first to add text to the timeline.';
    } else if (overlayTarget) {
        message = hasOverlay
            ? `<strong>Selected:</strong> Scene ${overlayTarget.id} already has a text overlay. Convert or edit it from the timeline.`
            : `<strong>Selected for overlay:</strong> Scene ${overlayTarget.id} (${overlayTarget.type}). New text will start at the beginning of this scene.`;
    } else if (selectedScene) {
        message = `<strong>Selected:</strong> Scene ${selectedScene.id} is a text scene. Add another text scene, or select an image/video scene to add an overlay.`;
    }

    targetEl.innerHTML = message;
    addSceneBtn.disabled = !EditorState.project || !text;
    addOverlayBtn.disabled = !EditorState.project || !text || !overlayTarget || hasOverlay;
}

function addTextSceneFromTool() {
    if (!EditorState.project) {
        showToast('Load a project first', 'warning');
        return;
    }

    const { textarea, text, duration, displayMode, animation } = getTextToolPayload();
    if (!text) {
        showToast('Enter text first', 'warning');
        return;
    }

    const newScene = buildTextSceneFromTool(text, duration, displayMode, animation);
    const insertIndex = getTextToolInsertIndex();
    EditorState.scenes.splice(insertIndex, 0, newScene);
    recordEdit(`Add text scene (Scene ${newScene.id})`, newScene.id, 'scene_add', null, cloneScene(newScene));
    syncTimelineAfterSceneStructureChange(newScene.id, false);

    if (textarea) textarea.value = '';
    renderTextToolState();
    showToast('Text scene added to timeline', 'success');
}

function addTextOverlayFromTool() {
    if (!EditorState.project) {
        showToast('Load a project first', 'warning');
        return;
    }

    const { textarea, text, duration, displayMode, animation } = getTextToolPayload();
    if (!text) {
        showToast('Enter text first', 'warning');
        return;
    }

    const scene = getTextOverlayTargetScene();
    if (!scene) {
        showToast('Select an image or video scene first', 'warning');
        return;
    }
    if (hasSceneTextOverlay(scene)) {
        showToast('Selected scene already has a text overlay', 'warning');
        return;
    }

    const oldValue = {
        text_content: scene.text_content,
        text_timeline_offset: scene.text_timeline_offset,
        text_overlay_duration: scene.text_overlay_duration,
        text_background_enabled: scene.text_background_enabled,
        text_background_color: scene.text_background_color
    };

    scene.text_content = text;
    scene.text_timeline_offset = 0;
    scene.text_overlay_duration = Math.min(duration, Math.max(MIN_TEXT_OVERLAY_DURATION, scene.duration || duration));
    scene.text_color = scene.text_color || 'white';
    scene.text_size = scene.text_size || 72;
    if (scene.text_hide_captions === undefined) scene.text_hide_captions = true;
    scene.font_family = scene.font_family || 'Inter';
    scene.font_style = scene.font_style || 'bold';
    scene.text_align = scene.text_align || 'center';
    scene.vertical_align = scene.vertical_align || 'center';
    if (typeof scene.text_background_enabled !== 'boolean') scene.text_background_enabled = false;
    scene.text_background_color = scene.text_background_color || '#000000';
    if (!scene.text_display_mode) scene.text_display_mode = displayMode || 'emphasis';
    if (!scene.text_hook_animation) {
        _migrateToHookAnimation(scene);
        const parts = _resolveHookParts(scene.text_hook_animation);
        scene.text_animation = parts.animation;
        scene.text_emphasis = parts.emphasis;
    }
    normalizeSceneTextOverlay(scene);

    recordEdit(`Add text overlay (Scene ${scene.id})`, scene.id, 'text_overlay', oldValue, {
        text_content: scene.text_content,
        text_timeline_offset: scene.text_timeline_offset,
        text_overlay_duration: scene.text_overlay_duration,
        text_background_enabled: scene.text_background_enabled,
        text_background_color: scene.text_background_color
    });

    renderTimeline();
    if (EditorState.preview) {
        EditorState.preview.setScenes(EditorState.scenes);
        EditorState.preview.seek(EditorState.playbackPosition);
    }
    selectTextOverlay(scene.id);
    saveProjectEdits();

    if (textarea) textarea.value = '';
    renderTextToolState();
    showToast('Text overlay added to selected scene', 'success');
}

function setupTextTool() {
    const textarea = document.getElementById('text-tool-content');
    const addSceneBtn = document.getElementById('text-add-scene');
    const addOverlayBtn = document.getElementById('text-add-overlay');
    const durationInput = document.getElementById('text-tool-duration');
    if (!textarea || !addSceneBtn || !addOverlayBtn || !durationInput) return;
    if (textarea.dataset.bound === '1') return;

    textarea.dataset.bound = '1';
    textarea.addEventListener('input', renderTextToolState);
    durationInput.addEventListener('input', renderTextToolState);
    addSceneBtn.addEventListener('click', addTextSceneFromTool);
    addOverlayBtn.addEventListener('click', addTextOverlayFromTool);

    // Display mode toggle buttons
    const modeFullBtn = document.getElementById('text-tool-mode-full');
    const modeEmphasisBtn = document.getElementById('text-tool-mode-emphasis');
    modeFullBtn?.addEventListener('click', () => {
        modeFullBtn.classList.add('active');
        modeEmphasisBtn?.classList.remove('active');
    });
    modeEmphasisBtn?.addEventListener('click', () => {
        modeEmphasisBtn.classList.add('active');
        modeFullBtn?.classList.remove('active');
    });

    // Set default animation based on project tone
    const animSelect = document.getElementById('text-tool-animation');
    if (animSelect) {
        const defaultAnim = getDefaultTextAnimation();
        if (animSelect.querySelector(`option[value="${defaultAnim}"]`)) {
            animSelect.value = defaultAnim;
        }
    }

    renderTextToolState();
}

function isVoiceAudible() {
    const voiceTrack = getVoiceTrack();
    if (!voiceTrack?.loaded || !voiceTrack.element || voiceTrack.muted) return false;
    if (voiceTrack.element.paused) return false;
    const vol = Number(voiceTrack.volume ?? 1.0);
    return vol > 0.001;
}

function getEffectiveTrackVolume(track, requestedVol, voiceAudible = isVoiceAudible()) {
    const vol = Number(requestedVol ?? track?.volume ?? 1.0);
    if (!track || isTrackPlaybackSuppressed(track)) return 0;
    if (track.type === 'music' && track.duckingEnabled && voiceAudible) {
        const duck = Math.max(
            MIN_MUSIC_DUCKING_LEVEL,
            Number(track.duckingLevel ?? DEFAULT_MUSIC_DUCKING_LEVEL)
        );
        return Math.min(duck, vol);
    }
    return vol;
}

function isTrackPlaybackSuppressed(track) {
    if (!track) return true;
    const disabledTracks = EditorState.disabledTracks || new Set();
    const trackKey = `audio-${track.id}`;
    const legacyMusicDisabled = track.type === 'music' && disabledTracks.has('bgmusic');
    const soloSuppressed = EditorState.soloTrackId != null && track.id !== EditorState.soloTrackId;
    return !!(
        EditorState.isMuted
        || track.muted
        || soloSuppressed
        || disabledTracks.has(trackKey)
        || disabledTracks.has('audio')
        || legacyMusicDisabled
    );
}

function toggleSolo(trackId) {
    if (EditorState.soloTrackId === trackId) {
        // Unsolo — restore all tracks to their pre-solo mute state
        EditorState.soloTrackId = null;
        EditorState.audioTracks.forEach(t => {
            if (t._preSoloMuted !== undefined) {
                t.muted = t._preSoloMuted;
                t._preSoloMuted = undefined;
            }
            applyTrackVolumeLive(t, t.volume);
        });
    } else {
        // Solo this track — save mute states, mute all others
        EditorState.soloTrackId = trackId;
        EditorState.audioTracks.forEach(t => {
            t._preSoloMuted = t.muted;
            if (t.id !== trackId) {
                t.muted = true;
            } else {
                t.muted = false;
            }
            applyTrackVolumeLive(t, t.volume);
        });
    }
    renderAllAudioTracks();
}

function ensureTrackGainNode(track) {
    if (!track?.element || track._gainNode) return;
    const audio = track.element;
    try {
        if (!EditorState._audioCtx) {
            EditorState._audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        }
        const ctx = EditorState._audioCtx;
        const source = ctx.createMediaElementSource(audio);
        const gain = ctx.createGain();
        gain.gain.value = getEffectiveTrackVolume(track, track.volume, isVoiceAudible());
        source.connect(gain);
        gain.connect(ctx.destination);
        track._gainNode = gain;
        audio.muted = false;
        audio.volume = 1.0;
    } catch (e) {
        audio.muted = false;
        audio.volume = Math.min(1.0, getEffectiveTrackVolume(track, track.volume, isVoiceAudible()));
    }
}

async function ensureAudioContextReady() {
    if (!EditorState._audioCtx) return null;
    if (EditorState._audioCtx.state === 'suspended') {
        try {
            await EditorState._audioCtx.resume();
        } catch (e) {
            console.warn('AudioContext resume failed:', e);
        }
    }
    return EditorState._audioCtx;
}

function applyTrackVolumeLive(track, requestedVol = track?.volume, options = {}) {
    if (!track?.element) return;
    // Don't override gain while user is dragging the volume slider
    if (track._volumeDragging) return;

    const nextVol = Number.isFinite(+requestedVol) ? Math.max(0, +requestedVol) : Number(track.volume ?? 1.0);
    track.volume = nextVol;
    ensureTrackGainNode(track);

    const applyVolume = () => {
        const effectiveVol = getEffectiveTrackVolume(track, track.volume, isVoiceAudible());
        track.element.muted = false;
        if (track._gainNode && EditorState._audioCtx) {
            try {
                const gain = track._gainNode.gain;
                const now = EditorState._audioCtx.currentTime;
                gain.cancelScheduledValues(now);
                gain.setValueAtTime(gain.value, now);
                gain.linearRampToValueAtTime(effectiveVol, now + 0.05);
            } catch (_) {
                track._gainNode.gain.value = effectiveVol;
            }
            track.element.volume = 1.0;
        } else {
            track.element.volume = Math.min(1.0, effectiveVol);
        }
    };

    if (options.resumeContext) {
        ensureAudioContextReady().finally(applyVolume);
    } else {
        applyVolume();
    }
}

/**
 * Generate waveform data from an audio track's element.
 * Fetches the audio file, decodes it, and stores sampled peaks on track._waveformData.
 */
async function generateWaveformData(track) {
    if (!track?.path || track._waveformData || track._waveformLoading) return;
    track._waveformLoading = true;
    try {
        if (!EditorState._audioCtx) {
            EditorState._audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        }
        const ctx = EditorState._audioCtx;
        const resp = await fetch(track.path);
        if (!resp.ok) throw new Error('fetch failed');
        const arrayBuf = await resp.arrayBuffer();
        const audioBuffer = await ctx.decodeAudioData(arrayBuf);
        const rawData = audioBuffer.getChannelData(0);
        // Down-sample to ~200 peaks for efficient rendering
        const samples = 200;
        const blockSize = Math.floor(rawData.length / samples);
        const peaks = new Float32Array(samples);
        for (let i = 0; i < samples; i++) {
            let sum = 0;
            const start = i * blockSize;
            for (let j = start; j < start + blockSize; j++) {
                sum += Math.abs(rawData[j]);
            }
            peaks[i] = sum / blockSize;
        }
        // Normalize peaks to 0-1
        const maxPeak = Math.max(...peaks) || 1;
        for (let i = 0; i < samples; i++) peaks[i] /= maxPeak;
        track._waveformData = peaks;
    } catch (e) {
        console.warn('Waveform generation failed for', track.file, e);
    }
    track._waveformLoading = false;
}

/**
 * Draw waveform onto a canvas element using the track's _waveformData.
 * Applies fade in/out envelope visually to the waveform bars and draws fade curves.
 */
function drawWaveformCanvas(canvas, track) {
    if (!canvas || !track?._waveformData) return;
    const peaks = track._waveformData;
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const w = Math.max(1, canvas.clientWidth);
    const h = Math.max(1, canvas.clientHeight);
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    const color = track.color || AUDIO_TRACK_COLORS[track.type] || AUDIO_TRACK_COLORS.voice;
    const trackDur = getTrackVisibleDuration(track) || track.duration || 1;
    const sourceDur = Math.max(track.duration || trackDur || 1, 0.1);
    const startOffset = getTrackStartOffset(track);
    const fadeIn = track.fadeIn || 0;
    const fadeOut = track.fadeOut || 0;
    const fadeInFrac = Math.min(1, fadeIn / trackDur);
    const fadeOutFrac = Math.min(1, fadeOut / trackDur);

    // Keep waveform density tied to the source duration so trimming crops instead of stretching.
    const barColor = color.replace(/[\d.]+\)$/, '0.4)');
    const cycleWidth = Math.max(1, timeToPixels(sourceDur));
    const barWidth = Math.max(1, cycleWidth / peaks.length);
    const barDrawWidth = Math.max(1, barWidth - 0.75);
    const barCount = Math.ceil(w / barWidth);
    const midY = h / 2;
    for (let i = 0; i < barCount; i++) {
        const x = i * barWidth;
        const frac = x / w;
        const sourceTime = startOffset + (x / Math.max(1, cycleWidth)) * sourceDur;
        const peakIndex = track.loop
            ? Math.floor(((sourceTime % sourceDur) / sourceDur) * peaks.length)
            : Math.min(peaks.length - 1, Math.floor((Math.min(sourceTime, sourceDur) / sourceDur) * peaks.length));
        let envelope = 1.0;
        if (fadeInFrac > 0 && frac < fadeInFrac) {
            envelope = frac / fadeInFrac;
        }
        if (fadeOutFrac > 0 && frac > 1 - fadeOutFrac) {
            envelope = Math.min(envelope, (1 - frac) / fadeOutFrac);
        }
        const peak = peaks[Math.max(0, Math.min(peaks.length - 1, peakIndex))];
        const barH = Math.max(1, peak * (h * 0.85) * envelope);
        ctx.fillStyle = barColor;
        ctx.fillRect(x, midY - barH / 2, Math.min(barDrawWidth, w - x), barH);
    }

    // Draw fade-in curve
    if (fadeInFrac > 0) {
        const fadeInPx = fadeInFrac * w;
        ctx.beginPath();
        ctx.moveTo(0, h);
        // Quadratic curve from bottom-left to top at fade end
        ctx.quadraticCurveTo(fadeInPx * 0.5, h, fadeInPx, 0);
        ctx.lineTo(fadeInPx, h);
        ctx.closePath();
        ctx.fillStyle = 'rgba(0, 0, 0, 0.25)';
        ctx.fill();
        // Curve line
        ctx.beginPath();
        ctx.moveTo(0, h);
        ctx.quadraticCurveTo(fadeInPx * 0.5, h, fadeInPx, 0);
        ctx.strokeStyle = color.replace(/[\d.]+\)$/, '0.8)');
        ctx.lineWidth = 1.5;
        ctx.stroke();
    }

    // Draw fade-out curve
    if (fadeOutFrac > 0) {
        const fadeOutStartPx = (1 - fadeOutFrac) * w;
        ctx.beginPath();
        ctx.moveTo(fadeOutStartPx, 0);
        // Quadratic curve from top at fade start to bottom-right
        ctx.quadraticCurveTo(fadeOutStartPx + (w - fadeOutStartPx) * 0.5, h, w, h);
        ctx.lineTo(w, 0);
        ctx.lineTo(fadeOutStartPx, 0);
        ctx.closePath();
        ctx.fillStyle = 'rgba(0, 0, 0, 0.25)';
        ctx.fill();
        // Curve line
        ctx.beginPath();
        ctx.moveTo(fadeOutStartPx, 0);
        ctx.quadraticCurveTo(fadeOutStartPx + (w - fadeOutStartPx) * 0.5, h, w, h);
        ctx.strokeStyle = color.replace(/[\d.]+\)$/, '0.8)');
        ctx.lineWidth = 1.5;
        ctx.stroke();
    }

    // Draw ducking envelope overlay for music tracks
    if (track.type === 'music' && track.duckingEnabled) {
        const voiceTrack = EditorState.audioTracks.find(t => t.type === 'voice' && !t.muted);
        if (voiceTrack) {
            const totalDur = getTotalDuration();
            const voiceStart = getTrackTimelineOffset(voiceTrack);
            const voiceEnd = getTrackTimelineEnd(voiceTrack, totalDur) || totalDur;
            const musicStart = getTrackTimelineOffset(track);
            const musicDur = trackDur;
            const pxPerSec = w / musicDur;
            const duckStartPx = Math.max(0, (voiceStart - musicStart) * pxPerSec);
            const duckEndPx = Math.min(w, (voiceEnd - musicStart) * pxPerSec);

            // Only draw if the ducked region is visible on this canvas
            if (duckEndPx > 0 && duckStartPx < w) {
                const duckLevel = Math.max(0, Math.min(1, track.duckingLevel || 0));
                const duckHeight = h * (1 - duckLevel);
                const rampPx = Math.min(1.5 * pxPerSec, (duckEndPx - duckStartPx) * 0.3);

                // Semi-transparent ducking region overlay
                ctx.save();
                ctx.globalAlpha = 0.12;
                ctx.fillStyle = '#f59e0b';
                ctx.beginPath();
                ctx.moveTo(Math.max(0, duckStartPx - rampPx), 0);
                ctx.lineTo(duckStartPx, duckHeight);
                ctx.lineTo(duckEndPx, duckHeight);
                ctx.lineTo(Math.min(w, duckEndPx + rampPx), 0);
                ctx.lineTo(Math.max(0, duckStartPx - rampPx), 0);
                ctx.closePath();
                ctx.fill();
                ctx.restore();

                // Dashed line at the ducking level across the ducked region
                ctx.save();
                ctx.globalAlpha = 0.35;
                ctx.strokeStyle = '#f59e0b';
                ctx.lineWidth = 1;
                ctx.setLineDash([4, 3]);
                ctx.beginPath();
                ctx.moveTo(duckStartPx, duckHeight);
                ctx.lineTo(duckEndPx, duckHeight);
                ctx.stroke();
                ctx.setLineDash([]);
                ctx.restore();
            }
        }
    }
}

/**
 * Select an audio track for the detail panel
 */
function selectAudioTrack(trackId) {
    // Deselect scenes
    EditorState.selectedScene = null;
    EditorState.selectedTextOverlaySceneId = null;
    EditorState.selectedCaptionIdx = null;
    EditorState.selectedOverlayIdx = null;
    document.querySelectorAll('.scene-clip.selected').forEach(el => el.classList.remove('selected'));
    document.querySelectorAll('.text-clip.selected').forEach(el => el.classList.remove('selected'));
    document.querySelectorAll('.caption-clip.selected').forEach(el => el.classList.remove('selected'));

    // Deselect previous audio clip
    document.querySelectorAll('.audio-clip-universal.selected').forEach(el => el.classList.remove('selected'));

    const track = getAudioTrackById(trackId);
    EditorState.selectedAudioTrack = track || null;

    // Highlight selected clip
    if (track) {
        const clip = document.querySelector(`.audio-clip-universal[data-track-id="${trackId}"]`);
        if (clip) clip.classList.add('selected');
    }

    renderAudioProperties();
    renderTextToolState();
}

/**
 * Render audio track properties in the detail panel
 */
function renderAudioProperties() {
    if (!elements.sceneProperties) return;

    const track = EditorState.selectedAudioTrack;
    if (!track) {
        // Restore default placeholder if no scene selected either
        if (!EditorState.selectedScene) {
            elements.sceneProperties.innerHTML = '<div class="detail-placeholder">Select a scene to edit</div>';
        }
        return;
    }

    const volPct = Math.round(track.volume * 100);
    const trackLabel = track.label || (track.type === 'voice' ? 'Voice' : track.type === 'music' ? 'Music' : 'SFX');
    const color = track.color || AUDIO_TRACK_COLORS[track.type] || AUDIO_TRACK_COLORS.voice;

    elements.sceneProperties.innerHTML = `
        <div class="audio-props-header">
            <span class="audio-props-icon" style="background:${color}">
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 010 14.14M15.54 8.46a5 5 0 010 7.08"/></svg>
            </span>
            <span class="audio-props-title">${trackLabel}</span>
        </div>
        ${track.file ? `
        <div class="property-group">
            <label>File</label>
            <span class="property-value" style="max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${track.file}">${track.file}</span>
        </div>
        <div class="property-group">
            <label>Duration</label>
            <span class="property-value">${formatTimestamp(getTrackVisibleDuration(track) || track.duration)}</span>
        </div>
        ` : ''}
        <div class="property-group">
            <label>Volume</label>
            <div class="audio-prop-slider-wrap">
                <input type="range" class="audio-prop-slider" id="audio-prop-volume" min="0" max="300" value="${volPct}">
                <span class="audio-prop-slider-val" id="audio-prop-volume-val">${volPct}%</span>
            </div>
        </div>
        <div class="property-group">
            <label>Fade in</label>
            <div class="audio-prop-slider-wrap">
                <input type="range" class="audio-prop-slider" id="audio-prop-fade-in" min="0" max="100" step="1" value="${Math.round(track.fadeIn * 10)}">
                <span class="audio-prop-slider-val" id="audio-prop-fade-in-val">${track.fadeIn.toFixed(1)}s</span>
            </div>
        </div>
        <div class="property-group">
            <label>Fade out</label>
            <div class="audio-prop-slider-wrap">
                <input type="range" class="audio-prop-slider" id="audio-prop-fade-out" min="0" max="100" step="1" value="${Math.round(track.fadeOut * 10)}">
                <span class="audio-prop-slider-val" id="audio-prop-fade-out-val">${track.fadeOut.toFixed(1)}s</span>
            </div>
        </div>
        ${track.type === 'music' ? `
        <div class="property-group">
            <label>Loop</label>
            <label class="toggle-switch-small">
                <input type="checkbox" id="audio-prop-loop" ${track.loop ? 'checked' : ''}>
                <span class="toggle-slider-small"></span>
            </label>
        </div>
        <div class="property-group">
            <label>Voice ducking</label>
            <label class="toggle-switch-small">
                <input type="checkbox" id="audio-prop-ducking" ${track.duckingEnabled ? 'checked' : ''}>
                <span class="toggle-slider-small"></span>
            </label>
        </div>
        ` : ''}
    `;

    // Wire volume slider
    const volSlider = document.getElementById('audio-prop-volume');
    const volLabel = document.getElementById('audio-prop-volume-val');
    volSlider?.addEventListener('input', () => {
        const vol = parseInt(volSlider.value) / 100;
        _saveVolume(track.type, vol);
        volLabel.textContent = `${volSlider.value}%`;
        applyTrackVolumeLive(track, vol, { resumeContext: true });
    });
    volSlider?.addEventListener('change', () => saveProjectEdits());

    // Helper to redraw the waveform for the current track
    const redrawTrackWaveform = () => {
        const c = document.querySelector(`.audio-waveform-canvas[data-track-id="${track.id}"]`);
        drawWaveformCanvas(c, track);
    };

    // Wire fade in slider
    const fadeInSlider = document.getElementById('audio-prop-fade-in');
    const fadeInLabel = document.getElementById('audio-prop-fade-in-val');
    fadeInSlider?.addEventListener('input', () => {
        const val = parseInt(fadeInSlider.value) / 10;
        track.fadeIn = val;
        fadeInLabel.textContent = `${val.toFixed(1)}s`;
        redrawTrackWaveform();
    });
    fadeInSlider?.addEventListener('change', () => {
        recordEdit(`Change ${trackLabel} fade in`, track.id, 'fadeIn', null, track.fadeIn);
        saveProjectEdits();
    });

    // Wire fade out slider
    const fadeOutSlider = document.getElementById('audio-prop-fade-out');
    const fadeOutLabel = document.getElementById('audio-prop-fade-out-val');
    fadeOutSlider?.addEventListener('input', () => {
        const val = parseInt(fadeOutSlider.value) / 10;
        track.fadeOut = val;
        fadeOutLabel.textContent = `${val.toFixed(1)}s`;
        redrawTrackWaveform();
    });
    fadeOutSlider?.addEventListener('change', () => {
        recordEdit(`Change ${trackLabel} fade out`, track.id, 'fadeOut', null, track.fadeOut);
        saveProjectEdits();
    });

    // Wire loop toggle
    const loopToggle = document.getElementById('audio-prop-loop');
    loopToggle?.addEventListener('change', () => {
        const oldLoop = track.loop;
        track.loop = loopToggle.checked;
        if (track.element) track.element.loop = track.loop;
        renderAllAudioTracks();
        recordEdit(`Toggle ${trackLabel} loop`, track.id, 'loop', oldLoop, track.loop);
    });

    // Wire ducking toggle
    const duckingToggle = document.getElementById('audio-prop-ducking');
    duckingToggle?.addEventListener('change', () => {
        const oldDucking = track.duckingEnabled;
        track.duckingEnabled = duckingToggle.checked;
        recordEdit(`Toggle ${trackLabel} ducking`, track.id, 'duckingEnabled', oldDucking, track.duckingEnabled);
    });
}

/**
 * Apply fade in/out gain envelopes during real-time playback.
 * Called from onTimeUpdate.
 */
function applyAudioFades() {
    for (const track of EditorState.audioTracks) {
        if (!track.element || track.muted || !track.file) continue;
        const fadeIn = track.fadeIn || 0;
        const fadeOut = track.fadeOut || 0;
        if (!fadeIn && !fadeOut) continue;

        const currentTime = track.element.currentTime;
        const clipTime = currentTime - getTrackStartOffset(track);
        const trackEnd = getTrackVisibleDuration(track);
        if (!trackEnd) continue;

        let fadeMultiplier = 1.0;
        // Fade in
        if (fadeIn > 0 && clipTime < fadeIn) {
            fadeMultiplier = Math.min(fadeMultiplier, Math.max(0, clipTime) / fadeIn);
        }
        // Fade out
        if (fadeOut > 0 && clipTime > trackEnd - fadeOut) {
            const remaining = trackEnd - clipTime;
            fadeMultiplier = Math.min(fadeMultiplier, Math.max(0, remaining / fadeOut));
        }

        const baseVol = getEffectiveTrackVolume(track, track.volume, isVoiceAudible());
        if (track._gainNode && EditorState._audioCtx) {
            const now = EditorState._audioCtx.currentTime;
            track._gainNode.gain.cancelScheduledValues(now);
            track._gainNode.gain.setValueAtTime(baseVol * fadeMultiplier, now);
        } else {
            track.element.volume = Math.min(1.0, baseVol * fadeMultiplier);
        }
    }
}

// Load saved settings from localStorage
function loadSavedSettings() {
    const savedZoom = localStorage.getItem(STORAGE_KEYS.ZOOM_LEVEL);
    const savedLoop = localStorage.getItem(STORAGE_KEYS.LOOP_STATE);

    return {
        zoomLevel: savedZoom ? parseFloat(savedZoom) : 1,
        isLooping: savedLoop === 'true',
        timelineHeight: parseInt(localStorage.getItem(STORAGE_KEYS.TIMELINE_HEIGHT)) || 180
    };
}

const savedSettings = loadSavedSettings();

// Editor State
const EditorState = {
    project: null,
    scenes: [],
    originalScenes: [],  // Original scenes for comparison/reset
    selectedScene: null,
    selectedTextOverlaySceneId: null,
    selectedAudioTrack: null,  // Currently selected audio track for detail panel
    mediaFolder: null,
    mediaFiles: new Map(),
    playbackPosition: 0,
    isPlaying: false,
    isLooping: savedSettings.isLooping,  // Loop playback mode - restored from localStorage
    zoomLevel: savedSettings.zoomLevel,   // Restored from localStorage
    timelineHeight: savedSettings.timelineHeight, // Restored from localStorage
    pixelsPerSecond: 20,
    preview: null,  // CanvasPreview instance
    audio: null,    // DEPRECATED — use audioTracks[0] (voice)
    audioElement: null,  // DEPRECATED — use audioTracks[0].element
    audioTracks: [],     // Universal multi-track audio array
    isMuted: false,  // Audio mute state
    videoAudioEnabled: false,  // Video embedded audio (muted by default, user can enable)
    editHistory: [],  // History of edits for undo
    historyIndex: -1,  // Current position in history (-1 = no history)
    sceneErrors: new Map(),  // Map of sceneId -> [error messages]
    savedAudioSettings: null,  // Saved audio settings from localStorage
    voiceLoadPromise: Promise.resolve({ status: 'idle', reason: 'init' }),
    voiceLoadToken: 0,
    activeBootstrapId: 0,
    captionData: null,      // Caption data { captions: [], style: {} }
    captionsEnabled: false, // Whether caption track is visible
    selectedCaptionIdx: null, // Currently selected caption index for detail panel
    selectedOverlayIdx: null, // Currently selected overlay index for detail panel
    overlays: [],           // Stacked overlay objects {url, opacity, blend} (bottom → top)
    grainOverlay: null,     // Optional animated white-dot grain config (export-time only)
    selectedExportProfile: 'yt_shorts',  // Export profile ID
    bgMusic: null,          // DEPRECATED — use audioTracks (type: 'music')
    bgMusicElement: null,   // DEPRECATED — use audioTracks[].element
    soloTrackId: null,         // Currently soloed audio track ID (null = no solo)
    disabledTracks: new Set(), // Keep track of which tracks are disabled
    storageEnabled: STS.get('sts-editor-storage') !== 'false', // localStorage toggle (default ON)
    sessionStorageEnabled: STS.get('sts-editor-session-storage') !== 'false' // sessionStorage toggle (default ON)
};

const DEFAULT_GRAIN_OVERLAY = Object.freeze({
    enabled: false,
    opacity: 0.16,
    start: 0.0,
    fade_in: 0.12,
    hold: 0.65,
    fade_out: 1.20,
    noise_strength: 88,
    threshold: 246
});

const OVERLAY_BLEND_MODES = ['normal','screen','multiply','overlay','soft-light','hard-light','lighten','darken','color-dodge'];

function normalizeOverlayEntry(entry) {
    if (typeof entry === 'string') return { url: entry, opacity: 1.0, blend: 'normal' };
    return {
        url: entry.url || '',
        opacity: Number.isFinite(+entry.opacity) ? Math.max(0, Math.min(1, +entry.opacity)) : 1.0,
        blend: OVERLAY_BLEND_MODES.includes(entry.blend) ? entry.blend : 'normal'
    };
}

function findOverlayIdx(url) {
    return EditorState.overlays.findIndex(o => o.url === url);
}

function normalizeGrainOverlay(cfg) {
    const src = cfg || {};
    return {
        enabled: !!src.enabled,
        opacity: Number.isFinite(+src.opacity) ? +src.opacity : DEFAULT_GRAIN_OVERLAY.opacity,
        start: Number.isFinite(+src.start) ? +src.start : DEFAULT_GRAIN_OVERLAY.start,
        fade_in: Number.isFinite(+src.fade_in) ? +src.fade_in : (Number.isFinite(+src.fadeIn) ? +src.fadeIn : DEFAULT_GRAIN_OVERLAY.fade_in),
        hold: Number.isFinite(+src.hold) ? +src.hold : DEFAULT_GRAIN_OVERLAY.hold,
        fade_out: Number.isFinite(+src.fade_out) ? +src.fade_out : (Number.isFinite(+src.fadeOut) ? +src.fadeOut : DEFAULT_GRAIN_OVERLAY.fade_out),
        noise_strength: Number.isFinite(+src.noise_strength) ? +src.noise_strength : (Number.isFinite(+src.noiseStrength) ? +src.noiseStrength : DEFAULT_GRAIN_OVERLAY.noise_strength),
        threshold: Number.isFinite(+src.threshold) ? +src.threshold : DEFAULT_GRAIN_OVERLAY.threshold
    };
}

// ============================================================
// Edit History & Persistence System
// ============================================================

/**
 * Get localStorage key for project edits
 */
function getProjectEditsKey(projectId) {
    return STORAGE_KEYS.PROJECT_EDITS + projectId;
}

/**
 * Get localStorage key for project history
 */
function getProjectHistoryKey(projectId) {
    return STORAGE_KEYS.PROJECT_HISTORY + projectId;
}

/**
 * Save current scene edits to localStorage
 */
function saveProjectEdits() {
    if (!EditorState.project?.id || !EditorState.storageEnabled) return;

    const edits = EditorState.scenes.map(scene => ({
        id: scene.id,
        duration: scene.duration,
        visual_fx: scene.visual_fx,
        text_content: scene.text_content,
        text_color: scene.text_color,
        text_size: scene.text_size,
        font_family: scene.font_family,
        font_style: scene.font_style,
        text_align: scene.text_align,
        vertical_align: scene.vertical_align,
        text_x: scene.text_x,
        text_y: scene.text_y,
        text_timeline_offset: scene.text_timeline_offset ?? 0,
        text_overlay_duration: scene.text_overlay_duration ?? null,
        text_background_enabled: !!scene.text_background_enabled,
        text_background_color: scene.text_background_color || '#000000',
        text_display_mode: scene.text_display_mode || null,
        text_hook_animation: scene.text_hook_animation || null,
        text_animation: scene.text_animation || null
    }));

    // Include audio settings if audio is loaded
    const audioSettings = EditorState.audio?.loaded ? {
        trimmedDuration: EditorState.audio.trimmedDuration,
        timelineOffset: EditorState.audio.timelineOffset || 0,
        startOffset: EditorState.audio.startOffset || 0,
        file: EditorState.audio.file || null
    } : null;

    const data = {
        projectId: EditorState.project.id,
        savedAt: new Date().toISOString(),
        edits: edits,
        audio: audioSettings
    };

    try {
        localStorage.setItem(getProjectEditsKey(EditorState.project.id), JSON.stringify(data));
        console.log('Project edits saved to localStorage');
    } catch (e) {
        console.warn('Failed to save project edits:', e);
    }

    // Debounced save to server
    _debouncedServerSave();
}

// ---- Server-side project persistence ----

let _serverSaveTimer = null;
let _serverSaveRetries = 0;
const _MAX_SAVE_RETRIES = 3;
const _SAVE_DEBOUNCE_MS = 2000;
let _saveStatusTimer = null;

function cancelPendingProjectSave() {
    if (_serverSaveTimer) {
        clearTimeout(_serverSaveTimer);
        _serverSaveTimer = null;
    }
    _serverSaveRetries = 0;
}

function clearEditorBootCaches() {
    try { sessionStorage.removeItem('sts-staged-timeline'); } catch (_) { /* ignore */ }
    try { sessionStorage.removeItem('sts-editor-saved-state'); } catch (_) { /* ignore */ }
    try { localStorage.removeItem('sts-editor-boot-project'); } catch (_) { /* ignore */ }
    try { localStorage.removeItem('sts-editor-scenes'); } catch (_) { /* ignore */ }
    try { localStorage.removeItem('sts-editor-source-folder'); } catch (_) { /* ignore */ }
}

function _debouncedServerSave() {
    if (_serverSaveTimer) clearTimeout(_serverSaveTimer);
    _serverSaveTimer = setTimeout(() => saveProjectToServer(), _SAVE_DEBOUNCE_MS);
}

function _showSaveStatus(status, text) {
    const el = document.getElementById('save-status');
    if (!el) return;
    if (_saveStatusTimer) clearTimeout(_saveStatusTimer);
    el.style.display = '';
    el.className = 'save-status ' + status;
    el.textContent = text;
    if (status === 'saved') {
        _saveStatusTimer = setTimeout(() => { el.classList.add('fade-out'); }, 2000);
        _saveStatusTimer = setTimeout(() => { el.style.display = 'none'; }, 2500);
    }
}

function _buildSavePayload() {
    normalizeTimelineDurations();
    const captions = EditorState.captionData
        ? {
            ...EditorState.captionData,
            source_folder: EditorState.project.sourceFolder || EditorState.captionData.source_folder || ''
        }
        : null;

    return {
        project_id: EditorState.project.id,
        project_name: EditorState.project.name || EditorState.project.id,
        source_folder: EditorState.project.sourceFolder || '',
        total_duration: _roundTimelineSeconds(getScenesDuration()),
        scene_count: EditorState.scenes.length,
        scenes: EditorState.scenes.map(s => ({
            id: s.id, type: s.type, duration: s.duration,
            visual_fx: s.visual_fx,
            image_url: s.mediaUrl || s.image_url || '',
            mediaUrl: s.mediaUrl || '',
            image: s.image || '',
            image_prompt: s.image_prompt || '',
            text_content: s.text_content || null,
            text_color: s.text_color, text_size: s.text_size,
            font_family: s.font_family, font_style: s.font_style,
            text_align: s.text_align, vertical_align: s.vertical_align,
            text_x: s.text_x ?? null, text_y: s.text_y ?? null,
            text_timeline_offset: s.text_timeline_offset ?? 0,
            text_overlay_duration: s.text_overlay_duration ?? null,
            text_background_enabled: !!s.text_background_enabled,
            text_background_color: s.text_background_color || '#000000',
            text_display_mode: s.text_display_mode || null,
            text_hook_animation: s.text_hook_animation || null,
            text_animation: s.text_animation || null,
            timestamp: s.timestamp || 0, status: s.status || 'ready',
            isVideo: !!s.isVideo, script: s.script || '',
            narrative_role: s.narrative_role || s.scene_type || '',
            filler_shift: s.filler_shift || 0,
            segment_start: s.segment_start ?? null,
            segment_end: s.segment_end ?? null,
            segment_duration: s.segment_duration ?? null
        })),
        audio_tracks: EditorState.audioTracks.map(t => {
            const base = {
                id: t.id, label: t.label, type: t.type,
                file: t.file || null, path: t.path || null,
                duration: t.duration || 0,
                timelineOffset: t.timelineOffset || 0,
                startOffset: t.startOffset || 0,
                trimmedDuration: t.trimmedDuration || null,
                volume: t.volume ?? 1.0, loop: !!t.loop, muted: !!t.muted,
                duckingEnabled: !!t.duckingEnabled,
                duckingLevel: t.duckingLevel ?? DEFAULT_MUSIC_DUCKING_LEVEL,
                fadeIn: t.fadeIn || 0, fadeOut: t.fadeOut || 0,
            };
            if (t.clips && t.clips.length > 0) {
                base.clips = t.clips.map(c => ({
                    id: c.id, file: c.file, path: c.path,
                    label: c.label, duration: c.duration || 0,
                    offset: c.offset || 0,
                }));
            }
            return base;
        }),
        captions,
        captionsEnabled: !!EditorState.captionsEnabled,
        overlays: EditorState.overlays.length ? EditorState.overlays : null,
        grain_overlay: normalizeGrainOverlay(EditorState.grainOverlay),
        edit_history: (EditorState.editHistory || []).slice(-50),
        history_index: EditorState.historyIndex,
        disabled_tracks: [...(EditorState.disabledTracks || [])]
    };
}

async function saveProjectToServer() {
    if (!EditorState.project?.id) return;

    _showSaveStatus('saving', 'Saving...');
    const payload = _buildSavePayload();

    try {
        const res = await fetch('/api/editor/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        if (!res.ok) throw new Error(`Server ${res.status}`);
        _serverSaveRetries = 0;
        _showSaveStatus('saved', 'Saved');
        // Mark project as WIP after first successful save
        if (EditorState.project) {
            EditorState.project.loadedFrom = 'wip';
            try {
                localStorage.setItem('sts-editor-last-saved-project-id', EditorState.project.id);
            } catch (_) { /* ignore */ }
        }
    } catch (e) {
        _serverSaveRetries++;
        if (_serverSaveRetries <= _MAX_SAVE_RETRIES) {
            const delay = _SAVE_DEBOUNCE_MS * _serverSaveRetries;
            console.warn(`Save failed (attempt ${_serverSaveRetries}/${_MAX_SAVE_RETRIES}), retrying in ${delay}ms:`, e.message);
            _showSaveStatus('save-error', `Save failed, retrying...`);
            _serverSaveTimer = setTimeout(() => saveProjectToServer(), delay);
        } else {
            console.error('Save failed after max retries:', e.message);
            _showSaveStatus('save-error', 'Save failed');
            _serverSaveRetries = 0;
        }
    }
}

/**
 * Load saved edits from localStorage and apply to scenes
 */
function loadProjectEdits() {
    if (!EditorState.project?.id) return false;

    try {
        const saved = localStorage.getItem(getProjectEditsKey(EditorState.project.id));
        if (!saved) return false;

        const data = JSON.parse(saved);
        if (data.projectId !== EditorState.project.id) return false;

        // Apply saved edits to scenes
        let appliedCount = 0;
        for (const edit of data.edits) {
            const scene = EditorState.scenes.find(s => s.id === edit.id);
            if (scene) {
                if (edit.duration !== undefined) scene.duration = edit.duration;
                if (edit.visual_fx !== undefined) scene.visual_fx = edit.visual_fx;
                if (edit.text_content !== undefined) scene.text_content = edit.text_content;
                if (edit.text_color !== undefined) scene.text_color = edit.text_color;
                if (edit.text_size !== undefined) scene.text_size = edit.text_size;
                if (edit.font_family !== undefined) scene.font_family = edit.font_family;
                if (edit.font_style !== undefined) scene.font_style = edit.font_style;
                if (edit.text_align !== undefined) scene.text_align = edit.text_align;
                if (edit.vertical_align !== undefined) scene.vertical_align = edit.vertical_align;
                if (edit.text_x !== undefined) scene.text_x = edit.text_x;
                if (edit.text_y !== undefined) scene.text_y = edit.text_y;
                if (edit.text_timeline_offset !== undefined) scene.text_timeline_offset = edit.text_timeline_offset;
                if (edit.text_overlay_duration !== undefined) scene.text_overlay_duration = edit.text_overlay_duration;
                if (edit.text_background_enabled !== undefined) scene.text_background_enabled = edit.text_background_enabled;
                if (edit.text_background_color !== undefined) scene.text_background_color = edit.text_background_color;
                if (edit.text_display_mode !== undefined) scene.text_display_mode = edit.text_display_mode;
                if (edit.text_hook_animation !== undefined) scene.text_hook_animation = edit.text_hook_animation;
                if (edit.text_animation !== undefined) scene.text_animation = edit.text_animation;
                normalizeSceneTextOverlay(scene);
                appliedCount++;
            }
        }

        // Store saved audio settings to apply after audio loads
        if (data.audio) {
            EditorState.savedAudioSettings = data.audio;
            console.log('Saved audio settings found:', data.audio);
        }

        if (appliedCount > 0) {
            console.log(`Loaded ${appliedCount} saved edits from localStorage`);
            showToast(`Restored ${appliedCount} saved edits`, 'info');
            return true;
        }
    } catch (e) {
        console.warn('Failed to load project edits:', e);
    }
    return false;
}

/**
 * Record an edit action to history
 */
function _updateResetButtonVisibility() {
    const resetBtn = document.getElementById('share-reset-initial');
    if (!resetBtn) return;
    // Always show the button when a project is loaded — the confirmation
    // dialog and backend validation guard against invalid resets.
    resetBtn.style.display = EditorState.project?.id ? '' : 'none';
}

function recordEdit(action, sceneId, field, oldValue, newValue) {
    if (!EditorState.project?.id) return;

    const historyEntry = {
        timestamp: Date.now(),
        action: action,
        sceneId: sceneId,
        field: field,
        oldValue: oldValue,
        newValue: newValue
    };

    // If we're not at the end of history, truncate future entries
    if (EditorState.historyIndex < EditorState.editHistory.length - 1) {
        EditorState.editHistory = EditorState.editHistory.slice(0, EditorState.historyIndex + 1);
    }

    // Add new entry
    EditorState.editHistory.push(historyEntry);
    EditorState.historyIndex = EditorState.editHistory.length - 1;

    // Limit history size
    if (EditorState.editHistory.length > MAX_HISTORY_ENTRIES) {
        EditorState.editHistory.shift();
        EditorState.historyIndex--;
    }

    // Save to localStorage
    saveEditHistory();
    saveProjectEdits();

    // Update undo button state
    updateUndoButton();
    _updateResetButtonVisibility();

    // Re-validate scenes and update error indicators
    validateScenes();
    applySceneErrorStyles();
}

/**
 * Save edit history to localStorage
 */
function saveEditHistory() {
    if (!EditorState.project?.id || !EditorState.storageEnabled) return;

    try {
        const data = {
            projectId: EditorState.project.id,
            history: EditorState.editHistory,
            historyIndex: EditorState.historyIndex
        };
        localStorage.setItem(getProjectHistoryKey(EditorState.project.id), JSON.stringify(data));
    } catch (e) {
        console.warn('Failed to save edit history:', e);
    }
}

/**
 * Load edit history from localStorage
 */
function loadEditHistory() {
    if (!EditorState.project?.id) return;

    try {
        const saved = localStorage.getItem(getProjectHistoryKey(EditorState.project.id));
        if (!saved) return;

        const data = JSON.parse(saved);
        if (data.projectId === EditorState.project.id) {
            EditorState.editHistory = data.history || [];
            EditorState.historyIndex = data.historyIndex ?? -1;
            updateUndoButton();
        }
    } catch (e) {
        console.warn('Failed to load edit history:', e);
    }
}

/**
 * Undo the last edit
 */
function undoEdit() {
    if (EditorState.historyIndex < 0 || EditorState.editHistory.length === 0) {
        showToast('Nothing to undo', 'info');
        return;
    }

    const entry = EditorState.editHistory[EditorState.historyIndex];

    // Handle audio edits (legacy 'audio' key or track ID like 'at_1')
    if (entry.sceneId === 'audio' || entry.sceneId?.startsWith('at_')) {
        if (entry.field === 'removeTrack' && entry.oldValue) {
            // Undo track removal — re-insert the track
            const restored = { ...entry.oldValue, element: null };
            const insertAt = Math.min(restored._index ?? EditorState.audioTracks.length, EditorState.audioTracks.length);
            delete restored._index;
            EditorState.audioTracks.splice(insertAt, 0, restored);
            // Re-create audio element if it had a file
            if (restored.path) {
                const el = new Audio(restored.path);
                el.preload = 'metadata';
                restored.element = el;
            }
            recalculateDuration();
            renderAllAudioTracks();
            renderTimeRuler();
            showToast(`Undo: ${entry.action}`, 'info');
        } else {
        const track = entry.sceneId === 'audio' ? getVoiceTrack() : getAudioTrackById(entry.sceneId);
        if (entry.field === 'trimmedDuration' && track) {
            track.trimmedDuration = entry.oldValue;
            if (track.element) track.element.currentTime = getTrackPlaybackTime(track, EditorState.playbackPosition);
            recalculateDuration();
            renderAllAudioTracks();
            renderTimeRuler();
            if (EditorState.preview) {
                EditorState.preview.setDuration(getTotalDuration());
            }
        } else if (entry.field === 'trimRange' && track) {
            applyTrackTrimState(track, entry.oldValue || {});
            if (track.element) track.element.currentTime = getTrackPlaybackTime(track, EditorState.playbackPosition);
            recalculateDuration();
            renderAllAudioTracks();
            renderTimeRuler();
            if (EditorState.preview) {
                EditorState.preview.setDuration(getTotalDuration());
            }
        } else if (entry.field === 'timelineOffset' && track) {
            track.timelineOffset = entry.oldValue;
            if (track.element) track.element.currentTime = getTrackPlaybackTime(track, EditorState.playbackPosition);
            recalculateDuration();
            renderAllAudioTracks();
            renderTimeRuler();
            if (EditorState.preview) {
                EditorState.preview.setDuration(getTotalDuration());
            }
        } else if (['loop', 'duckingEnabled', 'muted', 'volume', 'fadeIn', 'fadeOut'].includes(entry.field) && track) {
            track[entry.field] = entry.oldValue;
            if (entry.field === 'volume') applyTrackVolumeLive(track, entry.oldValue);
            if (entry.field === 'muted') applyTrackVolumeLive(track, track.volume);
            if (entry.field === 'loop' && track.element) track.element.loop = entry.oldValue;
            renderAllAudioTracks();
        }
        showToast(`Undo: ${entry.action}`, 'info');
        }
    } else if (entry.sceneId === 'bulk' && entry.field === 'flipFillers') {
        // Undo bulk filler flip — restore all durations
        const oldState = entry.oldValue;
        if (Array.isArray(oldState)) {
            EditorState.scenes.forEach((s, i) => {
                if (oldState[i]) {
                    s.duration = oldState[i].duration;
                    s.filler_shift = oldState[i].filler_shift;
                }
            });
            const isNowApplied = EditorState.scenes.some(s => s.filler_shift && s.filler_shift !== 0);
            elements.flipFillerBtn?.classList.toggle('active', isNowApplied);
            recalculateDuration();
            renderTimeline();
            renderTimeRuler();
            renderCaptionTrack();
        }
        showToast(`Undo: ${entry.action}`, 'info');
    } else if (entry.sceneId === 'captions') {
        if (entry.field === 'captionsEnabled') {
            EditorState.captionsEnabled = entry.oldValue;
            const capToggle = document.getElementById('caption-enabled-toggle');
            if (capToggle) capToggle.checked = entry.oldValue;
            const row = elements.captionTrackRow;
            if (row) row.style.display = entry.oldValue ? '' : 'none';
            if (EditorState.preview) {
                if (entry.oldValue && EditorState.captionData) {
                    EditorState.preview.setCaptions(EditorState.captionData.captions, EditorState.captionData.style || {});
                } else {
                    EditorState.preview.setCaptions(null, null);
                }
            }
            renderCaptionTrack();
        } else if (entry.field === 'style' && EditorState.captionData) {
            EditorState.captionData.style = entry.oldValue;
            if (typeof _capSyncStyleUI === 'function') _capSyncStyleUI();
            if (EditorState.preview && EditorState.captionsEnabled) {
                EditorState.preview.setCaptions(EditorState.captionData.captions, EditorState.captionData.style);
            }
        } else if (entry.field?.startsWith('style.') && EditorState.captionData?.style) {
            const key = entry.field.split('.')[1];
            EditorState.captionData.style[key] = entry.oldValue;
            if (typeof _capSyncStyleUI === 'function') _capSyncStyleUI();
            if (EditorState.preview && EditorState.captionsEnabled) {
                EditorState.preview.setCaptions(EditorState.captionData.captions, EditorState.captionData.style);
            }
        }
        _saveCaptionsToStorage();
        showToast(`Undo: ${entry.action}`, 'info');
    } else if (entry.field === 'trackDisabled') {
        if (entry.oldValue) {
            EditorState.disabledTracks.add(entry.sceneId);
        } else {
            EditorState.disabledTracks.delete(entry.sceneId);
        }
        const trackEl = document.querySelector(`.track[data-track="${entry.sceneId}"]`);
        trackEl?.classList.toggle('disabled', entry.oldValue);
        updatePreviewFromDisabledTracks();
        showToast(`Undo: ${entry.action}`, 'info');
    } else {
        // Handle scene edits
        const scene = EditorState.scenes.find(s => s.id === entry.sceneId);

        if (scene && entry.field) {
            // Revert the change
            scene[entry.field] = entry.oldValue;

            // Update UI
            if (entry.field === 'duration') {
                recalculateDuration();
                renderTimeline();
            }
            if (EditorState.selectedScene?.id === entry.sceneId) {
                renderSceneProperties();
            }
            if (EditorState.preview) {
                EditorState.preview.seek(EditorState.playbackPosition);
            }

            showToast(`Undo: ${entry.action}`, 'info');
        }
    }

    EditorState.historyIndex--;
    saveEditHistory();
    saveProjectEdits();

    // Re-validate scenes and update error indicators
    validateScenes();
    applySceneErrorStyles();
    updateUndoButton();
}

/**
 * Redo the last undone edit
 */
function redoEdit() {
    if (EditorState.historyIndex >= EditorState.editHistory.length - 1) {
        showToast('Nothing to redo', 'info');
        return;
    }

    EditorState.historyIndex++;
    const entry = EditorState.editHistory[EditorState.historyIndex];

    // Handle audio edits (legacy 'audio' key or track ID like 'at_1')
    if (entry.sceneId === 'audio' || entry.sceneId?.startsWith('at_')) {
        if (entry.field === 'removeTrack') {
            // Redo track removal — remove it again
            const track = getAudioTrackById(entry.sceneId);
            if (track) {
                if (track.element) { track.element.pause(); track.element.src = ''; }
                EditorState.audioTracks = EditorState.audioTracks.filter(t => t.id !== entry.sceneId);
                recalculateDuration();
                renderAllAudioTracks();
                renderTimeRuler();
            }
            showToast(`Redo: ${entry.action}`, 'info');
        } else {
        const track = entry.sceneId === 'audio' ? getVoiceTrack() : getAudioTrackById(entry.sceneId);
        if (entry.field === 'trimmedDuration' && track) {
            track.trimmedDuration = entry.newValue;
            if (track.element) track.element.currentTime = getTrackPlaybackTime(track, EditorState.playbackPosition);
            recalculateDuration();
            renderAllAudioTracks();
            renderTimeRuler();
            if (EditorState.preview) {
                EditorState.preview.setDuration(getTotalDuration());
            }
        } else if (entry.field === 'trimRange' && track) {
            applyTrackTrimState(track, entry.newValue || {});
            if (track.element) track.element.currentTime = getTrackPlaybackTime(track, EditorState.playbackPosition);
            recalculateDuration();
            renderAllAudioTracks();
            renderTimeRuler();
            if (EditorState.preview) {
                EditorState.preview.setDuration(getTotalDuration());
            }
        } else if (entry.field === 'timelineOffset' && track) {
            track.timelineOffset = entry.newValue;
            if (track.element) track.element.currentTime = getTrackPlaybackTime(track, EditorState.playbackPosition);
            recalculateDuration();
            renderAllAudioTracks();
            renderTimeRuler();
            if (EditorState.preview) {
                EditorState.preview.setDuration(getTotalDuration());
            }
        } else if (['loop', 'duckingEnabled', 'muted', 'volume', 'fadeIn', 'fadeOut'].includes(entry.field) && track) {
            track[entry.field] = entry.newValue;
            if (entry.field === 'volume') applyTrackVolumeLive(track, entry.newValue);
            if (entry.field === 'muted') applyTrackVolumeLive(track, track.volume);
            if (entry.field === 'loop' && track.element) track.element.loop = entry.newValue;
            renderAllAudioTracks();
        }
        showToast(`Redo: ${entry.action}`, 'info');
        }
    } else if (entry.sceneId === 'bulk' && entry.field === 'flipFillers') {
        const newState = entry.newValue;
        if (Array.isArray(newState)) {
            EditorState.scenes.forEach((s, i) => {
                if (newState[i]) {
                    s.duration = newState[i].duration;
                    s.filler_shift = newState[i].filler_shift;
                }
            });
            const isNowApplied = EditorState.scenes.some(s => s.filler_shift && s.filler_shift !== 0);
            elements.flipFillerBtn?.classList.toggle('active', isNowApplied);
            recalculateDuration();
            renderTimeline();
            renderTimeRuler();
            renderCaptionTrack();
        }
        showToast(`Redo: ${entry.action}`, 'info');
    } else if (entry.sceneId === 'captions') {
        if (entry.field === 'captionsEnabled') {
            EditorState.captionsEnabled = entry.newValue;
            const capToggle = document.getElementById('caption-enabled-toggle');
            if (capToggle) capToggle.checked = entry.newValue;
            const row = elements.captionTrackRow;
            if (row) row.style.display = entry.newValue ? '' : 'none';
            if (EditorState.preview) {
                if (entry.newValue && EditorState.captionData) {
                    EditorState.preview.setCaptions(EditorState.captionData.captions, EditorState.captionData.style || {});
                } else {
                    EditorState.preview.setCaptions(null, null);
                }
            }
            renderCaptionTrack();
        } else if (entry.field === 'style' && EditorState.captionData) {
            EditorState.captionData.style = entry.newValue;
            if (typeof _capSyncStyleUI === 'function') _capSyncStyleUI();
            if (EditorState.preview && EditorState.captionsEnabled) {
                EditorState.preview.setCaptions(EditorState.captionData.captions, EditorState.captionData.style);
            }
        } else if (entry.field?.startsWith('style.') && EditorState.captionData?.style) {
            const key = entry.field.split('.')[1];
            EditorState.captionData.style[key] = entry.newValue;
            if (typeof _capSyncStyleUI === 'function') _capSyncStyleUI();
            if (EditorState.preview && EditorState.captionsEnabled) {
                EditorState.preview.setCaptions(EditorState.captionData.captions, EditorState.captionData.style);
            }
        }
        _saveCaptionsToStorage();
        showToast(`Redo: ${entry.action}`, 'info');
    } else if (entry.field === 'trackDisabled') {
        if (entry.newValue) {
            EditorState.disabledTracks.add(entry.sceneId);
        } else {
            EditorState.disabledTracks.delete(entry.sceneId);
        }
        const trackEl = document.querySelector(`.track[data-track="${entry.sceneId}"]`);
        trackEl?.classList.toggle('disabled', entry.newValue);
        updatePreviewFromDisabledTracks();
        showToast(`Redo: ${entry.action}`, 'info');
    } else {
        // Handle scene edits
        const scene = EditorState.scenes.find(s => s.id === entry.sceneId);

        if (scene && entry.field) {
            // Apply the change again
            scene[entry.field] = entry.newValue;

            // Update UI
            if (entry.field === 'duration') {
                recalculateDuration();
                renderTimeline();
            }
            if (EditorState.selectedScene?.id === entry.sceneId) {
                renderSceneProperties();
            }
            if (EditorState.preview) {
                EditorState.preview.seek(EditorState.playbackPosition);
            }

            showToast(`Redo: ${entry.action}`, 'info');
        }
    }

    saveEditHistory();
    saveProjectEdits();

    // Re-validate scenes and update error indicators
    validateScenes();
    applySceneErrorStyles();
    updateUndoButton();
}

/**
 * Update undo/redo button states
 */
function updateUndoButton() {
    const undoBtn = document.getElementById('undo-btn');
    const redoBtn = document.getElementById('redo-btn');
    const historyBadge = document.getElementById('history-badge');

    if (undoBtn) {
        undoBtn.disabled = EditorState.historyIndex < 0;
        undoBtn.title = EditorState.historyIndex >= 0
            ? `Undo: ${EditorState.editHistory[EditorState.historyIndex]?.action || ''}`
            : 'Nothing to undo';
    }

    if (redoBtn) {
        redoBtn.disabled = EditorState.historyIndex >= EditorState.editHistory.length - 1;
        redoBtn.title = EditorState.historyIndex < EditorState.editHistory.length - 1
            ? `Redo: ${EditorState.editHistory[EditorState.historyIndex + 1]?.action || ''}`
            : 'Nothing to redo';
    }

    // Update history badge
    if (historyBadge) {
        const count = EditorState.historyIndex + 1;
        historyBadge.textContent = count;
        historyBadge.classList.toggle('has-history', count > 0);
    }
}

/**
 * Setup history dropdown functionality
 */
function setupHistoryDropdown() {
    const historyBtn = document.getElementById('history-btn');
    const historyDropdown = document.getElementById('history-dropdown');
    const clearHistoryBtn = document.getElementById('clear-history-btn');

    if (!historyBtn || !historyDropdown) return;

    // Toggle dropdown
    historyBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const isOpen = historyDropdown.classList.contains('show');
        if (isOpen) {
            historyDropdown.classList.remove('show');
        } else {
            renderHistoryList();
            historyDropdown.classList.add('show');
        }
    });

    // Close on outside click
    document.addEventListener('click', (e) => {
        if (!historyDropdown.contains(e.target) && !historyBtn.contains(e.target)) {
            historyDropdown.classList.remove('show');
        }
    });

    // Clear all history
    if (clearHistoryBtn) {
        clearHistoryBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            if (confirm('Clear all edit history? This cannot be undone.')) {
                clearProjectEdits();
                renderHistoryList();
            }
        });
    }

    // Reset to initial state button
    const resetBtn = document.getElementById('share-reset-initial');
    if (resetBtn) {
        resetBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            resetToInitialState();
        });
    }
}

/**
 * Render the history list in the dropdown
 */
function renderHistoryList() {
    const historyList = document.getElementById('editor-history-list');
    if (!historyList) return;

    const history = EditorState.editHistory;
    const historyIndex = EditorState.historyIndex;

    if (!history || history.length === 0) {
        historyList.innerHTML = '<li class="history-empty">No history yet</li>';
        return;
    }

    // Render history items (most recent first)
    historyList.innerHTML = history.map((entry, index) => {
        const isCurrent = index === historyIndex;
        const label = entry.action || 'Unknown change';
        const meta = entry.sceneId ? `Scene ${entry.sceneId}` : 'Project';

        return `
            <li class="history-item ${isCurrent ? 'current' : ''}" data-index="${index}">
                <span class="history-item-index">${index + 1}</span>
                <div class="history-item-info">
                    <div class="history-item-label">${label}</div>
                    <div class="history-item-meta">${meta}</div>
                </div>
                <button class="history-item-delete" data-index="${index}" title="Delete this state">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M18 6L6 18"></path>
                        <path d="M6 6l12 12"></path>
                    </svg>
                </button>
            </li>
        `;
    }).reverse().join('');

    // Add click handlers for jumping to history state
    historyList.querySelectorAll('.history-item').forEach(item => {
        item.addEventListener('click', (e) => {
            if (e.target.closest('.history-item-delete')) return;
            const index = parseInt(item.dataset.index);
            jumpToHistoryState(index);
            renderHistoryList();
        });
    });

    // Add click handlers for delete buttons
    historyList.querySelectorAll('.history-item-delete').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const index = parseInt(btn.dataset.index);
            deleteHistoryAt(index);
            renderHistoryList();
        });
    });
}

/**
 * Jump to a specific history state
 */
function jumpToHistoryState(targetIndex) {
    if (targetIndex < 0 || targetIndex >= EditorState.editHistory.length) return;

    // Apply all states from current to target
    if (targetIndex < EditorState.historyIndex) {
        // Going back - undo from current to target
        while (EditorState.historyIndex > targetIndex) {
            const entry = EditorState.editHistory[EditorState.historyIndex];
            applyHistoryEntry(entry, true); // true = undo (use oldValue)
            EditorState.historyIndex--;
        }
    } else if (targetIndex > EditorState.historyIndex) {
        // Going forward - redo from current to target
        while (EditorState.historyIndex < targetIndex) {
            EditorState.historyIndex++;
            const entry = EditorState.editHistory[EditorState.historyIndex];
            applyHistoryEntry(entry, false); // false = redo (use newValue)
        }
    }

    saveEditHistory();
    updateUndoButton();
    renderTimeline();
    showToast(`Jumped to state ${targetIndex + 1}`, 'info');
}

/**
 * Apply a history entry (for undo/redo operations)
 */
function applyHistoryEntry(entry, isUndo) {
    const scene = EditorState.scenes.find(s => s.id === entry.sceneId);
    if (!scene) return;

    const value = isUndo ? entry.oldValue : entry.newValue;
    scene[entry.field] = value;
}

/**
 * Delete a specific history entry
 */
function deleteHistoryAt(index) {
    if (index < 0 || index >= EditorState.editHistory.length) return;

    // Remove the entry
    EditorState.editHistory.splice(index, 1);

    // Adjust historyIndex if needed
    if (EditorState.historyIndex >= index) {
        EditorState.historyIndex = Math.max(-1, EditorState.historyIndex - 1);
    }

    saveEditHistory();
    updateUndoButton();
    _updateResetButtonVisibility();
    showToast('History entry removed', 'info');
}

/**
 * Clear all saved edits for current project
 */
function clearProjectEdits() {
    if (!EditorState.project?.id) return;

    localStorage.removeItem(getProjectEditsKey(EditorState.project.id));
    localStorage.removeItem(getProjectHistoryKey(EditorState.project.id));
    EditorState.savedAudioSettings = null;
    EditorState.editHistory = [];
    EditorState.historyIndex = -1;
    updateUndoButton();
    _updateResetButtonVisibility();
    showToast('Cleared saved edits', 'info');
}

// ============================================================
// Scene Error Validation
// ============================================================

/**
 * Validate all scenes and track errors
 */
function validateScenes() {
    EditorState.sceneErrors.clear();

    EditorState.scenes.forEach(scene => {
        const errors = [];

        // Check for missing media (image scenes should have media)
        if (!['text', 'cta'].includes(scene.type)) {
            if (!scene.mediaUrl && !scene.mediaFile) {
                errors.push('Image not found');
            }
        }

        // Check for text scenes without content
        if (['text', 'cta'].includes(scene.type)) {
            if (!scene.text_content || !scene.text_content.trim()) {
                errors.push('Missing text content');
            }
        }

        // Check for zero or negative duration
        if (scene.duration <= 0) {
            errors.push('Invalid duration');
        }

        // Check for very short duration (less than 0.5s)
        if (scene.duration > 0 && scene.duration < 0.5) {
            errors.push('Duration too short');
        }

        if (errors.length > 0) {
            EditorState.sceneErrors.set(scene.id, errors);
        }
    });

    updateErrorIndicator();
}

/**
 * Update the error indicator in the header
 */
function updateErrorIndicator() {
    const errorIndicator = document.getElementById('error-indicator');
    const errorCount = document.getElementById('error-count');

    if (!errorIndicator || !errorCount) return;

    const errorTotal = EditorState.sceneErrors.size;

    if (errorTotal > 0) {
        errorIndicator.classList.remove('hidden');
        errorCount.textContent = errorTotal;
        errorIndicator.title = `${errorTotal} scene${errorTotal > 1 ? 's' : ''} with errors`;
    } else {
        errorIndicator.classList.add('hidden');
    }
}

/**
 * Apply error styling to scene clips in timeline
 */
function applySceneErrorStyles() {
    if (!elements.videoTrack) return;

    elements.videoTrack.querySelectorAll('.scene-clip').forEach(clip => {
        const sceneId = parseInt(clip.dataset.id);
        const errors = EditorState.sceneErrors.get(sceneId);

        if (errors && errors.length > 0) {
            clip.classList.add('has-error');
            clip.title = `${clip.title}\n⚠ ${errors.join(', ')}`;
        } else {
            clip.classList.remove('has-error');
        }
    });
}

/**
 * Setup error dropdown toggle and interactions
 */
function setupErrorDropdown() {
    const errorIndicator = document.getElementById('error-indicator');
    const errorDropdown = document.getElementById('error-dropdown');

    if (!errorIndicator || !errorDropdown) return;

    // Toggle dropdown on indicator click
    errorIndicator.addEventListener('click', (e) => {
        e.stopPropagation();
        if (errorDropdown.classList.contains('show')) {
            errorDropdown.classList.remove('show');
        } else {
            renderErrorList();
            errorDropdown.classList.add('show');
        }
    });

    // Close on outside click
    document.addEventListener('click', (e) => {
        if (!errorDropdown.contains(e.target) && !errorIndicator.contains(e.target)) {
            errorDropdown.classList.remove('show');
        }
    });
}

/**
 * Render the error list in the dropdown
 */
function renderErrorList() {
    const errorList = document.getElementById('error-list');
    if (!errorList) return;

    if (EditorState.sceneErrors.size === 0) {
        errorList.innerHTML = '<li class="error-empty">No errors</li>';
        return;
    }

    let html = '';
    EditorState.sceneErrors.forEach((errors, sceneId) => {
        const scene = EditorState.scenes.find(s => s.id === sceneId);
        const sceneLabel = scene ? `Scene ${scene.id}` : `Scene ${sceneId}`;
        const sceneType = scene?.type || 'unknown';

        errors.forEach(error => {
            html += `
                <li class="error-item" data-scene-id="${sceneId}">
                    <span class="error-item-scene">${sceneLabel}</span>
                    <div class="error-item-info">
                        <div class="error-item-type">${sceneType}</div>
                        <div class="error-item-message">${error}</div>
                    </div>
                </li>
            `;
        });
    });

    errorList.innerHTML = html;

    // Add click handlers to navigate to scene
    errorList.querySelectorAll('.error-item').forEach(item => {
        item.addEventListener('click', () => {
            const sceneId = parseInt(item.dataset.sceneId);
            selectScene(sceneId);
            const clip = elements.videoTrack?.querySelector(`.scene-clip[data-id="${sceneId}"]`);
            if (clip) {
                clip.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
            }
            // Close dropdown after selection
            document.getElementById('error-dropdown')?.classList.remove('show');
        });
    });
}

// ============================================================
// Timeline Calculation Helpers - Single Source of Truth
// ============================================================

/**
 * Get the total duration of all scenes
 */
function getScenesDuration() {
    return EditorState.scenes.reduce((sum, s) => sum + s.duration, 0);
}

/**
 * Get the total project duration (max of scenes and audio)
 */
function getTotalDuration() {
    const scenesDuration = getScenesDuration();

    // Compute max duration across all audio tracks
    let maxAudioDur = 0;
    for (const track of EditorState.audioTracks) {
        if (track.loaded || track.file) {
            const dur = getTrackTimelineEnd(track, scenesDuration);
            if (dur > maxAudioDur) maxAudioDur = dur;
        }
    }

    let captionsDuration = 0;
    if (EditorState.captionsEnabled && EditorState.captionData?.captions?.length > 0) {
        const lastCaption = EditorState.captionData.captions[EditorState.captionData.captions.length - 1];
        captionsDuration = lastCaption.end || 0;
    }

    return Math.max(scenesDuration, maxAudioDur, captionsDuration);
}

function _roundTimelineSeconds(value) {
    return Math.round(Math.max(0, value) * 1000) / 1000;
}

function _getTimelineConstraintDuration() {
    let target = EditorState.project?.totalDuration || 0;

    for (const track of EditorState.audioTracks) {
        const dur = getTrackTimelineEnd(track, target || getScenesDuration());
        if (dur > target) target = dur;
    }

    if (EditorState.captionsEnabled && EditorState.captionData?.captions?.length > 0) {
        const lastCaption = EditorState.captionData.captions[EditorState.captionData.captions.length - 1];
        target = Math.max(target, lastCaption.end || 0);
    }

    return _roundTimelineSeconds(target);
}

function _syncSceneTimestamps() {
    let acc = 0;
    for (const scene of EditorState.scenes) {
        scene.timestamp = _roundTimelineSeconds(acc);
        acc += Number(scene.duration) || 0;
    }
}

function normalizeTimelineDurations(targetDuration = null) {
    if (!EditorState.scenes.length) return false;

    const target = _roundTimelineSeconds(targetDuration ?? _getTimelineConstraintDuration());
    if (target <= 0) {
        _syncSceneTimestamps();
        return false;
    }

    const total = _roundTimelineSeconds(getScenesDuration());
    const diff = _roundTimelineSeconds(target - total);
    if (Math.abs(diff) <= 0.01) {
        _syncSceneTimestamps();
        return false;
    }

    const lastScene = EditorState.scenes[EditorState.scenes.length - 1];
    const adjustedLast = _roundTimelineSeconds((lastScene.duration || 0) + diff);

    if (adjustedLast >= 0.1) {
        lastScene.duration = adjustedLast;
    } else {
        const ratio = total > 0 ? target / total : 1;
        EditorState.scenes.forEach(scene => {
            scene.duration = _roundTimelineSeconds(Math.max(0.1, (scene.duration || 0) * ratio));
        });

        const resyncedTotal = _roundTimelineSeconds(getScenesDuration());
        const residual = _roundTimelineSeconds(target - resyncedTotal);
        const fallbackLast = EditorState.scenes[EditorState.scenes.length - 1];
        fallbackLast.duration = _roundTimelineSeconds(Math.max(0.1, (fallbackLast.duration || 0) + residual));
    }

    _syncSceneTimestamps();
    return true;
}

/**
 * Convert time (seconds) to pixel position on timeline
 */
function timeToPixels(time) {
    return time * EditorState.pixelsPerSecond * EditorState.zoomLevel;
}

/**
 * Convert pixel position to time (seconds)
 */
function pixelsToTime(pixels) {
    return pixels / (EditorState.pixelsPerSecond * EditorState.zoomLevel);
}

/**
 * Get the start time of a scene by its index
 */
function getSceneStartTime(sceneIndex) {
    let startTime = 0;
    for (let i = 0; i < sceneIndex && i < EditorState.scenes.length; i++) {
        startTime += EditorState.scenes[i].duration;
    }
    return startTime;
}

/**
 * Get all scene boundary times (start/end of every scene)
 */
function getSceneBoundaryTimes() {
    const boundaries = [0];
    let t = 0;
    for (const s of EditorState.scenes) {
        t += s.duration || 0;
        boundaries.push(t);
    }
    return boundaries;
}

/**
 * Snap a time value to the nearest scene boundary if within threshold pixels.
 * Returns the snapped time, or the original time if no boundary is close enough.
 */
function snapToSceneBoundary(time, thresholdPx) {
    const threshold = pixelsToTime(thresholdPx || 8);
    const boundaries = getSceneBoundaryTimes();
    for (const b of boundaries) {
        if (Math.abs(time - b) < threshold) return b;
    }
    return time;
}

/**
 * Get the scene at a given time
 */
function getSceneAtTime(time) {
    let accumulated = 0;
    for (let i = 0; i < EditorState.scenes.length; i++) {
        const scene = EditorState.scenes[i];
        if (time >= accumulated && time < accumulated + scene.duration) {
            return {
                scene,
                index: i,
                startTime: accumulated,
                endTime: accumulated + scene.duration,
                localTime: time - accumulated,
                progress: (time - accumulated) / scene.duration
            };
        }
        accumulated += scene.duration;
    }
    return null; // Time is past all scenes (in audio-only region)
}

/**
 * Get the pixel position of a scene on the timeline
 */
function getScenePixelPosition(sceneIndex) {
    const startTime = getSceneStartTime(sceneIndex);
    return timeToPixels(startTime);
}

/**
 * Get the pixel width of a scene
 */
function getScenePixelWidth(scene) {
    return timeToPixels(scene.duration);
}

/**
 * Track base offset (header + padding)
 */
const TRACK_BASE_OFFSET = 40; // 36px header + 4px padding

// DOM Elements
const elements = {
    projectName: document.getElementById('project-name'),
    noDataOverlay: document.getElementById('no-data-overlay'),
    timelineTracks: document.getElementById('timeline-tracks'),
    videoTrack: document.getElementById('video-track'),
    textTrack: document.getElementById('text-track'),
    captionTrack: document.getElementById('caption-track'),
    captionTrackRow: document.getElementById('caption-track-row'),
    audioTracksContainer: document.getElementById('audio-tracks-container'),
    previewCanvas: document.getElementById('preview-canvas'),
    previewPlaceholder: document.getElementById('preview-placeholder'),
    currentTime: document.getElementById('current-time'),
    totalTime: document.getElementById('total-time'),
    timeScrubber: document.getElementById('time-scrubber'),
    playBtn: document.getElementById('play-btn'),
    loopBtn: document.getElementById('loop-btn'),  // Loop toggle button
    volumeBtn: document.getElementById('volume-btn'),  // Volume/mute button
    fullscreenBtn: document.getElementById('fullscreen-btn'),  // Fullscreen toggle
    previewPanel: document.getElementById('preview-panel'),  // Preview panel for fullscreen
    selectFolderBtn: document.getElementById('select-folder'),
    randomizeMediaBtn: document.getElementById('randomize-media'),
    flipFillerBtn: document.getElementById('flip-filler-btn'),
    mediaStatus: document.getElementById('media-status'),
    zoomIn: document.getElementById('zoom-in'),
    zoomOut: document.getElementById('zoom-out'),
    zoomLevel: document.getElementById('zoom-level'),
    infoScenes: document.getElementById('info-scenes'),
    infoDuration: document.getElementById('info-duration'),
    sceneProperties: document.getElementById('scene-properties'),
    previewJsonBtn: document.getElementById('preview-json'),
    exportShareBtn: document.getElementById('export-share-btn'),
    timeRuler: document.getElementById('time-ruler'),
    timelineResizeHandle: document.getElementById('timeline-resize-handle'),
    timelineHeaderMarker: document.getElementById('timeline-header-marker'),
    headerMarkerIndicator: document.querySelector('.header-marker-indicator'),
    headerMarkerTrail: document.querySelector('.header-marker-trail'),
    editorLayout: document.querySelector('.editor-layout'),
    timelinePanel: document.querySelector('.timeline-panel'),
    // Export progress modal
    exportProgressModal: document.getElementById('export-progress-modal'),
    exportProgressTitle: document.getElementById('export-progress-title'),
    exportProgressBar: document.getElementById('export-progress-bar'),
    exportProgressPercent: document.getElementById('export-progress-percent'),
    exportProgressMessage: document.getElementById('export-progress-message'),
    cancelExportBtn: document.getElementById('cancel-export'),
    previewExportBtn: document.getElementById('preview-export'),
    openExportFolderBtn: document.getElementById('open-export-folder'),
    downloadExportBtn: document.getElementById('download-export')
};

// ---------------------------------------------------------------------------
// Font Registry — loads custom + system fonts from backend
// ---------------------------------------------------------------------------
let _fontRegistry = [];  // [{family, source, variants:{variant: url}}]
let _fontRegistryLoadPromise = null;

async function loadFontRegistry() {
    try {
        const res = await fetch('/api/fonts');
        if (!res.ok) throw new Error(`Font API ${res.status}`);
        _fontRegistry = await res.json();
        console.log(`Font registry loaded: ${_fontRegistry.length} fonts`);

        // Inject @font-face rules for custom fonts
        const style = document.createElement('style');
        style.id = 'custom-font-faces';
        const rules = [];
        for (const font of _fontRegistry) {
            if (font.source !== 'custom') continue;
            for (const [variant, url] of Object.entries(font.variants)) {
                const weight = variant.includes('bold') || variant === 'black' || variant === 'extrabold' ? 'bold'
                    : variant.includes('light') || variant === 'thin' || variant === 'extralight' ? '300'
                        : variant === 'medium' ? '500'
                            : variant === 'semibold' ? '600'
                                : 'normal';
                const fontStyle = variant.includes('italic') ? 'italic' : 'normal';
                rules.push(`@font-face {
  font-family: '${font.family}';
  src: url('${url}') format('${url.endsWith('.otf') ? 'opentype' : 'truetype'}');
  font-weight: ${weight};
  font-style: ${fontStyle};
  font-display: swap;
}`);
            }
        }
        style.textContent = rules.join('\n');
        document.head.appendChild(style);

        // Wait for fonts to be ready for canvas rendering (cap at 5s)
        if (rules.length > 0) {
            await Promise.race([
                document.fonts.ready,
                new Promise(r => setTimeout(r, 5000))
            ]);
            console.log(`Custom @font-face rules injected: ${rules.length}`);
        }
    } catch (err) {
        console.warn('Failed to load font registry:', err);
    }
}

function ensureFontRegistryLoaded() {
    if (!_fontRegistryLoadPromise) {
        _fontRegistryLoadPromise = loadFontRegistry();
    }
    return _fontRegistryLoadPromise;
}

/**
 * Build <option> elements for a font <select>, grouped by custom/system.
 * Each option is styled in its own font for preview.
 */
function buildFontOptions(selectEl, selectedFamily) {
    selectEl.innerHTML = '';
    const custom = _fontRegistry.filter(f => f.source === 'custom');
    const system = _fontRegistry.filter(f => f.source === 'system');
    let found = false;

    if (custom.length) {
        const grp = document.createElement('optgroup');
        grp.label = 'Custom Fonts';
        for (const f of custom) {
            const opt = document.createElement('option');
            opt.value = f.family;
            opt.textContent = f.family;
            opt.style.fontFamily = `'${f.family}', sans-serif`;
            if (f.family === selectedFamily) { opt.selected = true; found = true; }
            grp.appendChild(opt);
        }
        selectEl.appendChild(grp);
    }

    if (system.length) {
        const grp = document.createElement('optgroup');
        grp.label = 'System Fonts';
        for (const f of system) {
            const opt = document.createElement('option');
            opt.value = f.family;
            opt.textContent = f.family;
            opt.style.fontFamily = `'${f.family}', sans-serif`;
            if (f.family === selectedFamily) { opt.selected = true; found = true; }
            grp.appendChild(opt);
        }
        selectEl.appendChild(grp);
    }

    // If selected font isn't in registry, add it so the dropdown isn't blank
    if (!found && selectedFamily) {
        const opt = document.createElement('option');
        opt.value = selectedFamily;
        opt.textContent = selectedFamily;
        opt.style.fontFamily = `'${selectedFamily}', sans-serif`;
        opt.selected = true;
        selectEl.insertBefore(opt, selectEl.firstChild);
    }
}

// ---- Load saved project from server ----

async function loadProjectFromServer(projectId, { force = false } = {}) {
    // Skip if this project is already loaded and has scenes (unless forced, e.g. reset)
    if (!force && EditorState.project?.id === projectId && EditorState.scenes.length > 0 && !EditorState.activeBootstrapId) {
        hideNoDataOverlay();
        showToast('Project already loaded', 'info');
        return;
    }
    showLoadingOverlay('Loading saved project...');
    updateLoadingOverlay('Fetching saved project...');

    let saved;
    try {
        const res = await fetch(`/api/editor/load/${encodeURIComponent(projectId)}`, { signal: AbortSignal.timeout(15000) });
        if (!res.ok) throw new Error('Project not found');
        saved = await res.json();
    } catch (e) {
        await hideLoadingOverlay();
        showToast('Failed to load project: ' + e.message, 'error');
        showNoDataOverlay();
        return;
    }

    // Resolve style template name/color
    let styleName = '', styleColor = '';
    if (saved.style) {
        try {
            const templates = await fetch('/api/scenes/templates').then(r => r.json());
            const tmpl = templates.find(t => t.id === saved.style);
            if (tmpl) { styleName = tmpl.name; styleColor = tmpl.color; }
        } catch { /* ignore */ }
    }

    // Build project data directly (no sessionStorage)
    const projectData = {
        project_id: saved.project_id,
        project_name: saved.project_name || saved.project_id,
        _source: saved._source || 'initial',
        style: saved.style || '',
        style_name: styleName,
        style_color: styleColor,
        source_folder: saved.source_folder || '',
        story_tone: saved.story_tone || '',
        total_duration: saved.total_duration || 0,
        scene_count: saved.scene_count || saved.scenes?.length || 0,
        staged_at: saved.saved_at,
        scenes: (saved.scenes || []).map((s, i) => ({
            scene_id: s.id ?? i,
            type: s.type || 'image',
            image_prompt: s.image_prompt || '',
            text_content: s.text_content || null,
            duration: s.duration || 3,
            timestamp: s.timestamp || 0,
            image_url: s.mediaUrl || s.image_url || '',
            visual_fx: s.visual_fx || 'static',
            text_color: s.text_color,
            text_size: s.text_size,
            font_family: s.font_family,
            font_style: s.font_style,
            text_align: s.text_align,
            vertical_align: s.vertical_align,
            text_x: s.text_x,
            text_y: s.text_y,
            text_timeline_offset: s.text_timeline_offset ?? 0,
            text_overlay_duration: s.text_overlay_duration ?? null,
            text_background_enabled: !!s.text_background_enabled,
            text_background_color: s.text_background_color || '#000000',
            text_display_mode: s.text_display_mode || null,
            text_hook_animation: s.text_hook_animation || null,
            text_animation: s.text_animation || null,
            script: s.script || '',
            narrative_role: s.narrative_role || '',
            isVideo: s.isVideo || false,
            image: s.image || '',
            status: s.status || 'ready',
            filler_shift: s.filler_shift || 0,
            segment_start: s.segment_start ?? null,
            segment_end: s.segment_end ?? null,
            segment_duration: s.segment_duration ?? null
        }))
    };

    // Restore voice audio path from saved tracks
    const voiceTrack = (saved.audio_tracks || []).find(t => t.type === 'voice');
    if (voiceTrack?.path) {
        const audio = normalizeVoiceAudioConfig({
            url: voiceTrack.path,
            source_file: voiceTrack.file || '',
            duration: voiceTrack.duration || 0,
            trimmedDuration: voiceTrack.trimmedDuration || null,
            timelineOffset: voiceTrack.timelineOffset || voiceTrack.timeline_offset || 0,
            startOffset: voiceTrack.startOffset || voiceTrack.start_offset || 0
        });
        if (audio?.url) projectData.audio = audio;
    }

    _resetEditorForNewProject();

    try {
        await bootstrapProjectIntoEditor(projectData, {
            initialMessage: 'Loading saved project...',
            readyMessage: 'Project loaded',
            failureMessage: 'Failed to load project',
            showNoDataOnError: true,
            afterCoreLoad: async () => {
                if (saved.captions?.captions?.length) {
                    _receiveCaptionData(saved.captions);
                } else if (!EditorState.captionData) {
                    _loadCaptionsFromStorage();
                }
                if (EditorState.captionData && !saved.captions) {
                    saveProjectToServer();
                }

                _applyExtraState({
                    audio_tracks: (saved.audio_tracks || []).filter(t => t.type !== 'voice'),
                    edit_history: saved.edit_history || [],
                    history_index: saved.history_index ?? -1,
                    disabled_tracks: saved.disabled_tracks || [],
                    captionsEnabled: saved.captionsEnabled,
                    overlays: saved.overlays || (saved.overlay ? [saved.overlay] : []),
                    grain_overlay: saved.grain_overlay || saved.grainOverlay || null,
                    scenes: saved.scenes || []
                });
            }
        });
    } catch (e) {
        if (e.message !== 'Editor load superseded by a newer request') {
            console.warn('Saved project bootstrap failed:', e);
        }
    }
}

/**
 * Reset editor state before loading a new project (no page reload needed).
 */
function _resetEditorForNewProject() {
    // Stop playback
    if (EditorState.isPlaying && EditorState.preview) {
        EditorState.preview.toggle();
    }
    EditorState.isPlaying = false;

    // Stop and remove all audio elements
    for (const track of EditorState.audioTracks) {
        if (track.element) { track.element.pause(); track.element.src = ''; }
    }
    EditorState.audioTracks = [];
    EditorState.audio = null;
    EditorState.audioElement = null;
    EditorState.voiceLoadToken++;
    EditorState.voiceLoadPromise = Promise.resolve({ status: 'reset', reason: 'project-reset' });

    // Reset state
    EditorState.scenes = [];
    EditorState.originalScenes = [];
    EditorState.selectedScene = null;
    EditorState.selectedTextOverlaySceneId = null;
    EditorState.playbackPosition = 0;
    EditorState.editHistory = [];
    EditorState.historyIndex = -1;
    EditorState.sceneErrors = new Map();
    EditorState.savedAudioSettings = null;
    EditorState.captionData = null;
    EditorState.captionsEnabled = false;
    EditorState.selectedOverlayIdx = null;
    EditorState.overlays = [];
    EditorState.grainOverlay = null;
    EditorState.disabledTracks = new Set();

    // Clear preview
    if (EditorState.preview) {
        EditorState.preview.disabledTracks = new Set();
        EditorState.preview.setCaptions(null, null);
        EditorState.preview.setOverlay([]);
    }
}

/**
 * Apply extra saved state (music tracks, overlays, history, etc.)
 * directly from data, without going through sessionStorage.
 */
function _applyExtraState(saved) {
    // Re-apply scene-level properties from server save
    if (saved.scenes?.length) {
        for (const ss of saved.scenes) {
            const scene = EditorState.scenes.find(s => s.id === (ss.id ?? ss.scene_id));
            if (!scene) continue;
            if (ss.visual_fx !== undefined) scene.visual_fx = ss.visual_fx;
            if (ss.duration !== undefined) scene.duration = ss.duration;
            if (ss.text_content !== undefined) scene.text_content = ss.text_content;
            if (ss.text_color !== undefined) scene.text_color = ss.text_color;
            if (ss.text_size !== undefined) scene.text_size = ss.text_size;
            if (ss.font_family !== undefined) scene.font_family = ss.font_family;
            if (ss.font_style !== undefined) scene.font_style = ss.font_style;
            if (ss.text_align !== undefined) scene.text_align = ss.text_align;
            if (ss.vertical_align !== undefined) scene.vertical_align = ss.vertical_align;
            if (ss.text_x !== undefined) scene.text_x = ss.text_x;
            if (ss.text_y !== undefined) scene.text_y = ss.text_y;
            if (ss.text_timeline_offset !== undefined) scene.text_timeline_offset = ss.text_timeline_offset;
            if (ss.text_overlay_duration !== undefined) scene.text_overlay_duration = ss.text_overlay_duration;
            if (ss.text_background_enabled !== undefined) scene.text_background_enabled = ss.text_background_enabled;
            if (ss.text_background_color !== undefined) scene.text_background_color = ss.text_background_color;
            if (ss.text_display_mode !== undefined) scene.text_display_mode = ss.text_display_mode;
            if (ss.text_hook_animation !== undefined) scene.text_hook_animation = ss.text_hook_animation;
            if (ss.text_animation !== undefined) scene.text_animation = ss.text_animation;
            if (ss.mediaUrl) scene.mediaUrl = ss.mediaUrl;
            if (ss.image_url) scene.mediaUrl = scene.mediaUrl || ss.image_url;
            normalizeSceneTextOverlay(scene);
        }
    }

    // Restore non-voice audio tracks (music, SFX)
    for (const t of (saved.audio_tracks || [])) {
        const hasClips = t.clips && t.clips.length > 0;
        if (!hasClips && (!t.file || !t.path)) continue;
        const track = createAudioTrack({
            label: (t.label || t.type).replace(/\s*\d+$/, ''),
            type: t.type,
            file: t.file || null,
            path: t.path || null,
            duration: t.duration || 0,
            timelineOffset: t.timelineOffset || t.timeline_offset || 0,
            startOffset: t.startOffset || t.start_offset || 0,
            trimmedDuration: t.trimmedDuration || null,
            volume: t.volume ?? 1.0,
            loop: !!t.loop,
            duckingEnabled: !!t.duckingEnabled,
            duckingLevel: t.duckingLevel ?? DEFAULT_MUSIC_DUCKING_LEVEL,
            fadeIn: t.fadeIn || 0,
            fadeOut: t.fadeOut || 0
        });
        track.muted = !!t.muted;

        // Restore multi-clip FX tracks
        if (hasClips) {
            track.clips = [];
            track.loaded = true;
            for (const c of t.clips) {
                const clip = {
                    id: c.id || nextClipId(),
                    file: c.file, path: c.path, label: c.label,
                    duration: c.duration || 0, offset: c.offset || 0,
                    element: null,
                };
                const clipAudio = new Audio(c.path);
                clip.element = clipAudio;
                clipAudio.addEventListener('loadedmetadata', () => {
                    clip.duration = clipAudio.duration;
                    renderAllAudioTracks();
                });
                track.clips.push(clip);
            }
        } else {
            const audio = new Audio(t.path);
            track.element = audio;
            audio.loop = track.loop;
            ensureTrackGainNode(track);
            audio.addEventListener('loadedmetadata', () => {
                track.loaded = true;
                track.duration = audio.duration;
                renderAllAudioTracks();
            });
            audio.addEventListener('error', () => {
                track.error = true;
                renderAllAudioTracks();
            });
        }

        EditorState.audioTracks.push(track);
    }

    // Restore edit history
    if (saved.edit_history?.length) {
        EditorState.editHistory = saved.edit_history;
        EditorState.historyIndex = saved.history_index ?? saved.edit_history.length - 1;
    }

    // Restore disabled tracks
    if (saved.disabled_tracks?.length) {
        EditorState.disabledTracks = new Set(saved.disabled_tracks);
    }

    // Restore captions enabled state
    if (saved.captionsEnabled !== undefined) {
        EditorState.captionsEnabled = saved.captionsEnabled;
        const toggle = document.getElementById('caption-enabled-toggle');
        if (toggle) {
            toggle.checked = saved.captionsEnabled;
            const lbl = toggle.parentElement?.querySelector('.cap-card-toggle-label');
            if (lbl) lbl.textContent = saved.captionsEnabled ? 'On' : 'Off';
        }
        if (elements.captionTrackRow) {
            elements.captionTrackRow.style.display = saved.captionsEnabled ? '' : 'none';
        }
        if (EditorState.preview) {
            if (saved.captionsEnabled && EditorState.captionData) {
                EditorState.preview.setCaptions(EditorState.captionData.captions, EditorState.captionData.style || {});
            } else if (!saved.captionsEnabled) {
                EditorState.preview.setCaptions(null, null);
            }
        }
    }

    // Restore global overlays (support legacy string[] or new object[])
    const savedOverlays = saved.overlays
        ? (Array.isArray(saved.overlays) ? saved.overlays : [saved.overlays])
        : (saved.overlay ? [saved.overlay] : []);
    if (savedOverlays.length) {
        EditorState.overlays = savedOverlays.map(normalizeOverlayEntry);
        if (EditorState.preview) EditorState.preview.setOverlay(EditorState.overlays);
        updateOverlaysTab();
    }

    EditorState.grainOverlay = normalizeGrainOverlay(saved.grain_overlay || saved.grainOverlay || EditorState.grainOverlay);
    updateOverlaysTab();

    renderAllAudioTracks();
    renderTimeline();
}

function _restoreSavedEditorState() {
    const raw = sessionStorage.getItem('sts-editor-saved-state');
    if (!raw) return;
    sessionStorage.removeItem('sts-editor-saved-state');

    let saved;
    try { saved = JSON.parse(raw); } catch (e) { return; }

    // Re-apply scene-level properties from server save (overrides stale localStorage edits)
    if (saved.scenes?.length) {
        for (const ss of saved.scenes) {
            const scene = EditorState.scenes.find(s => s.id === (ss.id ?? ss.scene_id));
            if (!scene) continue;
            if (ss.visual_fx !== undefined) scene.visual_fx = ss.visual_fx;
            if (ss.duration !== undefined) scene.duration = ss.duration;
            if (ss.text_content !== undefined) scene.text_content = ss.text_content;
            if (ss.text_color !== undefined) scene.text_color = ss.text_color;
            if (ss.text_size !== undefined) scene.text_size = ss.text_size;
            if (ss.font_family !== undefined) scene.font_family = ss.font_family;
            if (ss.font_style !== undefined) scene.font_style = ss.font_style;
            if (ss.text_align !== undefined) scene.text_align = ss.text_align;
            if (ss.vertical_align !== undefined) scene.vertical_align = ss.vertical_align;
            if (ss.text_x !== undefined) scene.text_x = ss.text_x;
            if (ss.text_y !== undefined) scene.text_y = ss.text_y;
            if (ss.text_timeline_offset !== undefined) scene.text_timeline_offset = ss.text_timeline_offset;
            if (ss.text_overlay_duration !== undefined) scene.text_overlay_duration = ss.text_overlay_duration;
            if (ss.text_background_enabled !== undefined) scene.text_background_enabled = ss.text_background_enabled;
            if (ss.text_background_color !== undefined) scene.text_background_color = ss.text_background_color;
            if (ss.text_display_mode !== undefined) scene.text_display_mode = ss.text_display_mode;
            if (ss.text_hook_animation !== undefined) scene.text_hook_animation = ss.text_hook_animation;
            if (ss.text_animation !== undefined) scene.text_animation = ss.text_animation;
            if (ss.mediaUrl) scene.mediaUrl = ss.mediaUrl;
            if (ss.image_url) scene.mediaUrl = scene.mediaUrl || ss.image_url;
            normalizeSceneTextOverlay(scene);
        }
    }

    // Restore non-voice audio tracks (music, SFX)
    const nonVoiceTracks = saved.audio_tracks || [];
    for (const t of nonVoiceTracks) {
        const hasClips = t.clips && t.clips.length > 0;
        if (!hasClips && (!t.file || !t.path)) continue;
        const track = createAudioTrack({
            label: (t.label || t.type).replace(/\s*\d+$/, ''),
            type: t.type,
            file: t.file || null,
            path: t.path || null,
            duration: t.duration || 0,
            timelineOffset: t.timelineOffset || t.timeline_offset || 0,
            startOffset: t.startOffset || t.start_offset || 0,
            trimmedDuration: t.trimmedDuration || null,
            volume: t.volume ?? 1.0,
            loop: !!t.loop,
            duckingEnabled: !!t.duckingEnabled,
            duckingLevel: t.duckingLevel ?? DEFAULT_MUSIC_DUCKING_LEVEL,
            fadeIn: t.fadeIn || 0,
            fadeOut: t.fadeOut || 0
        });
        track.muted = !!t.muted;

        if (hasClips) {
            track.clips = [];
            track.loaded = true;
            for (const c of t.clips) {
                const clip = {
                    id: c.id || nextClipId(),
                    file: c.file, path: c.path, label: c.label,
                    duration: c.duration || 0, offset: c.offset || 0,
                    element: null,
                };
                const clipAudio = new Audio(c.path);
                clip.element = clipAudio;
                clipAudio.addEventListener('loadedmetadata', () => {
                    clip.duration = clipAudio.duration;
                    renderAllAudioTracks();
                });
                track.clips.push(clip);
            }
        } else {
            // Load audio element with Web Audio gain node for volume boost
            const audio = new Audio(t.path);
            track.element = audio;
            audio.loop = track.loop;
            ensureTrackGainNode(track);

            audio.addEventListener('loadedmetadata', () => {
                track.loaded = true;
                track.duration = audio.duration;
                renderAllAudioTracks();
            });
            audio.addEventListener('error', () => {
                track.error = true;
                renderAllAudioTracks();
            });
        }

        EditorState.audioTracks.push(track);
    }

    // Restore edit history
    if (saved.edit_history?.length) {
        EditorState.editHistory = saved.edit_history;
        EditorState.historyIndex = saved.history_index ?? saved.edit_history.length - 1;
    }

    // Restore disabled tracks
    if (saved.disabled_tracks?.length) {
        EditorState.disabledTracks = new Set(saved.disabled_tracks);
    }

    // Restore captions enabled state
    if (saved.captionsEnabled !== undefined) {
        EditorState.captionsEnabled = saved.captionsEnabled;
        const toggle = document.getElementById('caption-enabled-toggle');
        if (toggle) {
            toggle.checked = saved.captionsEnabled;
            const lbl = toggle.parentElement?.querySelector('.cap-card-toggle-label');
            if (lbl) lbl.textContent = saved.captionsEnabled ? 'On' : 'Off';
        }
        if (elements.captionTrackRow) {
            elements.captionTrackRow.style.display = saved.captionsEnabled ? '' : 'none';
        }
        if (EditorState.preview) {
            if (saved.captionsEnabled && EditorState.captionData) {
                EditorState.preview.setCaptions(EditorState.captionData.captions, EditorState.captionData.style || {});
            } else if (!saved.captionsEnabled) {
                EditorState.preview.setCaptions(null, null);
            }
        }
    }

    // Restore global overlays (support legacy string[] or new object[])
    const savedOverlays = saved.overlays
        ? (Array.isArray(saved.overlays) ? saved.overlays : [saved.overlays])
        : (saved.overlay ? [saved.overlay] : []);
    if (savedOverlays.length) {
        EditorState.overlays = savedOverlays.map(normalizeOverlayEntry);
        if (EditorState.preview) {
            EditorState.preview.setOverlay(EditorState.overlays);
        }
        updateOverlaysTab();
    }

    EditorState.grainOverlay = normalizeGrainOverlay(saved.grain_overlay || saved.grainOverlay || EditorState.grainOverlay);
    updateOverlaysTab();

    renderAllAudioTracks();
    renderTimeline();
}

function buildBootProjectData(raw) {
    if (!raw?.scenes?.length) return null;
    const captions = raw.captions?.captions?.length ? raw.captions : null;

    let runningTimestamp = 0;
    const scenes = raw.scenes.map((scene, index) => {
        const duration = Number(scene.duration) || 3;
        const timestamp = scene.timestamp ?? scene.timeline_start ?? runningTimestamp;
        runningTimestamp = Number(timestamp) + duration;

        return {
            scene_id: scene.scene_id ?? scene.id ?? scene.index ?? index,
            type: scene.type || scene.type_of_scene || 'image',
            image_prompt: scene.image_prompt || '',
            text_content: scene.text_content ?? null,
            duration,
            timestamp,
            image_url: scene.image_url || scene.mediaUrl || scene.image || '',
            asset_files: Array.isArray(scene.asset_files)
                ? scene.asset_files.filter(Boolean)
                : (Array.isArray(scene.files_on_disk)
                    ? scene.files_on_disk.map(file => file?.url).filter(Boolean)
                    : ((scene.image_url || scene.mediaUrl) ? [scene.image_url || scene.mediaUrl] : [])),
            visual_fx: scene.visual_fx || 'none',
            text_color: scene.text_color,
            text_size: scene.text_size,
            font_family: scene.font_family,
            font_style: scene.font_style,
            text_align: scene.text_align,
            vertical_align: scene.vertical_align,
            text_x: scene.text_x,
            text_y: scene.text_y,
            text_timeline_offset: scene.text_timeline_offset ?? 0,
            text_overlay_duration: scene.text_overlay_duration ?? null,
            text_background_enabled: !!scene.text_background_enabled,
            text_background_color: scene.text_background_color || '#000000',
            text_display_mode: scene.text_display_mode || null,
            text_hook_animation: scene.text_hook_animation || null,
        text_animation: scene.text_animation || null,
            script: scene.script || scene.segment_words || '',
            narrative_role: scene.narrative_role || '',
            isVideo: scene.isVideo ?? ((scene.type || scene.type_of_scene) === 'video'),
            image: scene.image || '',
            status: scene.status || ((scene.image_url || scene.mediaUrl || scene.image) ? 'ready' : 'pending'),
            filler_shift: scene.filler_shift || 0,
            segment_start: scene.segment_start ?? null,
            segment_end: scene.segment_end ?? null,
            segment_duration: scene.segment_duration ?? null
        };
    });

    return {
        project_id: raw.project_id || raw.projectId || 'default',
        project_name: raw.project_name || raw.project_id || raw.projectId || 'Untitled',
        style: raw.style || '',
        style_name: raw.style_name || '',
        style_color: raw.style_color || '',
        source_folder: raw.source_folder || '',
        story_tone: raw.story_tone || '',
        total_duration: raw.total_duration || scenes.reduce((sum, scene) => sum + (scene.duration || 0), 0),
        scene_count: raw.scene_count || scenes.length,
        staged_at: raw.staged_at || raw.saved_at || new Date().toISOString(),
        scenes,
        ...(captions ? {
            captions,
            captionsEnabled: raw.captionsEnabled ?? true
        } : {}),
        ...(raw.audio ? (() => {
            const audio = normalizeVoiceAudioConfig(raw.audio);
            return audio?.url ? { audio } : {};
        })() : (() => {
            // Extract audio from audio_tracks if no top-level audio key
            const vt = (raw.audio_tracks || []).find(t => t.type === 'voice');
            if (vt?.path) {
                const audio = normalizeVoiceAudioConfig({
                    url: vt.path,
                    source_file: vt.file || '',
                    duration: vt.duration || 0,
                    trimmedDuration: vt.trimmedDuration || null,
                    timelineOffset: vt.timelineOffset || vt.timeline_offset || 0,
                    startOffset: vt.startOffset || vt.start_offset || 0
                });
                if (audio?.url) return { audio };
            }
            return {};
        })())
    };
}

function getBootProjectData() {
    const stagedRaw = sessionStorage.getItem('sts-staged-timeline');
    if (stagedRaw) {
        try {
            return buildBootProjectData(JSON.parse(stagedRaw));
        } catch (error) {
            console.error('Failed to parse staged data:', error);
        }
    }

    const bootRaw = localStorage.getItem('sts-editor-boot-project');
    if (bootRaw) {
        try {
            return buildBootProjectData(JSON.parse(bootRaw));
        } catch (error) {
            console.error('Failed to parse editor boot data:', error);
        }
    }

    const bridgeRaw = localStorage.getItem('sts-editor-scenes');
    if (!bridgeRaw) return null;

    try {
        return buildBootProjectData(JSON.parse(bridgeRaw));
    } catch (error) {
        console.error('Failed to parse editor bridge data:', error);
        return null;
    }
}

function setEditorBootState(state) {
    const shell = document.getElementById('editor-shell');
    if (!shell) return;
    shell.classList.toggle('editor-shell-booting', state === 'booting');
    shell.classList.toggle('editor-shell-loading', state === 'loading');
    // Notify main app directly (no longer in iframe)
    if (typeof window._onEditorReady === 'function' && state !== 'booting') {
        window._onEditorReady(state);
    }
}

function beginEditorBootstrap(message = 'Loading...') {
    const bootId = Date.now() + Math.random();
    EditorState.activeBootstrapId = bootId;
    showLoadingOverlay(message);
    return bootId;
}

function isEditorBootstrapActive(bootId) {
    return EditorState.activeBootstrapId === bootId;
}

function assertEditorBootstrapActive(bootId) {
    if (!isEditorBootstrapActive(bootId)) {
        throw new Error('Editor load superseded by a newer request');
    }
}

function validateBootProjectData(data) {
    const errors = [];
    const warnings = [];
    const scenes = Array.isArray(data?.scenes) ? data.scenes : [];

    if (!data || typeof data !== 'object') {
        errors.push('Project payload is missing');
    }
    if (!String(data?.project_id || '').trim()) {
        errors.push('Project ID is missing');
    }
    if (!scenes.length) {
        errors.push('Project has no scenes');
    }

    scenes.forEach((scene, index) => {
        if (!scene) {
            errors.push(`Scene ${index + 1} is missing`);
            return;
        }
        if (!(Number(scene.duration) > 0)) {
            warnings.push(`Scene ${scene.scene_id ?? scene.id ?? index + 1} has an invalid duration`);
        }
    });

    return {
        ok: errors.length === 0,
        errors,
        warnings,
        sceneCount: scenes.length
    };
}

async function waitForVoiceAudioVerification(loadPromise = EditorState.voiceLoadPromise, timeoutMs = 12000) {
    if (!loadPromise || typeof loadPromise.then !== 'function') {
        return { status: 'skipped', reason: 'no-voice-load-promise' };
    }

    try {
        return await Promise.race([
            loadPromise,
            new Promise(resolve => setTimeout(() => resolve({
                status: 'timeout',
                reason: 'voice-audio-timeout',
                timeoutMs
            }), timeoutMs))
        ]);
    } catch (error) {
        return {
            status: 'error',
            reason: error?.message || 'voice-audio-verification-failed'
        };
    }
}

function validateLoadedEditorState({ mediaReport, voiceReport }) {
    const errors = [];
    const warnings = [];

    if (!EditorState.project?.id) {
        errors.push('Editor project state is empty');
    }
    if (!Array.isArray(EditorState.scenes) || EditorState.scenes.length === 0) {
        errors.push('Editor scenes were not initialized');
    }
    if (elements.previewCanvas && !EditorState.preview) {
        errors.push('Preview canvas failed to initialize');
    }

    if (EditorState.sceneErrors.size > 0) {
        warnings.push(`${EditorState.sceneErrors.size} scene${EditorState.sceneErrors.size === 1 ? '' : 's'} still have validation errors`);
    }
    if (mediaReport?.missingCount > 0) {
        warnings.push(`${mediaReport.missingCount} scene asset${mediaReport.missingCount === 1 ? '' : 's'} could not be verified`);
    }
    if (voiceReport?.status === 'error' || voiceReport?.status === 'timeout') {
        warnings.push('Voice audio could not be verified');
    }

    return {
        ok: errors.length === 0,
        errors,
        warnings
    };
}

async function bootstrapProjectIntoEditor(projectData, options = {}) {
    const {
        initialMessage = 'Initializing editor...',
        readyMessage = 'Editor ready',
        failureMessage = 'Failed to load project',
        showNoDataOnError = false,
        afterCoreLoad = null
    } = options;

    const bootId = beginEditorBootstrap(initialMessage);

    try {
        updateLoadingOverlay('Validating project data...');
        const projectValidation = validateBootProjectData(projectData);
        if (!projectValidation.ok) {
            throw new Error(projectValidation.errors[0]);
        }

        hideNoDataOverlay();

        updateLoadingOverlay('Loading fonts...');
        await ensureFontRegistryLoaded();
        assertEditorBootstrapActive(bootId);

        updateLoadingOverlay('Loading project data...');
        const { voiceLoadPromise } = await loadProjectData(projectData);
        assertEditorBootstrapActive(bootId);

        updateLoadingOverlay('Verifying scene media...');
        const mediaReport = await loadProjectMediaWithProgress();
        assertEditorBootstrapActive(bootId);

        updateLoadingOverlay('Verifying voice audio...');
        const voiceReport = await waitForVoiceAudioVerification(voiceLoadPromise);
        assertEditorBootstrapActive(bootId);

        updateLoadingOverlay('Applying saved editor state...');
        if (typeof afterCoreLoad === 'function') {
            await afterCoreLoad({ projectValidation, mediaReport, voiceReport });
        }
        assertEditorBootstrapActive(bootId);

        updateLoadingOverlay('Final verification...');
        validateScenes();
        applySceneErrorStyles();
        const finalValidation = validateLoadedEditorState({ mediaReport, voiceReport });
        if (!finalValidation.ok) {
            // Only hard-fail if scenes are truly empty — otherwise warn and continue
            if (!Array.isArray(EditorState.scenes) || EditorState.scenes.length === 0) {
                throw new Error(finalValidation.errors[0]);
            }
            console.warn('Editor bootstrap: soft validation errors (continuing):', finalValidation.errors);
            finalValidation.warnings.unshift(...finalValidation.errors);
            finalValidation.errors = [];
            finalValidation.ok = true;
        }

        await hideLoadingOverlay(bootId);
        if (!isEditorBootstrapActive(bootId)) {
            return { projectValidation, mediaReport, voiceReport, finalValidation, superseded: true };
        }
        EditorState.activeBootstrapId = 0;

        if (finalValidation.warnings.length > 0) {
            console.warn('Editor bootstrap warnings:', finalValidation.warnings);
            showToast(finalValidation.warnings[0], 'warning');
        }
        if (readyMessage) {
            showToast(readyMessage, 'success');
        }

        // Auto-select background music if none loaded and project has a story_tone
        _autoSelectBgMusic();

        return { projectValidation, mediaReport, voiceReport, finalValidation };
    } catch (error) {
        if (isEditorBootstrapActive(bootId)) {
            await hideLoadingOverlay(bootId);
            if (isEditorBootstrapActive(bootId)) {
                EditorState.activeBootstrapId = 0;
                showToast(`${failureMessage}: ${error.message}`, 'error');
                // Only show import overlay if scenes are truly empty — don't bounce
                // the user back to import if the project partially loaded
                if (showNoDataOnError && (!Array.isArray(EditorState.scenes) || EditorState.scenes.length === 0)) {
                    showNoDataOverlay();
                }
            }
        }
        throw error;
    }
}

let _captionBridgeListenerBound = false;

function ensureCaptionBridgeListener() {
    if (_captionBridgeListenerBound) return;
    window.addEventListener('message', (e) => {
        if (e.data && e.data.type === 'load-captions' && e.data.data) {
            _receiveCaptionData(e.data.data);
        }
    });
    _captionBridgeListenerBound = true;
}

function persistBootProjectData(raw, options = {}) {
    const bootData = buildBootProjectData(raw);
    if (!bootData) return null;

    try {
        sessionStorage.setItem('sts-staged-timeline', JSON.stringify(bootData));
    } catch (_) { /* ignore */ }

    try {
        localStorage.setItem('sts-editor-boot-project', JSON.stringify(bootData));
        localStorage.setItem('sts-editor-scenes', JSON.stringify(bootData));
        if (bootData.source_folder) {
            localStorage.setItem('sts-editor-source-folder', bootData.source_folder);
        } else {
            localStorage.removeItem('sts-editor-source-folder');
        }
        if (bootData.project_id) {
            localStorage.setItem('sts-editor-last-project-id', bootData.project_id);
            if (options.markSavedProject) {
                localStorage.setItem('sts-editor-last-saved-project-id', bootData.project_id);
            }
        }
        if (bootData.captions?.captions?.length) {
            localStorage.setItem('sts-editor-captions', JSON.stringify(bootData.captions));
        } else {
            localStorage.removeItem('sts-editor-captions');
        }
    } catch (_) { /* ignore */ }

    return bootData;
}

/**
 * Initialize the editor with sequential loading
 */
async function init() {
    console.log('Video Editor initializing...');

    // Re-query DOM elements (needed for Vue SPA re-navigation)
    refreshElements();

    // Always set up event listeners, even if no project is staged yet.
    // This ensures play, scrubber, effects, overlays, etc. work when
    // a project is loaded later via loadProjectFromServer().
    setupEventListeners();
    applySavedSettings();
    ensureCaptionBridgeListener();

    const editorEntrySource = sessionStorage.getItem('sts-editor-entry-source') || 'internal';
    // One-shot signal from Studio shell.
    sessionStorage.removeItem('sts-editor-entry-source');

    // When opened from the sidebar menu, always show the asset import list first.
    if (editorEntrySource === 'menu') {
        showNoDataOverlay(true);
        return;
    }

    // Prefer the staged timeline bridge, but survive refreshes with the localStorage bridge.
    const data = getBootProjectData();
    if (!data) {
        const lastSavedProjectId = localStorage.getItem('sts-editor-last-saved-project-id');
        if (lastSavedProjectId) {
            await loadProjectFromServer(lastSavedProjectId);
            return;
        }
        // Try to auto-load the most recent saved project before showing the import overlay
        if (editorEntrySource !== 'menu') {
            try {
                const savedProjects = await fetch('/api/editor/projects').then(r => r.json()).catch(() => []);
                if (savedProjects && savedProjects.length > 0) {
                    savedProjects.sort((a, b) => new Date(b.saved_at || 0) - new Date(a.saved_at || 0));
                    const mostRecent = savedProjects[0];
                    if (mostRecent.project_id) {
                        await loadProjectFromServer(mostRecent.project_id);
                        return;
                    }
                }
            } catch (e) {
                console.warn('Could not auto-load recent project:', e);
            }
        }
        showNoDataOverlay(true);
        return;
    }

    persistBootProjectData(data);

    try {
        await bootstrapProjectIntoEditor(data, {
            initialMessage: 'Initializing editor...',
            readyMessage: 'Editor ready',
            failureMessage: 'Failed to initialize editor',
            showNoDataOnError: true,
            afterCoreLoad: async () => {
                _loadCaptionsFromStorage();
                _restoreSavedEditorState();
            }
        });

        console.log('Video Editor initialized');
    } catch (error) {
        if (error.message !== 'Editor load superseded by a newer request') {
            console.warn('Editor initialization failed:', error);
        }
    }
}

/**
 * Sleep utility for sequential loading
 */
function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Load project data without media (fast)
 */
async function loadProjectData(data) {
    EditorState.project = {
        id: data.project_id,
        name: data.project_name,
        loadedFrom: data._source || 'initial',
        style: data.style || '',
        styleName: data.style_name || '',
        styleColor: data.style_color || '',
        sourceFolder: data.source_folder || '',
        storyTone: data.story_tone || '',
        totalDuration: data.total_duration,
        sceneCount: data.scene_count,
        stagedAt: data.staged_at
    };

    // Resolve style name/color from templates if missing
    if (EditorState.project.style && !EditorState.project.styleName) {
        try {
            const templates = await fetch('/api/scenes/templates').then(r => r.json());
            const tmpl = templates.find(t => t.id === EditorState.project.style);
            if (tmpl) {
                EditorState.project.styleName = tmpl.name;
                EditorState.project.styleColor = tmpl.color;
            }
        } catch { /* ignore */ }
    }

    EditorState.scenes = data.scenes.map(scene => ({
        ...scene,
        id: scene.id ?? scene.scene_id,
        mediaLoaded: !!scene.image_url,
        mediaUrl: scene.image_url || scene.mediaUrl || null,
        isVideo: scene.isVideo || isVideoFile(scene.image_url || scene.mediaUrl)
    }));
    persistBootProjectData({
        ...data,
        project_name: EditorState.project.name,
        style_name: EditorState.project.styleName,
        style_color: EditorState.project.styleColor
    }, {
        markSavedProject: EditorState.project.loadedFrom === 'wip' || EditorState.project.loadedFrom === 'initial'
    });
    EditorState.scenes.forEach(normalizeSceneTextOverlay);
    renderTextToolState();

    normalizeTimelineDurations(data.total_duration || 0);

    // Store original scenes for reset functionality
    EditorState.originalScenes = JSON.parse(JSON.stringify(EditorState.scenes));

    // Load saved edits from localStorage (if any)
    loadProjectEdits();

    normalizeTimelineDurations();

    // Load edit history from localStorage
    loadEditHistory();

    // Initialize Canvas Preview
    if (elements.previewCanvas) {
        EditorState.preview = new CanvasPreview(elements.previewCanvas, {
            onTimeUpdate: (time) => {
                EditorState.playbackPosition = time;
                updateTimeScrubber();
                updatePlayhead();

                // Enforce trimmed duration on non-looping tracks during playback
                if (EditorState.isPlaying) {
                    applyAudioFades();
                    for (const track of EditorState.audioTracks) {
                        // Multi-clip FX tracks
                        if (track.clips && track.clips.length > 0) {
                            for (const clip of track.clips) {
                                if (!clip.element) continue;
                                const clipStart = clip.offset;
                                const clipEnd = clip.offset + (clip.duration || 0);
                                const isActive = !track.muted && time >= clipStart && time < clipEnd;
                                if (!isActive) {
                                    if (!clip.element.paused) clip.element.pause();
                                    continue;
                                }
                                if (clip.element.paused) {
                                    clip.element.currentTime = time - clipStart;
                                    applyTrackVolumeLive(track, track.volume, { resumeContext: true });
                                    clip.element.play().catch(() => {});
                                }
                            }
                            continue;
                        }

                        if (!track.element || !track.file) continue;

                        const trackStart = getTrackTimelineOffset(track);
                        const trackEnd = getTrackTimelineEnd(track, getTotalDuration()) || Infinity;
                        const isActive = !track.muted && time >= trackStart && (track.loop || time < trackEnd);

                        if (!isActive) {
                            if (!track.element.paused) {
                                track.element.pause();
                            }
                            continue;
                        }

                        if (track.element.paused) {
                            track.element.currentTime = getTrackPlaybackTime(track, time);
                            applyTrackVolumeLive(track, track.volume, { resumeContext: true });
                            track.element.play().catch(() => {});
                        }
                    }
                    if (elements.timelineTracks) {
                        scrollTimelineToTime(time);
                    }
                }
            },
            onPlaybackEnd: () => {
                if (EditorState.isLooping) {
                    EditorState.playbackPosition = 0;
                    // Restart all audio tracks
                    seekAudio(0);
                    if (EditorState.preview) {
                        EditorState.preview.seek(0);
                        EditorState.preview.play();
                    }
                    syncAudioPlayback();
                    if (elements.timelineTracks) {
                        elements.timelineTracks.scrollLeft = 0;
                    }
                    updatePlayhead();
                    updateTimeScrubber();
                    return;
                }

                EditorState.isPlaying = false;
                // Stop all audio tracks
                for (const track of EditorState.audioTracks) {
                    if (track.clips && track.clips.length > 0) {
                        for (const clip of track.clips) {
                            if (clip.element) { clip.element.pause(); clip.element.currentTime = 0; }
                        }
                    }
                    if (track.element) {
                        track.element.pause();
                        track.element.currentTime = getTrackStartOffset(track);
                    }
                }
                if (EditorState.preview) {
                    EditorState.preview.setTimeSource(null);
                }
                EditorState.playbackPosition = 0;
                if (elements.timelineTracks) {
                    elements.timelineTracks.scrollLeft = 0;
                }
                updatePlayhead();
                updateTimeScrubber();
                updatePlayButton();
            }
        });

        EditorState.preview.setProjectPath(`working-assets/${EditorState.project.id}`);
        // setScenes triggers async preload + render; the main await
        // happens in loadProjectMediaWithProgress after URLs are verified.
        EditorState.preview.setScenes(EditorState.scenes);

        EditorState.preview.enableTextDrag((x, y, scene) => {
            if (!EditorState._textDragDebounce) {
                EditorState._textDragDebounce = setTimeout(() => {
                    recordEdit(`Move text position (Scene ${scene.id})`, scene.id, 'text_position', null, { x, y });
                    saveProjectEdits();
                    EditorState._textDragDebounce = null;
                }, 500);
            }
        });
    }

    EditorState.playbackPosition = 0;

    // Update UI
    updateProjectInfo();

    // Show/hide reset button depending on whether there are edits or WIP
    _updateResetButtonVisibility();

    // Sync flip-filler button active state
    const hasFlipped = EditorState.scenes.some(s => s.filler_shift && s.filler_shift !== 0);
    elements.flipFillerBtn?.classList.toggle('active', hasFlipped);

    renderTimeline();
    setupTimelineDragDrop();
    renderMediaGrid();
    renderTimeRuler();
    updateTimeScrubber();
    updatePlayhead();

    if (data.captions?.captions?.length) {
        _receiveCaptionData(data.captions);
        if (data.captionsEnabled === false) {
            EditorState.captionsEnabled = false;
            const toggle = document.getElementById('caption-enabled-toggle');
            if (toggle) {
                toggle.checked = false;
                const lbl = toggle.parentElement?.querySelector('.cap-card-toggle-label');
                if (lbl) lbl.textContent = 'Off';
            }
            if (elements.captionTrackRow) {
                elements.captionTrackRow.style.display = 'none';
            }
            if (EditorState.preview) {
                EditorState.preview.setCaptions(null, null);
            }
        }
    }

    // Load audio — use staged alignment URL when available
    EditorState.voiceLoadPromise = loadDefaultAudio(data);
    return { voiceLoadPromise: EditorState.voiceLoadPromise };
}

/**
 * Load project media with progress tracking.
 * Uses image_url from staged data when available, falls back to working-assets/ probing.
 */
async function loadProjectMediaWithProgress() {
    const projectId = EditorState.project?.id;
    if (!projectId) {
        console.warn('No project ID available for auto-loading media');
        return { projectId: '', totalScenes: 0, loadedCount: 0, missingCount: 0, missingSceneIds: [] };
    }

    const visualScenes = EditorState.scenes.filter(s => s.type !== 'text');
    const totalScenes = visualScenes.length;
    let loadedCount = 0;

    updateLoadingOverlay(`Loading assets (0/${totalScenes})...`);

    // ---- Phase 1: verify existing mediaUrls in parallel ----
    const scenesToProbe = [];
    const verifyPromises = [];
    for (let i = 0; i < EditorState.scenes.length; i++) {
        const scene = EditorState.scenes[i];
        if (scene.type === 'text') continue;
        if (scene.mediaUrl) {
            verifyPromises.push(
                checkMediaExists(scene.mediaUrl).then(ok => ({ scene, idx: i, ok }))
            );
        } else {
            scenesToProbe.push({ scene, idx: i });
        }
    }

    if (verifyPromises.length) {
        updateLoadingOverlay(`Verifying ${verifyPromises.length} known media paths...`);
        const results = await Promise.all(verifyPromises);
        for (const { scene, idx, ok } of results) {
            if (ok) {
                scene.isVideo = isVideoFile(scene.mediaUrl);
                loadedCount++;
                updateSceneClipThumb(scene.id, scene.mediaUrl, scene.isVideo, scene.videoThumb);
            } else {
                console.warn(`Scene ${idx}: mediaUrl failed (${scene.mediaUrl}), will probe`);
                scene.mediaUrl = null;
                scene.mediaLoaded = false;
                scenesToProbe.push({ scene, idx });
            }
        }
    }

    // ---- Phase 2: probe unknown scenes — batch HEAD requests per scene ----
    const basePath = `working-assets/${projectId}/`;
    const allExtensions = [...IMAGE_EXTENSIONS, ...VIDEO_EXTENSIONS];

    for (const { scene, idx: sceneNumber } of scenesToProbe) {
        updateLoadingOverlay(`Loading scene ${sceneNumber} (${loadedCount}/${totalScenes})...`);

        const assetsBasePath = `/output/animator/${projectId}/${sceneNumber}/`;
        const pathsToTry = [];
        if (scene.asset_files && scene.asset_files.length) {
            for (const af of scene.asset_files) {
                pathsToTry.push({ path: af, filename: af.split('/').pop() });
            }
        }
        for (const ext of allExtensions) {
            pathsToTry.push({ path: `${assetsBasePath}0.${ext}`, filename: `0.${ext}` });
        }
        for (const ext of allExtensions) {
            pathsToTry.push({ path: `${basePath}${sceneNumber}.${ext}`, filename: `${sceneNumber}.${ext}` });
        }
        if (scene.image) {
            pathsToTry.push({ path: `${basePath}${scene.image}`, filename: scene.image });
            const bareFilename = scene.image.split('/').pop();
            if (bareFilename !== scene.image) {
                pathsToTry.push({ path: `${basePath}${bareFilename}`, filename: bareFilename });
            }
        }

        // Fire all HEAD requests for this scene in parallel
        const probeResults = await Promise.all(
            pathsToTry.map(({ path: p, filename }) =>
                checkMediaExists(p).then(ok => ({ path: p, filename, ok }))
            )
        );

        const hit = probeResults.find(r => r.ok);
        if (hit) {
            scene.mediaUrl = hit.path;
            scene.mediaLoaded = true;
            scene.isVideo = isVideoFile(hit.path);
            scene.image = hit.filename;
            if (!Array.isArray(scene.asset_files) || scene.asset_files.length === 0) {
                scene.asset_files = [hit.path];
            }
            loadedCount++;
            console.log(`Scene ${sceneNumber}: found ${scene.isVideo ? 'video' : 'image'} ${hit.path}`);
            updateSceneClipThumb(scene.id, hit.path, scene.isVideo, scene.videoThumb);
        } else {
            console.warn(`Scene ${sceneNumber} (id: ${scene.id}): No media found`);
        }
    }

    // ---- Phase 3: generate server-side thumbnails for video scenes ----
    const videoScenes = EditorState.scenes.filter(s => s.isVideo && s.mediaUrl && !s.videoThumb);
    if (videoScenes.length) {
        updateLoadingOverlay(`Generating ${videoScenes.length} video thumbnails...`);

        // Ask server to generate _thumb.jpg for all videos in this project
        try {
            const thumbRes = await fetch(`/api/animator/thumbnails/${projectId}`, { method: 'POST' });
            if (thumbRes.ok) {
                const thumbData = await thumbRes.json();
                const thumbMap = {};
                for (const t of (thumbData.thumbnails || [])) {
                    thumbMap[t.video_url] = t.thumb_url;
                }
                let matched = 0;
                for (const scene of videoScenes) {
                    const thumbUrl = thumbMap[scene.mediaUrl] || thumbMap[scene.image_url];
                    if (thumbUrl) {
                        scene.videoThumb = thumbUrl;
                        updateSceneClipThumb(scene.id, scene.mediaUrl, true, thumbUrl);
                        matched++;
                    }
                }
                console.log(`Server thumbnails: ${(thumbData.thumbnails || []).length} generated, ${matched}/${videoScenes.length} matched`);
            } else {
                console.warn('Server thumbnail request failed:', thumbRes.status);
            }
        } catch (e) {
            console.warn('Server thumbnail generation failed, trying client-side:', e);
        }

        // Client-side fallback for any remaining scenes without thumbs
        const stillMissing = videoScenes.filter(s => !s.videoThumb && !s.videoDuration);
        if (stillMissing.length) {
            updateLoadingOverlay(`Loading ${stillMissing.length} video metadata...`);
            const metaResults = await Promise.all(
                stillMissing.map(s => getVideoMeta(s.mediaUrl).then(meta => ({ scene: s, meta })))
            );
            for (const { scene, meta } of metaResults) {
                if (meta) {
                    scene.videoDuration = meta.duration;
                    if (meta.thumbDataUrl) {
                        scene.videoThumb = meta.thumbDataUrl;
                        updateSceneClipThumb(scene.id, scene.mediaUrl, true, meta.thumbDataUrl);
                    }
                }
            }
        }
    }

    const scenesWithMedia = EditorState.scenes.filter(s => s.mediaUrl);
    const missingScenes = visualScenes.filter(scene => !scene.mediaUrl);
    console.log(`Auto-load complete: ${scenesWithMedia.length} scenes have mediaUrl`);
    persistBootProjectData({
        project_id: EditorState.project?.id,
        project_name: EditorState.project?.name,
        style: EditorState.project?.style,
        style_name: EditorState.project?.styleName,
        style_color: EditorState.project?.styleColor,
        source_folder: EditorState.project?.sourceFolder,
        total_duration: getTotalDuration(),
        scene_count: EditorState.scenes.length,
        staged_at: EditorState.project?.stagedAt,
        scenes: EditorState.scenes.map(scene => ({
            ...scene,
            image_url: scene.mediaUrl || scene.image_url || '',
            asset_files: Array.isArray(scene.asset_files) ? scene.asset_files : []
        })),
        ...(_getAudioForPersist())
    }, {
        markSavedProject: EditorState.project?.loadedFrom === 'wip' || EditorState.project?.loadedFrom === 'initial'
    });

    if (EditorState.preview) {
        updateLoadingOverlay(`Preloading ${scenesWithMedia.length} media elements...`);
        await EditorState.preview.setScenes(EditorState.scenes);
    }

    // Recalculate total duration (video scenes may have updated durations)
    recalculateDuration();

    if (scenesWithMedia.length > 0) {
        elements.previewPlaceholder?.classList.add('hidden');
        renderTimeline();
        renderMediaGrid();
        if (elements.mediaStatus) {
            const videoCount = scenesWithMedia.filter(s => s.isVideo).length;
            const imageCount = scenesWithMedia.length - videoCount;
            const parts = [];
            if (imageCount) parts.push(`${imageCount} image${imageCount > 1 ? 's' : ''}`);
            if (videoCount) parts.push(`${videoCount} video${videoCount > 1 ? 's' : ''}`);
            elements.mediaStatus.textContent = `${parts.join(' + ')} loaded`;
        }
        showToast(`Loaded ${scenesWithMedia.length} scene assets`, 'success');
    } else {
        showToast('No media found for this project', 'info');
    }

    return {
        projectId,
        totalScenes,
        loadedCount: scenesWithMedia.length,
        missingCount: missingScenes.length,
        missingSceneIds: missingScenes.map(scene => scene.id),
        videoCount: scenesWithMedia.filter(scene => scene.isVideo).length
    };
}

/**
 * Apply saved settings from localStorage
 */
function applySavedSettings() {
    // Apply saved timeline height
    const timelineHeight = EditorState.timelineHeight;
    if (elements.editorLayout) {
        elements.editorLayout.style.setProperty('--timeline-height', `${timelineHeight}px`);
    }
    updateClipSizes(timelineHeight);

    // Apply saved zoom level
    updateZoom();

    // Apply saved loop state
    if (EditorState.isLooping && elements.loopBtn) {
        elements.loopBtn.classList.add('active');
    }
}

// ===== SIMPLE LOADING OVERLAY =====

/**
 * Show unified loading overlay - single black screen with current step
 */
function showLoadingOverlay(message = 'Loading...') {
    let overlay = document.getElementById('loading-overlay');
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'loading-overlay';
        overlay.className = 'loading-overlay';
        overlay.innerHTML = `
            <div class="loading-content">
                <div class="loading-spinner"></div>
                <div class="loading-text">${message}</div>
            </div>
        `;
        document.body.appendChild(overlay);
    }
    overlay.classList.remove('fade-out');
    const textEl = overlay.querySelector('.loading-text');
    if (textEl) textEl.textContent = message;
    setEditorBootState('loading');
    return overlay;
}

/**
 * Update loading overlay text
 */
function updateLoadingOverlay(message) {
    const textEl = document.querySelector('.loading-overlay .loading-text');
    if (textEl) textEl.textContent = message;
}

/**
 * Hide loading overlay with fade
 */
function hideLoadingOverlay(bootId = null) {
    return new Promise(resolve => {
        const overlay = document.getElementById('loading-overlay');
        if (overlay) {
            overlay.classList.add('fade-out');
            setTimeout(() => {
                if (bootId !== null && !isEditorBootstrapActive(bootId)) {
                    resolve();
                    return;
                }
                overlay.remove();
                setEditorBootState('ready');
                resolve();
            }, 300);
        } else {
            if (bootId === null || isEditorBootstrapActive(bootId)) {
                setEditorBootState('ready');
            }
            resolve();
        }
    });
}

/**
 * Show the no data overlay — auto-loads asset list
 */
function showNoDataOverlay(showProjects = true) {
    // Never show import overlay if editor has a loaded project with scenes
    if (EditorState.scenes.length > 0 && EditorState.project?.id) {
        console.log('[Editor] showNoDataOverlay blocked — project already loaded:', EditorState.project.id, 'with', EditorState.scenes.length, 'scenes');
        return;
    }
    setEditorBootState('ready');
    // Tell Vue to render the overlay first
    if (typeof window._vueShowNoData === 'function') window._vueShowNoData();
    // Wait a frame for Vue to mount the DOM, then manipulate elements
    requestAnimationFrame(() => {
        elements.noDataOverlay = document.getElementById('no-data-overlay');
        elements.noDataOverlay?.classList.remove('hidden');
        if (showProjects) {
            _loadNoDataProjects();
            return;
        }
        const listContainer = document.getElementById('no-data-asset-list');
        const emptyEl = document.getElementById('no-data-empty');
        if (listContainer) listContainer.style.display = 'none';
        if (emptyEl) emptyEl.style.display = '';
    });
}

function _loadNoDataProjects() {
    const listEl = document.getElementById('no-data-asset-items');
    if (!listEl) return;

    listEl.innerHTML = '<p style="text-align:center;color:var(--text-muted,#666);font-size:12px;padding:24px 0">Loading...</p>';

    // Fetch both asset projects and saved editor projects in parallel
    Promise.all([
        fetch('/api/animator/history').then(r => r.json()).catch(() => []),
        fetch('/api/editor/projects').then(r => r.json()).catch(() => [])
    ]).then(([assetProjects, savedProjects]) => {
        // Re-query elements inside callback (Vue may have re-rendered)
        const listContainer = document.getElementById('no-data-asset-list');
        const emptyEl = document.getElementById('no-data-empty');
        if ((!assetProjects || !assetProjects.length) && (!savedProjects || !savedProjects.length)) {
            if (listContainer) listContainer.style.display = 'none';
            if (emptyEl) emptyEl.style.display = '';
            return;
        }
        if (listContainer) listContainer.style.display = '';
        if (emptyEl) emptyEl.style.display = 'none';

        const assetMap = {};
        const savedMap = {};
        for (const ap of (assetProjects || [])) {
            if (ap?.project_id) assetMap[ap.project_id] = ap;
        }
        for (const sp of (savedProjects || [])) {
            if (sp?.project_id) savedMap[sp.project_id] = sp;
        }

        const statusColors = {
            done: '#4ECDC4',
            saved: '#4ECDC4',
            edited: '#4ECDC4',
            downloading: '#FFB347',
            error: '#FF6B6B',
            waiting: '#8B8B8B',
            grabbing: '#A78BFA'
        };
        const esc = s => { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; };
        const timeAgo = ts => {
            if (!ts) return '';
            const parsed = new Date(ts).getTime();
            if (!Number.isFinite(parsed)) return '';
            const diff = (Date.now() - parsed) / 1000;
            if (diff < 60) return 'just now';
            if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
            if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
            return Math.floor(diff / 86400) + 'd ago';
        };
        const sortTime = p => {
            const parsed = new Date(p?.saved_at || p?.created_at || p?.timestamp || '').getTime();
            return Number.isFinite(parsed) ? parsed : 0;
        };

        const projects = [];
        for (const projectId of new Set([...Object.keys(assetMap), ...Object.keys(savedMap)])) {
            const asset = assetMap[projectId] || {};
            const saved = savedMap[projectId] || null;
            projects.push({
                ...asset,
                project_id: projectId,
                project_name: saved?.project_name || asset.project_name || projectId,
                scene_count: saved?.scene_count || asset.scene_count || 0,
                status: asset.status || (saved ? (saved.has_wip ? 'edited' : 'saved') : 'waiting'),
                saved_at: saved?.saved_at || '',
                preview: asset.preview || saved?.preview || '',
                ready_count: asset.ready_count || 0,
                disk_files: asset.disk_files || asset.total_files || 0,
                _saved: saved,
            });
        }
        projects.sort((a, b) => sortTime(b) - sortTime(a));

        listEl.innerHTML = projects.map(p => {
            const sc = statusColors[p.status] || '#8B8B8B';
            const files = p.disk_files || p.total_files || 0;
            const ready = p.ready_count || 0;
            const scenes = p.scene_count || 0;
            const time = timeAgo(p.saved_at || p.created_at || p.timestamp);
            const saved = p._saved;
            const isSaved = !!saved;

            // Saved projects load from server save; others import from assets
            const onclick = isSaved
                ? `loadProjectFromServer('${esc(p.project_id)}')`
                : `editorImportAssetProject('${esc(p.project_id)}')`;

            const savedBadge = isSaved
                ? `<svg width="12" height="12" fill="none" stroke="var(--accent,#4ECDC4)" stroke-width="2" viewBox="0 0 24 24" style="flex-shrink:0;opacity:0.8" title="Saved project"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>`
                : '';

            const savedTime = isSaved && saved.saved_at
                ? `<span style="color:var(--accent,#4ECDC4);opacity:0.8">${saved.has_wip ? 'edited ' : 'saved '}${timeAgo(saved.saved_at)}</span>`
                : '';

            return `
            <div data-pid="${esc(p.project_id)}" style="cursor:pointer;padding:10px 14px;border-radius:8px;border:1px solid transparent;transition:all 0.15s;margin-bottom:4px"
                 onclick="${onclick}"
                 onmouseover="this.style.background='var(--bg-darkest,#111)';this.style.borderColor='${isSaved ? 'var(--accent,#4ECDC4)' : 'var(--border,#2a2a3e)'}'"
                 onmouseout="this.style.background='';this.style.borderColor='transparent'">
                <div style="display:flex;align-items:center;gap:10px">
                    ${p.preview
                    ? '<div class="proj-thumb" style="width:40px;height:40px;border-radius:6px;overflow:hidden;flex-shrink:0;border:1px solid var(--border,#2a2a3e)"><img src="' + esc(p.preview) + '" style="width:100%;height:100%;object-fit:cover" /></div>'
                    : '<div class="proj-thumb" style="width:40px;height:40px;border-radius:6px;flex-shrink:0;background:var(--bg-darkest,#111);display:flex;align-items:center;justify-content:center"><svg width="18" height="18" fill="none" stroke="var(--text-muted,#666)" stroke-width="1.5" viewBox="0 0 24 24" style="opacity:0.4"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg></div>'}
                    <div style="flex:1;min-width:0">
                        <div style="display:flex;align-items:center;gap:6px;margin-bottom:2px">
                            <span style="font-size:12px;font-weight:600;color:var(--text,#e0e0e0);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(p.project_id)}</span>
                            ${savedBadge}
                            <span style="width:6px;height:6px;border-radius:50%;background:${sc};flex-shrink:0"></span>
                        </div>
                        <div style="display:flex;gap:6px;align-items:center;font-size:10px;font-family:'JetBrains Mono',monospace;color:var(--text-muted,#666);flex-wrap:wrap">
                            <span style="color:#4ECDC4">${scenes} scene${scenes !== 1 ? 's' : ''}</span>
                            ${ready > 0 ? '<span style="opacity:0.3">/</span><span style="color:#26DE81">' + ready + ' ready</span>' : ''}
                            ${files > 0 ? '<span style="opacity:0.3">/</span><span style="color:var(--text-secondary,#999)">' + files + ' files</span>' : ''}
                            <span style="opacity:0.3">/</span>
                            ${savedTime || '<span>' + time + '</span>'}
                        </div>
                    </div>
                    <svg width="14" height="14" fill="none" stroke="${isSaved ? 'var(--accent,#4ECDC4)' : 'var(--text-muted,#666)'}" stroke-width="1.5" viewBox="0 0 24 24" style="flex-shrink:0;opacity:0.4"><path d="M9 18l6-6-6-6"/></svg>
                </div>
            </div>`;
        }).join('');

        // Lazy thumbnail generation: for projects missing previews, generate in background then update
        const missingPreviews = projects.filter(p => !p.preview && (p.scene_count > 0 || p.disk_files > 0));
        if (missingPreviews.length > 0) {
            Promise.all(missingPreviews.map(p =>
                fetch(`/api/thumbnails/${encodeURIComponent(p.project_id)}/generate?modules=assets`, { method: 'POST' })
                    .then(r => r.json())
                    .then(data => ({ project_id: p.project_id, generated: data.total_generated || 0 }))
                    .catch(() => ({ project_id: p.project_id, generated: 0 }))
            )).then(results => {
                const updated = results.filter(r => r.generated > 0);
                if (updated.length > 0) {
                    // Update thumbnail images in-place
                    for (const r of updated) {
                        const url = `/api/thumbnails/${encodeURIComponent(r.project_id)}/assets/0.jpg`;
                        const card = listEl.querySelector(`[data-pid="${r.project_id}"]`);
                        if (card) {
                            const thumbEl = card.querySelector('.proj-thumb');
                            if (thumbEl) {
                                thumbEl.style.cssText = 'width:40px;height:40px;border-radius:6px;overflow:hidden;flex-shrink:0;border:1px solid var(--border,#2a2a3e)';
                                thumbEl.innerHTML = `<img src="${url}" style="width:100%;height:100%;object-fit:cover" />`;
                            }
                        }
                    }
                }
            });
        }
    }).catch(() => {
        if (listContainer) listContainer.style.display = 'none';
        if (emptyEl) emptyEl.style.display = '';
    });
}

/**
 * Hide the no data overlay
 */
function hideNoDataOverlay() {
    if (window._vueHideNoData) window._vueHideNoData();
    elements.noDataOverlay?.classList.add('hidden');
    if (typeof window._vueHideNoData === 'function') window._vueHideNoData();
}

// Old loading functions removed - replaced by sequential loading system

/**
 * Update a single scene clip thumbnail in the timeline
 */
function updateSceneClipThumb(sceneId, mediaPath, isVideo = false, videoThumbUrl = null) {
    const clip = document.querySelector(`.scene-clip[data-id="${sceneId}"]`);
    if (!clip) return;
    const thumb = clip.querySelector('.scene-clip-thumb');
    if (!thumb) return;

    const videoBadgeHtml = '<span class="media-video-badge" data-tooltip="Video"><svg width="8" height="8" viewBox="0 0 24 24" fill="currentColor"><polygon points="6,4 20,12 6,20"/></svg></span>';
    const imageBadgeHtml = '<span class="media-image-badge" data-tooltip="Image"><svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg></span>';

    if (isVideo && videoThumbUrl) {
        thumb.innerHTML = `<img src="${videoThumbUrl}" alt="Scene ${sceneId}">${videoBadgeHtml}`;
    } else if (isVideo) {
        thumb.classList.add('loading');
        // Try client-side canvas extraction first, fall back to server _thumb.jpg
        getVideoMeta(mediaPath).then(meta => {
            if (meta?.thumbDataUrl) {
                thumb.innerHTML = `<img src="${meta.thumbDataUrl}" alt="Scene ${sceneId}">${videoBadgeHtml}`;
                thumb.classList.remove('loading');
            } else if (mediaPath) {
                // Fall back to server-side _thumb.jpg
                const dotIdx = mediaPath.lastIndexOf('.');
                const thumbPath = dotIdx !== -1 ? mediaPath.substring(0, dotIdx) + '_thumb.jpg' : null;
                if (thumbPath) {
                    const img = new Image();
                    img.onload = () => {
                        thumb.innerHTML = `<img src="${thumbPath}" alt="Scene ${sceneId}">${videoBadgeHtml}`;
                        thumb.classList.remove('loading');
                    };
                    img.onerror = () => thumb.classList.remove('loading');
                    img.src = thumbPath;
                } else {
                    thumb.classList.remove('loading');
                }
            } else {
                thumb.classList.remove('loading');
            }
        });
    } else {
        thumb.classList.add('loading');
        const img = new Image();
        img.onload = () => {
            thumb.innerHTML = `<img src="${mediaPath}" alt="Scene ${sceneId}">${imageBadgeHtml}`;
            thumb.classList.remove('loading');
        };
        img.onerror = () => thumb.classList.remove('loading');
        img.src = mediaPath;
    }
}

/**
 * Render the media panel grid with scene thumbnails (CapCut-style)
 */
function renderMediaGrid() {
    const pane = document.querySelector('.med-section-body[data-section="media-assets"]') ||
                 document.querySelector('.tab-pane[data-pane="media"] .tab-pane-body');
    if (!pane || !EditorState.scenes.length) return;

    const emptyEl = pane.querySelector('.media-empty');
    if (emptyEl) emptyEl.style.display = 'none';

    let grid = pane.querySelector('.media-grid');
    if (!grid) {
        grid = document.createElement('div');
        grid.className = 'media-grid';
        pane.appendChild(grid);
    }

    grid.innerHTML = EditorState.scenes.map(scene => {
        const hasMedia = !!scene.mediaUrl;
        const isVid = scene.isVideo || (hasMedia && isVideoFile(scene.mediaUrl));
        const dur = (scene.duration || 0).toFixed(1);
        const icon = SCENE_ICONS[scene.type] || SCENE_ICONS.default;
        const label = scene.image_prompt
            ? scene.image_prompt.substring(0, 30)
            : `Scene ${scene.id}`;

        return `
            <div class="media-grid-item${EditorState.selectedScene?.id === scene.id ? ' selected' : ''}"
                 data-scene-id="${scene.id}" title="${(scene.image_prompt || 'Scene ' + scene.id).replace(/"/g, '&quot;')}">
                ${hasMedia
                ? (isVid && scene.videoThumb
                    ? `<img src="${scene.videoThumb}" alt="Scene ${scene.id}" style="width:100%;height:100%;object-fit:cover">
                       <span class="media-video-badge" data-tooltip="Video"><svg width="8" height="8" viewBox="0 0 24 24" fill="currentColor"><polygon points="6,4 20,12 6,20"/></svg></span>`
                    : isVid
                        ? `<video src="${scene.mediaUrl}" muted preload="metadata" style="width:100%;height:100%;object-fit:cover"></video>
                           <span class="media-video-badge" data-tooltip="Video"><svg width="8" height="8" viewBox="0 0 24 24" fill="currentColor"><polygon points="6,4 20,12 6,20"/></svg></span>`
                        : `<img src="${scene.mediaUrl}" alt="Scene ${scene.id}">`)
                : `<div class="media-grid-placeholder">${icon}</div>`}
                ${hasMedia ? '<span class="media-grid-badge" data-tooltip="Added"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><path d="M20 6L9 17l-5-5"/></svg></span>' : ''}
                <span class="media-grid-duration">${dur}s</span>
                <span class="media-grid-label">${label}</span>
            </div>`;
    }).join('');

    // Update scene count badge
    const sceneCountEl = document.getElementById('scene-assets-count');
    if (sceneCountEl) sceneCountEl.textContent = EditorState.scenes.length;

    // Click to select scene
    grid.querySelectorAll('.media-grid-item').forEach(item => {
        item.addEventListener('click', () => {
            const sceneId = parseInt(item.dataset.sceneId);
            selectScene(sceneId);
            renderMediaGrid();
            // Scroll timeline to this clip
            const clip = elements.videoTrack?.querySelector(`.scene-clip[data-id="${sceneId}"]`);
            if (clip) clip.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
        });
    });

    // Load project assets below the scene grid
    loadProjectAssets();
}

// ============================================================
// Project Asset Browser + Drag-to-Replace
// ============================================================

let _projectAssetsCache = null;
let _projectAssetsCacheId = null;

async function loadProjectAssets() {
    const projectId = EditorState.project?.id;
    if (!projectId) return;

    const slot = document.getElementById('project-assets-slot');
    if (!slot) return;

    // Reuse cache if same project
    if (_projectAssetsCacheId === projectId && _projectAssetsCache) {
        renderProjectAssets(slot, _projectAssetsCache);
        return;
    }

    // Show loading state
    slot.innerHTML = '<p style="text-align:center;color:var(--text-muted);font-size:11px;padding:16px 0;opacity:0.6">Loading project assets...</p>';

    try {
        const data = await fetch(`/api/animator/project/${encodeURIComponent(projectId)}`).then(r => r.ok ? r.json() : null);
        if (!data || !data.scenes) {
            slot.innerHTML = '<p style="text-align:center;color:var(--text-muted);font-size:11px;padding:16px 0;opacity:0.6">No assets found for this project</p>';
            return;
        }
        _projectAssetsCache = data;
        _projectAssetsCacheId = projectId;
        renderProjectAssets(slot, data);
    } catch (e) {
        slot.innerHTML = '<p style="text-align:center;color:var(--text-muted);font-size:11px;padding:16px 0;opacity:0.6">Could not load assets</p>';
    }
}

function renderProjectAssets(slot, data) {
    const sceneEntries = Object.entries(data.scenes)
        .sort(([a], [b]) => parseInt(a) - parseInt(b));

    // Collect all asset files across all scenes
    let totalFiles = 0;
    sceneEntries.forEach(([, info]) => {
        totalFiles += (info.files_on_disk || []).length;
    });

    if (totalFiles === 0) {
        slot.innerHTML = '<p style="text-align:center;color:var(--text-muted);font-size:11px;padding:16px 0;opacity:0.6">No asset files on disk</p>';
        return;
    }

    let html = `<div class="med-card-section">
        <button class="med-card-section-header med-section-toggle" aria-expanded="true" data-section="project-assets">
            <svg class="med-card-section-chevron" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg>
            <span class="med-card-section-icon med-card-section-icon--assets">
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
            </span>
            <span class="med-card-section-title">Project Assets</span>
            <span class="med-card-section-count med-card-section-count--assets">${totalFiles}</span>
            <span class="med-card-section-action" onclick="event.stopPropagation(); window.openProjectAssetsFolder()" title="Open folder">
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
            </span>
            <span class="med-card-section-action" onclick="event.stopPropagation(); window.reloadProjectAssets()" title="Reload assets">
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
            </span>
        </button>`;

    html += '<div class="med-card-section-body med-section-body" data-section="project-assets"><div class="asset-scene-grid">';
    sceneEntries.forEach(([sceneNum, info]) => {
        const files = info.files_on_disk || [];
        if (!files.length) return;

        const editorScene = EditorState.scenes.find(s => s.id === parseInt(sceneNum));
        const sceneLabel = editorScene?.image_prompt
            ? editorScene.image_prompt.substring(0, 25)
            : `Scene ${sceneNum}`;

        files.forEach(file => {
            const isActive = editorScene && editorScene.mediaUrl === file.url;
            html += `<div class="asset-thumb${isActive ? ' active' : ''}"
                          draggable="true"
                          data-url="${file.url.replace(/"/g, '&quot;')}"
                          data-scene="${sceneNum}"
                          title="Scene ${sceneNum} — ${file.filename}">
                ${/\.(mp4|webm|mov|avi|mkv)$/i.test(file.url) ? `<video src="${file.url}#t=0.1" muted preload="auto" style="width:100%;height:100%;object-fit:cover"
                    onmouseenter="this.play();this.nextElementSibling.style.opacity='0'"
                    onmouseleave="this.pause();this.currentTime=0.1;this.nextElementSibling.style.opacity='1'"></video><span class="vid-play-icon" style="position:absolute;top:4px;right:4px;width:18px;height:18px;border-radius:50%;background:rgba(0,0,0,0.6);display:flex;align-items:center;justify-content:center;pointer-events:none;transition:opacity 0.2s;z-index:1"><svg width="8" height="8" fill="white" viewBox="0 0 24 24"><polygon points="6,3 20,12 6,21"/></svg></span><span class="media-video-badge" data-tooltip="Video"><svg width="8" height="8" viewBox="0 0 24 24" fill="currentColor"><polygon points="6,4 20,12 6,20"/></svg></span>` : `<img src="${file.url}" alt="${file.filename}" loading="lazy"><span class="media-image-badge" data-tooltip="Image"><svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg></span>`}
                ${isActive ? '<span class="asset-thumb-active">In use</span>' : ''}
            </div>`;
        });
    });
    html += '</div></div></div>';

    slot.innerHTML = html;

    // Wire collapsible Project Assets header
    slot.querySelectorAll('.med-section-toggle').forEach(btn => {
        btn.addEventListener('click', (e) => {
            if (e.target.closest('.med-card-section-action')) return;
            const section = btn.dataset.section;
            // Search siblings in the same container
            const parent = btn.parentElement;
            const body = parent.querySelector(`.med-section-body[data-section="${section}"]`);
            const expanded = btn.getAttribute('aria-expanded') === 'true';
            btn.setAttribute('aria-expanded', String(!expanded));
            if (body) body.style.display = expanded ? 'none' : '';
        });
    });

    // Attach drag events to asset thumbnails
    slot.querySelectorAll('.asset-thumb[draggable]').forEach(thumb => {
        thumb.addEventListener('dragstart', (e) => {
            const url = thumb.dataset.url;
            e.dataTransfer.setData('text/plain', url);
            e.dataTransfer.setData('application/x-asset-url', url);
            e.dataTransfer.effectAllowed = 'copy';
            thumb.classList.add('dragging');
            (document.getElementById('editor-shell') || document.body).classList.add('asset-dragging');
        });
        thumb.addEventListener('dragend', () => {
            thumb.classList.remove('dragging');
            (document.getElementById('editor-shell') || document.body).classList.remove('asset-dragging');
            // Remove all drop highlights
            document.querySelectorAll('.scene-clip.drop-target').forEach(el => el.classList.remove('drop-target'));
        });
        // Click to apply to selected scene
        thumb.addEventListener('click', () => {
            const scene = EditorState.selectedScene;
            if (!scene) {
                showToast('Select a scene on the timeline first', 'info');
                return;
            }
            applyAssetToScene(scene, thumb.dataset.url);
        });
    });
}

function applyAssetToScene(scene, url) {
    const oldUrl = scene.mediaUrl;
    if (oldUrl === url) return;

    scene.mediaUrl = url;
    scene.image_url = url;
    scene.mediaLoaded = true;
    scene.isVideo = isVideoFile(url);

    recordEdit(`Replace media (Scene ${scene.id})`, scene.id, 'mediaUrl', oldUrl, url);
    updateSceneClipThumb(scene.id, url, scene.isVideo);
    renderMediaGrid();
    renderSceneProperties();

    if (EditorState.preview) {
        EditorState.preview.imageCache.delete(scene.id);
        EditorState.preview.setScenes(EditorState.scenes);
    }

    // Auto-save
    saveProjectEdits();

    showToast(`Scene ${scene.id} image replaced`, 'success');
}

function setupTimelineDragDrop() {
    const track = elements.videoTrack;
    if (!track) return;

    track.addEventListener('dragover', (e) => {
        if (!e.dataTransfer.types.includes('application/x-asset-url')) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = 'copy';

        // Highlight the clip under cursor
        const clip = e.target.closest('.scene-clip');
        track.querySelectorAll('.scene-clip.drop-target').forEach(el => el.classList.remove('drop-target'));
        if (clip) clip.classList.add('drop-target');
    });

    track.addEventListener('dragleave', (e) => {
        if (!e.target.closest('.scene-clip')) {
            track.querySelectorAll('.scene-clip.drop-target').forEach(el => el.classList.remove('drop-target'));
        }
    });

    track.addEventListener('drop', (e) => {
        e.preventDefault();
        track.querySelectorAll('.scene-clip.drop-target').forEach(el => el.classList.remove('drop-target'));
        (document.getElementById('editor-shell') || document.body).classList.remove('asset-dragging');

        const url = e.dataTransfer.getData('application/x-asset-url');
        if (!url) return;

        const clip = e.target.closest('.scene-clip');
        if (!clip) return;

        const sceneId = parseInt(clip.dataset.id);
        const scene = EditorState.scenes.find(s => s.id === sceneId);
        if (!scene) return;

        applyAssetToScene(scene, url);
    });

    // Also support drop on the media grid items
    const mediaPane = document.querySelector('.tab-pane[data-pane="media"] .med-card') ||
                      document.querySelector('.tab-pane[data-pane="media"] .tab-pane-body');
    if (mediaPane) {
        mediaPane.addEventListener('dragover', (e) => {
            if (!e.dataTransfer.types.includes('application/x-asset-url')) return;
            const gridItem = e.target.closest('.media-grid-item');
            if (!gridItem) return;
            e.preventDefault();
            e.dataTransfer.dropEffect = 'copy';
            mediaPane.querySelectorAll('.media-grid-item.drop-target').forEach(el => el.classList.remove('drop-target'));
            gridItem.classList.add('drop-target');
        });

        mediaPane.addEventListener('dragleave', (e) => {
            if (!e.target.closest('.media-grid-item')) {
                mediaPane.querySelectorAll('.media-grid-item.drop-target').forEach(el => el.classList.remove('drop-target'));
            }
        });

        mediaPane.addEventListener('drop', (e) => {
            e.preventDefault();
            mediaPane.querySelectorAll('.media-grid-item.drop-target').forEach(el => el.classList.remove('drop-target'));
            (document.getElementById('editor-shell') || document.body).classList.remove('asset-dragging');

            const url = e.dataTransfer.getData('application/x-asset-url');
            if (!url) return;

            const gridItem = e.target.closest('.media-grid-item');
            if (!gridItem) return;

            const sceneId = parseInt(gridItem.dataset.sceneId);
            const scene = EditorState.scenes.find(s => s.id === sceneId);
            if (!scene) return;

            applyAssetToScene(scene, url);
        });
    }
}

/**
 * Check if an image exists at the given path
 */
function checkImageExists(imagePath) {
    return fetch(imagePath, { method: 'HEAD', signal: AbortSignal.timeout(4000) })
        .then(res => res.ok)
        .catch(() => false);
}

const VIDEO_EXTENSIONS = ['mp4', 'webm', 'mov'];
const IMAGE_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp', 'gif'];

/**
 * Check if a media file (image or video) exists via HEAD request
 */
function checkMediaExists(mediaPath) {
    return fetch(mediaPath, { method: 'HEAD', signal: AbortSignal.timeout(4000) })
        .then(res => res.ok)
        .catch(() => false);
}

/**
 * Determine if a file path is a video
 */
function isVideoFile(path) {
    const ext = (path || '').split('.').pop().toLowerCase();
    return VIDEO_EXTENSIONS.includes(ext);
}

/**
 * Load video metadata (duration) and capture a poster thumbnail.
 * Returns { duration, thumbDataUrl } or null on failure.
 */
function getVideoMeta(videoUrl) {
    return new Promise((resolve) => {
        const timeout = setTimeout(() => {
            video.src = '';
            resolve(null);
        }, 12000);
        const done = (result) => { clearTimeout(timeout); video.src = ''; resolve(result); };
        const video = document.createElement('video');
        video.muted = true;
        video.crossOrigin = 'anonymous';
        video.preload = 'auto';
        video.onloadeddata = () => {
            const duration = video.duration;
            // Seek to 1s or 10% for a representative frame
            video.currentTime = Math.min(1, duration * 0.1);
            video.onseeked = () => {
                let thumbDataUrl = null;
                try {
                    if (video.videoWidth > 0 && video.videoHeight > 0) {
                        const c = document.createElement('canvas');
                        c.width = video.videoWidth;
                        c.height = video.videoHeight;
                        c.getContext('2d').drawImage(video, 0, 0);
                        thumbDataUrl = c.toDataURL('image/jpeg', 0.7);
                    }
                } catch (_) { /* cross-origin / tainted canvas */ }
                done({ duration, thumbDataUrl });
            };
        };
        video.onerror = () => done(null);
        video.src = videoUrl;
    });
}

/**
 * Load audio — uses staged voice audio when available, otherwise resolves the scene audio file.
 * Creates or updates the voice track in audioTracks[].
 */
async function loadDefaultAudio(stagedData) {
    const projectId = EditorState.project?.id || 'default';
    const voiceLoadToken = ++EditorState.voiceLoadToken;
    const isStale = () => EditorState.voiceLoadToken !== voiceLoadToken;
    const sourceFolder = EditorState.project?.sourceFolder || projectId;
    const triedPaths = stagedData?._triedPaths || [];
    const resolvedAudio = await resolveDefaultVoiceAudio(projectId, sourceFolder, stagedData?.audio);
    if (isStale()) {
        return { status: 'stale', reason: 'superseded-before-audio-resolve' };
    }
    const candidatePaths = [
        resolvedAudio?.url || '',
        ...getDefaultVoiceAudioFallbacks(projectId, sourceFolder)
    ].filter((path, index, arr) => path && arr.indexOf(path) === index && !triedPaths.includes(path));

    if (!candidatePaths.length) {
        console.warn('No voice audio path available for project:', projectId);
        return {
            status: 'skipped',
            reason: 'no-voice-audio-candidate',
            projectId,
            sourceFolder
        };
    }
    const audioPath = candidatePaths[0];
    const audioFileName = getPathFileName(audioPath) || resolvedAudio?.source_file || 'voice.wav';
    console.log('Using voice audio URL:', audioPath);

    // Create or reuse voice track
    let voiceTrack = getVoiceTrack();
    if (!voiceTrack) {
        voiceTrack = createAudioTrack({ label: 'Voice', type: 'voice', color: AUDIO_TRACK_COLORS.voice });
        EditorState.audioTracks.unshift(voiceTrack);
    }

    // Stop previous element if any
    if (voiceTrack.element) { voiceTrack.element.pause(); voiceTrack.element.src = ''; }
    voiceTrack._gainNode = null;

    const audio = new Audio();
    audio.preload = 'auto';
    voiceTrack.element = audio;
    voiceTrack.file = audioFileName;
    voiceTrack.path = audioPath;
    voiceTrack.duration = resolvedAudio?.duration || 0;
    voiceTrack.loaded = false;
    voiceTrack.error = false;

    // Legacy compat
    EditorState.audioElement = audio;
    EditorState.audio = voiceTrack;
    ensureTrackGainNode(voiceTrack);

    const loadResultPromise = new Promise((resolve) => {
        let handledMetadata = false;
        let settled = false;
        const resolveResult = (result) => {
            if (settled) return;
            settled = true;
            resolve(result);
        };

        const handleLoadedMetadata = () => {
            if (handledMetadata || isStale()) return;
            handledMetadata = true;
            voiceTrack.duration = audio.duration;
            voiceTrack.loaded = true;
            voiceTrack.error = false;

            const savedTrim = EditorState.savedAudioSettings || resolvedAudio || null;
            if (savedTrim) {
                applyTrackTrimState(voiceTrack, {
                    timelineOffset: savedTrim.timelineOffset ?? savedTrim.timeline_offset ?? 0,
                    startOffset: savedTrim.startOffset ?? savedTrim.start_offset ?? 0,
                    trimmedDuration: savedTrim.trimmedDuration ?? savedTrim.trimmed_duration ?? null
                });
                console.log('Restored audio trim:', { startOffset: voiceTrack.startOffset, trimmedDuration: voiceTrack.trimmedDuration });
            }

            normalizeTimelineDurations(getTrackTimelineEnd(voiceTrack, audio.duration) || audio.duration);

            recalculateDuration();
            renderTimeline();
            renderAllAudioTracks();
            showToast('Audio loaded: ' + formatTimestamp(getTrackVisibleDuration(voiceTrack) || audio.duration), 'success');
            resolveResult({
                status: 'loaded',
                projectId,
                sourceFolder,
                path: audioPath,
                file: audioFileName,
                duration: audio.duration
            });
        };

        audio.addEventListener('loadedmetadata', handleLoadedMetadata);

        audio.addEventListener('error', async (e) => {
            if (isStale()) {
                resolveResult({ status: 'stale', path: audioPath, file: audioFileName });
                return;
            }

            console.warn('Failed to load audio:', audioPath, e);

            const nextTriedPaths = [...triedPaths, audioPath];
            const lookedUpAudio = await resolveDefaultVoiceAudio(projectId, sourceFolder, null);
            const nextFallbacks = [
                lookedUpAudio?.url || '',
                ...getDefaultVoiceAudioFallbacks(projectId, sourceFolder)
            ].filter((path, index, arr) => path && arr.indexOf(path) === index && !nextTriedPaths.includes(path));

            if (nextFallbacks.length > 0) {
                const nextPath = nextFallbacks[0];
                console.log('Trying audio fallback:', nextPath);
                const nextResult = await loadDefaultAudio({
                    audio: {
                        ...(resolvedAudio || {}),
                        ...(lookedUpAudio || {}),
                        url: nextPath,
                        source_file: getPathFileName(nextPath)
                    },
                    _triedPaths: nextTriedPaths
                });
                resolveResult(nextResult);
                return;
            }

            voiceTrack.loaded = false;
            voiceTrack.error = true;
            renderAllAudioTracks();
            showToast('Audio not found', 'warning');
            resolveResult({
                status: 'error',
                projectId,
                sourceFolder,
                path: audioPath,
                file: audioFileName,
                triedPaths: nextTriedPaths
            });
        });

        audio.src = audioPath;
        audio.load();
        if (audio.readyState >= 1 && Number.isFinite(audio.duration)) {
            queueMicrotask(handleLoadedMetadata);
        }

        // Initial render (before duration is known)
        renderAllAudioTracks();
    });

    EditorState.voiceLoadPromise = loadResultPromise;
    return loadResultPromise;
}

/**
 * Load audio from a URL (used by TTS picker and other sources)
 * Updates the voice track in audioTracks[].
 */
function loadAudioFromURL(audioPath, audioFileName, hintDuration) {
    const voiceLoadToken = ++EditorState.voiceLoadToken;
    const isStale = () => EditorState.voiceLoadToken !== voiceLoadToken;
    // Create or reuse voice track
    let voiceTrack = getVoiceTrack();
    if (!voiceTrack) {
        voiceTrack = createAudioTrack({ label: 'Voice', type: 'voice', color: AUDIO_TRACK_COLORS.voice });
        EditorState.audioTracks.unshift(voiceTrack);
    }

    // Stop previous element
    if (voiceTrack.element) { voiceTrack.element.pause(); voiceTrack.element.src = ''; }
    voiceTrack._gainNode = null;

    const audio = new Audio();
    audio.preload = 'auto';
    voiceTrack.element = audio;
    voiceTrack.file = audioFileName;
    voiceTrack.path = audioPath;
    voiceTrack.duration = hintDuration || 0;
    voiceTrack.loaded = false;
    voiceTrack.error = false;

    // Legacy compat
    EditorState.audioElement = audio;
    EditorState.audio = voiceTrack;
    ensureTrackGainNode(voiceTrack);

    const loadResultPromise = new Promise((resolve) => {
        let handledMetadata = false;
        let settled = false;
        const resolveResult = (result) => {
            if (settled) return;
            settled = true;
            resolve(result);
        };

        const handleLoadedMetadata = () => {
            if (handledMetadata || isStale()) return;
            handledMetadata = true;
            voiceTrack.duration = audio.duration;
            voiceTrack.loaded = true;
            voiceTrack.error = false;
            const savedTrim = EditorState.savedAudioSettings || null;
            if (savedTrim) {
                applyTrackTrimState(voiceTrack, {
                    timelineOffset: savedTrim.timelineOffset ?? savedTrim.timeline_offset ?? 0,
                    startOffset: savedTrim.startOffset ?? savedTrim.start_offset ?? 0,
                    trimmedDuration: savedTrim.trimmedDuration ?? savedTrim.trimmed_duration ?? null
                });
            }

            const audioDur = getTrackTimelineEnd(voiceTrack, audio.duration) || audio.duration;
            const scenesDur = getScenesDuration();
            if (EditorState.scenes.length > 0 && audioDur > scenesDur + 0.05) {
                const lastScene = EditorState.scenes[EditorState.scenes.length - 1];
                const gap = parseFloat((audioDur - scenesDur).toFixed(3));
                lastScene.duration = parseFloat((lastScene.duration + gap).toFixed(3));
            } else if (EditorState.scenes.length > 0 && scenesDur > audioDur + 0.05) {
                const ratio = audioDur / scenesDur;
                EditorState.scenes.forEach(s => {
                    s.duration = parseFloat((s.duration * ratio).toFixed(3));
                });
                renderTimeline();
            }

            recalculateDuration();
            renderAllAudioTracks();
            saveProjectEdits();
            showToast('Audio loaded: ' + formatTimestamp(getTrackVisibleDuration(voiceTrack) || audio.duration), 'success');
            resolveResult({
                status: 'loaded',
                path: audioPath,
                file: audioFileName,
                duration: audio.duration
            });
        };

        audio.addEventListener('loadedmetadata', handleLoadedMetadata);

        audio.addEventListener('error', () => {
            if (isStale()) {
                resolveResult({ status: 'stale', path: audioPath, file: audioFileName });
                return;
            }

            voiceTrack.loaded = false;
            voiceTrack.error = true;
            renderAllAudioTracks();
            showToast(`Audio not found: ${audioFileName}`, 'warning');
            resolveResult({
                status: 'error',
                path: audioPath,
                file: audioFileName
            });
        });

        audio.src = audioPath;
        audio.load();
        if (audio.readyState >= 1 && Number.isFinite(audio.duration)) {
            queueMicrotask(handleLoadedMetadata);
        }

        renderAllAudioTracks();
    });

    EditorState.voiceLoadPromise = loadResultPromise;
    return loadResultPromise;
}

// Listen for audio load requests from the TTS picker
window.addEventListener('editor-load-audio', (e) => {
    const { url, filename, duration } = e.detail;
    loadAudioFromURL(url, filename, duration);
});

// Handle aspect ratio changes from the dropdown
window.addEventListener('editor-ratio-change', (e) => {
    const { ratio, width, height } = e.detail;
    if (EditorState.preview) {
        EditorState.preview.width = width;
        EditorState.preview.height = height;
        EditorState.preview.render();
    }
    // Update detail panel
    const infoRatio = document.getElementById('info-ratio');
    const infoRes = document.getElementById('info-resolution');
    if (infoRatio) infoRatio.textContent = ratio;
    if (infoRes) infoRes.textContent = `${width}x${height}`;
});

/**
 * Render audio track with loaded audio - uses helper for width calculation
 */
function renderAudioTrack() {
    if (!elements.audioTrack) return;

    if (EditorState.audio && EditorState.audio.file) {
        // Use trimmed duration if set, otherwise use actual audio duration
        const audioDuration = EditorState.audio.trimmedDuration ||
            (EditorState.audio.loaded ? EditorState.audio.duration : EditorState.project.totalDuration);
        const totalWidth = timeToPixels(audioDuration);

        // Show error state if audio failed to load
        const errorClass = EditorState.audio.error ? 'audio-clip-error' : '';
        const statusText = EditorState.audio.error ? '(not found)' : formatTimestamp(audioDuration);

        elements.audioTrack.innerHTML = `
            <div class="audio-clip ${errorClass}" style="width: ${totalWidth}px;">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M9 18V5l12-2v13"/>
                    <circle cx="6" cy="18" r="3"/>
                    <circle cx="18" cy="16" r="3"/>
                </svg>
                <span class="audio-clip-name">${EditorState.audio.file}</span>
                <span class="audio-clip-duration">${statusText}</span>
                <div class="resize-handle resize-handle-right audio-resize-handle"></div>
            </div>
        `;

        // Setup audio resize handler
        setupAudioResizeHandler();
    } else {
        elements.audioTrack.innerHTML = `
            <div class="audio-placeholder">Click + to add background audio</div>
        `;
    }
}

/**
 * Setup resize handler for audio clip
 */
function setupAudioResizeHandler() {
    const audioClip = elements.audioTrack?.querySelector('.audio-clip');
    const resizeHandle = audioClip?.querySelector('.audio-resize-handle');

    if (!resizeHandle || !EditorState.audio?.loaded) return;

    resizeHandle.addEventListener('mousedown', (e) => {
        e.stopPropagation();
        startAudioResize(e);
    });
}

/**
 * Start resizing the audio clip
 */
function startAudioResize(startEvent) {
    if (!EditorState.audio?.loaded) return;

    const startX = startEvent.clientX;
    const startDuration = EditorState.audio.trimmedDuration || EditorState.audio.duration;
    const maxDuration = EditorState.audio.duration; // Can't extend beyond original audio length

    const audioClip = elements.audioTrack?.querySelector('.audio-clip');
    const durationSpan = audioClip?.querySelector('.audio-clip-duration');

    const onMouseMove = (e) => {
        const deltaX = e.clientX - startX;
        const deltaDuration = pixelsToTime(deltaX);

        // Calculate new duration (min 1s, max original audio duration)
        let newDuration = Math.max(1, Math.min(maxDuration, startDuration + deltaDuration));

        // Snap to 0.5s increments
        newDuration = Math.round(newDuration * 2) / 2;

        // Update audio trimmed duration
        EditorState.audio.trimmedDuration = newDuration;

        // Update clip width visually
        if (audioClip) {
            const newWidth = timeToPixels(newDuration);
            audioClip.style.width = `${newWidth}px`;
        }

        // Update duration display
        if (durationSpan) {
            durationSpan.textContent = formatTimestamp(newDuration);
        }
    };

    const onMouseUp = () => {
        document.removeEventListener('mousemove', onMouseMove);
        document.removeEventListener('mouseup', onMouseUp);

        const newDuration = EditorState.audio.trimmedDuration || EditorState.audio.duration;

        // Record the edit if duration actually changed
        if (newDuration !== startDuration) {
            recordEdit('Resize audio duration', 'audio', 'trimmedDuration', startDuration, newDuration);
        }

        // Recalculate total duration
        recalculateDuration();
        renderTimeRuler();

        // Update preview duration
        if (EditorState.preview) {
            EditorState.preview.setDuration(getTotalDuration());
        }

        showToast(`Audio duration: ${formatTimestamp(newDuration)}`, 'info');
    };

    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
}

// ---------------------------------------------------------------------------
// Universal Audio Track Renderer
// ---------------------------------------------------------------------------

/**
 * Render all audio tracks into #audio-tracks-container.
 * Replaces both renderAudioTrack() and renderBgMusicTrack().
 */
function renderAllAudioTracks() {
    const container = document.getElementById('audio-tracks-container');
    if (!container) return;

    const tracks = EditorState.audioTracks;
    if (!tracks.length) {
        container.innerHTML = '';
        return;
    }

    const pps = EditorState.pixelsPerSecond * EditorState.zoomLevel;
    const timelineDur = getTotalDuration() || EditorState.project?.totalDuration || 60;

    container.innerHTML = tracks.map(track => {
        const isVoice = track.type === 'voice';
        const isSfx = isSfxTrackType(track.type);
        const color = track.color || AUDIO_TRACK_COLORS[track.type] || AUDIO_TRACK_COLORS.voice;
        const trackLabel = track.label || (isVoice ? 'Voice' : track.type === 'music' ? 'Music' : 'SFX');
        const displayFile = isVoice
            ? (getPathFileName(track.path) || track.file || trackLabel)
            : (track.file || getPathFileName(track.path) || trackLabel);

        // Build clip HTML
        let clipHTML;
        const hasClips = track.clips && track.clips.length > 0;
        if (hasClips) {
            // Multi-clip FX track: render each clip independently
            const selectedClass = EditorState.selectedAudioTrack?.id === track.id ? ' selected' : '';
            clipHTML = track.clips.map(clip => {
                const cDur = clip.duration || 1;
                const cWidth = cDur * pps;
                const cOffsetPx = clip.offset * pps;
                return `
                    <div class="audio-clip-wrap fx-multi-clip" data-track-id="${track.id}" data-clip-id="${clip.id}" style="position:absolute; width:${cWidth}px; left:${cOffsetPx}px;">
                        <span class="audio-clip-tag" style="background:${color}">${clip.label || clip.file || 'FX'}</span>
                        <div class="audio-clip-universal${selectedClass}" data-track-id="${track.id}" data-clip-id="${clip.id}" style="width:100%; border-left: 3px solid ${color};">
                            <span class="audio-clip-duration">${formatTimestamp(cDur)}</span>
                        </div>
                    </div>`;
            }).join('');
            // Wrap in a relative container so absolute clips position correctly
            clipHTML = `<div class="fx-multi-clip-lane" data-track-id="${track.id}" style="position:relative; width:100%; min-height:28px;">${clipHTML}</div>`;
        } else if (track.file || track.path) {
            const duration = isVoice
                ? (getTrackTimelineDuration(track, EditorState.project?.totalDuration || timelineDur) || track.duration || EditorState.project?.totalDuration || 0)
                : (getTrackTimelineDuration(track, timelineDur) || (track.loop ? timelineDur : track.duration));
            const width = duration * pps;
            const offsetPx = timeToPixels(getTrackTimelineOffset(track));
            const errorClass = track.error ? 'audio-clip-universal-error' : '';
            const statusText = track.error ? '(not found)' : formatTimestamp(duration);

            // Music icon for music tracks, waveform icon for voice/fx
            const icon = track.type === 'music'
                ? `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="flex-shrink:0;opacity:0.5"><circle cx="5.5" cy="17.5" r="2.5"/><circle cx="17.5" cy="15.5" r="2.5"/><path d="M8 17.5V5l12-2v12.5"/></svg>`
                : `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="flex-shrink:0;opacity:0.5"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>`;

            const selectedClass = EditorState.selectedAudioTrack?.id === track.id ? ' selected' : '';
            // Fade handle positioning
            const fadeInSec = track.fadeIn || 0;
            const fadeOutSec = track.fadeOut || 0;
            const fadeInPx = duration > 0 ? (fadeInSec / duration) * width : 0;
            const fadeOutPx = duration > 0 ? (fadeOutSec / duration) * width : 0;
            const showFadeIn = fadeInSec > 0 || track.type === 'music';
            const showFadeOut = fadeOutSec > 0 || track.type === 'music';
            const fadeInHandle = showFadeIn
                ? `<div class="audio-fade-handle audio-fade-in" data-track-id="${track.id}" style="left:${fadeInPx}px;" title="Fade in: ${fadeInSec.toFixed(1)}s"></div>`
                : '';
            const fadeOutHandle = showFadeOut
                ? `<div class="audio-fade-handle audio-fade-out" data-track-id="${track.id}" style="right:${fadeOutPx}px;" title="Fade out: ${fadeOutSec.toFixed(1)}s"></div>`
                : '';
            clipHTML = `
                <div class="audio-clip-wrap" data-track-id="${track.id}" style="width:${width}px; margin-left:${offsetPx}px;">
                    <span class="audio-clip-tag" style="background:${color}">${displayFile}</span>
                    <div class="audio-clip-universal ${errorClass}${selectedClass}" data-track-id="${track.id}" style="width:100%; border-left: 3px solid ${color};">
                        <canvas class="audio-waveform-canvas" data-track-id="${track.id}"></canvas>
                        <span class="audio-clip-duration">${statusText}</span>
                        <div class="audio-resize-handle-universal audio-resize-left" data-track-id="${track.id}"></div>
                        <div class="audio-resize-handle-universal audio-resize-right" data-track-id="${track.id}"></div>
                        ${fadeInHandle}
                        ${fadeOutHandle}
                    </div>
                </div>`;
        } else {
            const emptyLabel = isVoice
                ? 'voice audio'
                : (isSfx ? 'sound FX — drag SFX here' : 'audio');
            clipHTML = `
                <div class="audio-placeholder audio-track-empty-target"
                     data-track-id="${track.id}"
                     style="width:100%; min-height:28px; display:flex; align-items:center; opacity:0.3; font-size:0.55rem; padding:0 8px; font-style:italic; color:var(--text-muted)">
                    Click to add ${emptyLabel}
                </div>`;
        }

        // Speaker icon (for volume popup)
        const mutedClass = track.muted ? ' muted' : '';
        const speakerIcon = track.muted
            ? `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><line x1="23" y1="9" x2="17" y2="15"/><line x1="17" y1="9" x2="23" y2="15"/></svg>`
            : `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 010 14.14M15.54 8.46a5 5 0 010 7.08"/></svg>`;

        // Gear menu button (for non-voice tracks)
        const gearBtn = !isVoice
            ? `<button class="audio-track-gear-btn" data-track-id="${track.id}" data-track-type="${track.type}" title="Track options"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 01-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/></svg></button>`
            : '';

        return `
            <div class="track" data-track="audio-${track.id}" data-audio-track-id="${track.id}">
                <div class="track-header" style="display:flex; flex-direction:column; align-items:center; gap:2px;">
                    <button class="audio-track-speaker-btn${mutedClass}" data-track-id="${track.id}" title="${trackLabel} — Vol ${Math.round(track.volume * 100)}%">
                        ${speakerIcon}
                    </button>
                    <button class="audio-track-solo-btn${track.id === EditorState.soloTrackId ? ' active' : ''}" data-track-id="${track.id}" title="Solo">S</button>
                    <span class="track-label">${trackLabel}</span>
                    ${gearBtn}
                </div>
                <div class="track-content" style="display:flex; align-items:center; min-height:28px;">
                    ${clipHTML}
                </div>
            </div>`;
    }).join('');

    // Wire up resize handles + edge hover indicators + fade handles
    setupAllAudioResizeHandlers();
    setupAudioFadeHandlers();
    setupAudioResizeHoverIndicators(container);
    setupAudioTrackDragHandlers(container);
    if (typeof _wireFxTrackDropZones === 'function') _wireFxTrackDropZones();

    // Wire up speaker buttons (volume popup)
    container.querySelectorAll('.audio-track-speaker-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const trackId = btn.dataset.trackId;
            toggleVolumePopup(trackId, btn);
        });
    });

    // Wire up solo buttons
    container.querySelectorAll('.audio-track-solo-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            toggleSolo(btn.dataset.trackId);
        });
    });

    // Wire up gear menu buttons
    container.querySelectorAll('.audio-track-gear-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            _showTrackGearMenu(btn.dataset.trackId, btn.dataset.trackType, btn);
        });
    });

    // Wire up empty-track placeholders — click to show add-track menu
    container.querySelectorAll('.audio-track-empty-target').forEach(el => {
        el.style.cursor = 'pointer';
        el.addEventListener('mousedown', (e) => {
            if (e.button !== 0) return;
            e.stopPropagation();
        });
        el.addEventListener('click', (e) => {
            e.stopPropagation();
            const trackId = el.dataset.trackId;
            if (!trackId) {
                const addTrackRow = document.getElementById('add-track-row');
                if (addTrackRow) showAddTrackMenu(addTrackRow);
                return;
            }

            selectAudioTrack(trackId);
            promptAudioFileUpload(trackId);
        });
    });

    // Wire up clip click to select audio track for detail panel
    container.querySelectorAll('.audio-clip-universal').forEach(clip => {
        clip.addEventListener('click', (e) => {
            if (e.target.classList.contains('audio-resize-handle-universal')) return;
            if (clip.dataset.suppressClick === '1') {
                delete clip.dataset.suppressClick;
                return;
            }
            const trackId = clip.dataset.trackId;
            selectAudioTrack(trackId);
        });
    });

    // Draw waveforms after DOM layout so canvas has correct dimensions
    requestAnimationFrame(() => {
        for (const track of tracks) {
            if (!track.file) continue;
            const canvas = container.querySelector(`.audio-waveform-canvas[data-track-id="${track.id}"]`);
            if (track._waveformData) {
                drawWaveformCanvas(canvas, track);
            } else if (!track._waveformLoading) {
                generateWaveformData(track).then(() => {
                    const c = container.querySelector(`.audio-waveform-canvas[data-track-id="${track.id}"]`);
                    drawWaveformCanvas(c, track);
                });
            }
        }
    });
}

/**
 * Setup resize handlers for all audio track clips
 */
function setupAllAudioResizeHandlers() {
    document.querySelectorAll('.audio-resize-handle-universal').forEach(handle => {
        handle.addEventListener('mousedown', (e) => {
            e.stopPropagation();
            const trackId = handle.dataset.trackId;
            const track = getAudioTrackById(trackId);
            if (!track || (!track.loaded && track.type === 'voice')) return;
            const handleSide = handle.classList.contains('audio-resize-left') ? 'left' : 'right';
            startUniversalAudioResize(e, track, handleSide);
        });
    });
}

/**
 * Setup drag handlers for fade in/out handles on audio clips.
 */
function setupAudioFadeHandlers() {
    document.querySelectorAll('.audio-fade-handle').forEach(handle => {
        handle.addEventListener('mousedown', (e) => {
            e.stopPropagation();
            e.preventDefault();
            const trackId = handle.dataset.trackId;
            const track = getAudioTrackById(trackId);
            if (!track) return;
            const isFadeIn = handle.classList.contains('audio-fade-in');
            startAudioFadeDrag(e, track, isFadeIn, handle);
        });
    });
}

/**
 * Drag handler for adjusting fade in/out duration on an audio clip.
 */
function startAudioFadeDrag(startEvent, track, isFadeIn, handle) {
    const clip = document.querySelector(`.audio-clip-universal[data-track-id="${track.id}"]`);
    const waveformCanvas = clip?.querySelector('.audio-waveform-canvas');
    if (!clip) return;

    const clipRect = clip.getBoundingClientRect();
    const timelineDur = getTotalDuration() || 60;
    const duration = getTrackVisibleDuration(track) || getTrackTimelineDuration(track, timelineDur) || track.duration || 1;
    const maxFade = duration / 2;
    const oldValue = isFadeIn ? (track.fadeIn || 0) : (track.fadeOut || 0);

    handle.classList.add('active');
    document.body.style.cursor = 'col-resize';

    const onMouseMove = (e) => {
        const currentRect = clip.getBoundingClientRect();
        let newFade;
        if (isFadeIn) {
            // Fade in: distance from left edge of clip
            const px = e.clientX - currentRect.left;
            newFade = Math.max(0, Math.min(maxFade, pixelsToTime(px)));
        } else {
            // Fade out: distance from right edge of clip
            const px = currentRect.right - e.clientX;
            newFade = Math.max(0, Math.min(maxFade, pixelsToTime(px)));
        }
        // Snap to 0.1s
        newFade = Math.round(newFade * 10) / 10;

        if (isFadeIn) {
            track.fadeIn = newFade;
            handle.style.left = `${timeToPixels(newFade)}px`;
            handle.title = `Fade in: ${newFade.toFixed(1)}s`;
        } else {
            track.fadeOut = newFade;
            handle.style.right = `${timeToPixels(newFade)}px`;
            handle.title = `Fade out: ${newFade.toFixed(1)}s`;
        }

        if (waveformCanvas) drawWaveformCanvas(waveformCanvas, track);
    };

    const onMouseUp = () => {
        document.removeEventListener('mousemove', onMouseMove);
        document.removeEventListener('mouseup', onMouseUp);
        handle.classList.remove('active');
        document.body.style.cursor = '';

        const newValue = isFadeIn ? (track.fadeIn || 0) : (track.fadeOut || 0);
        const field = isFadeIn ? 'fadeIn' : 'fadeOut';
        if (newValue !== oldValue) {
            recordEdit(`${isFadeIn ? 'Fade in' : 'Fade out'} ${track.label}`, track.id, field, oldValue, newValue);
            showToast(`${track.label} ${isFadeIn ? 'fade in' : 'fade out'}: ${newValue.toFixed(1)}s`, 'info');
        }
    };

    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
}

/**
 * Show the resize cue only on the clip edge nearest the pointer.
 */
function setupAudioResizeHoverIndicators(root = document) {
    root.querySelectorAll('.audio-clip-universal').forEach(clip => {
        const updateHoverEdge = (clientX) => {
            if (clip.classList.contains('audio-resizing')) return;

            const rect = clip.getBoundingClientRect();
            const hoverX = clientX - rect.left;
            const edgeThreshold = Math.min(18, Math.max(10, rect.width * 0.12), rect.width / 2);

            clip.classList.remove('resize-hover-left', 'resize-hover-right', 'drag-hover-middle');

            if (hoverX <= edgeThreshold) {
                clip.classList.add('resize-hover-left');
            } else if ((rect.width - hoverX) <= edgeThreshold) {
                clip.classList.add('resize-hover-right');
            } else {
                clip.classList.add('drag-hover-middle');
            }
        };

        clip.addEventListener('mouseenter', (e) => updateHoverEdge(e.clientX));
        clip.addEventListener('mousemove', (e) => updateHoverEdge(e.clientX));
        clip.addEventListener('mouseleave', () => {
            if (!clip.classList.contains('audio-resizing')) {
                clip.classList.remove('resize-hover-left', 'resize-hover-right', 'drag-hover-middle');
            }
        });
    });
}

function setupAudioTrackDragHandlers(root = document) {
    root.querySelectorAll('.audio-clip-universal').forEach(clip => {
        clip.addEventListener('mousedown', (e) => {
            if (e.button !== 0) return;
            if (e.target.closest('.audio-resize-handle-universal')) return;
            if (e.target.closest('.audio-fade-handle')) return;
            if (clip.classList.contains('resize-hover-left') || clip.classList.contains('resize-hover-right')) return;
            startAudioTrackDrag(e, clip.dataset.trackId);
        });
    });
}

function startAudioTrackDrag(startEvent, trackId) {
    const track = getAudioTrackById(trackId);
    const clip = document.querySelector(`.audio-clip-universal[data-track-id="${trackId}"]`);
    const clipWrap = clip?.closest('.audio-clip-wrap');
    if (!track || !clip || !clipWrap) return;

    startEvent.preventDefault();
    const startX = startEvent.clientX;
    const startOffset = getTrackTimelineOffset(track);
    let moved = false;

    clip.classList.add('audio-dragging');
    clip.classList.remove('drag-hover-middle', 'resize-hover-left', 'resize-hover-right');

    const onMouseMove = (e) => {
        const deltaX = e.clientX - startX;
        let newOffset = Math.max(0, startOffset + pixelsToTime(deltaX));
        // Scene boundary snap takes priority, then fall back to 0.5s grid
        const snapped = snapToSceneBoundary(newOffset, 8);
        newOffset = snapped !== newOffset ? snapped : Math.round(newOffset * 2) / 2;
        moved = moved || Math.abs(deltaX) > 2;

        track.timelineOffset = newOffset;
        clipWrap.style.marginLeft = `${timeToPixels(newOffset)}px`;

        if (track.element) {
            track.element.currentTime = getTrackPlaybackTime(track, EditorState.playbackPosition);
            if (EditorState.isPlaying) {
                const timelineEnd = getTrackTimelineEnd(track, getTotalDuration());
                if (EditorState.playbackPosition < newOffset || EditorState.playbackPosition >= timelineEnd) {
                    track.element.pause();
                } else if (!track.muted && track.file) {
                    track.element.play().catch(() => {});
                }
            }
        }
    };

    const onMouseUp = () => {
        document.removeEventListener('mousemove', onMouseMove);
        document.removeEventListener('mouseup', onMouseUp);
        clip.classList.remove('audio-dragging');
        clip.classList.add('drag-hover-middle');

        if (moved) {
            clip.dataset.suppressClick = '1';
            recalculateDuration();
            renderTimeRuler();
            if (EditorState.preview) EditorState.preview.setDuration(getTotalDuration());
            if (track.timelineOffset !== startOffset) {
                recordEdit(`Move ${track.label}`, track.id, 'timelineOffset', startOffset, track.timelineOffset);
            }
        }
    };

    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
}

/**
 * Generic audio resize for any track
 */
function startUniversalAudioResize(startEvent, track, handleSide = 'right') {
    const startX = startEvent.clientX;
    const timelineDur = getTotalDuration() || 60;
    const startTrim = {
        timelineOffset: getTrackTimelineOffset(track),
        startOffset: getTrackStartOffset(track),
        trimmedDuration: getTrackVisibleDuration(track) || (track.loop ? timelineDur : track.duration)
    };
    const sourceDuration = Math.max(track.duration || 0, startTrim.trimmedDuration || 0);
    const minDuration = getTrackMinDuration(track);
    const maxRightDuration = track.loop ? 3600 : Math.max(minDuration, sourceDuration - startTrim.startOffset);

    const clip = document.querySelector(`.audio-clip-universal[data-track-id="${track.id}"]`);
    const clipWrap = clip?.closest('.audio-clip-wrap');
    const waveformCanvas = clip?.querySelector('.audio-waveform-canvas');
    const durationSpan = clip?.querySelector('.audio-clip-duration');
    if (clip) {
        clip.classList.add('audio-resizing');
        clip.classList.remove('resize-hover-left', 'resize-hover-right');
        clip.classList.add(handleSide === 'left' ? 'resize-hover-left' : 'resize-hover-right');
    }

    const onMouseMove = (e) => {
        const deltaX = e.clientX - startX;
        const deltaDuration = pixelsToTime(deltaX);
        let nextTrim;

        if (handleSide === 'left') {
            const maxDelta = startTrim.trimmedDuration - minDuration;
            const minDelta = -Math.min(startTrim.startOffset, startTrim.timelineOffset);
            const trimDelta = Math.max(minDelta, Math.min(deltaDuration, maxDelta));
            const newTimelineOffset = startTrim.timelineOffset + trimDelta;
            const newStartOffset = startTrim.startOffset + trimDelta;
            const newDuration = startTrim.trimmedDuration - trimDelta;

            nextTrim = applyTrackTrimState(track, {
                timelineOffset: Math.round(newTimelineOffset * 2) / 2,
                startOffset: Math.round(newStartOffset * 2) / 2,
                trimmedDuration: Math.round(newDuration * 2) / 2
            });
        } else {
            let newDuration = Math.max(minDuration, Math.min(maxRightDuration, startTrim.trimmedDuration + deltaDuration));
            newDuration = Math.round(newDuration * 2) / 2; // snap 0.5s
            nextTrim = applyTrackTrimState(track, {
                startOffset: startTrim.startOffset,
                trimmedDuration: newDuration
            });
        }

        const newWidthPx = timeToPixels(nextTrim?.trimmedDuration || getTrackVisibleDuration(track));
        if (clipWrap) {
            clipWrap.style.width = `${newWidthPx}px`;
            clipWrap.style.marginLeft = `${timeToPixels(nextTrim?.timelineOffset || getTrackTimelineOffset(track))}px`;
            clip.style.width = '100%';
        } else if (clip) {
            clip.style.width = `${newWidthPx}px`;
        }
        if (durationSpan) durationSpan.textContent = formatTimestamp(nextTrim?.trimmedDuration || getTrackVisibleDuration(track));
        if (waveformCanvas) drawWaveformCanvas(waveformCanvas, track);
        if (track.element) {
            track.element.currentTime = getTrackPlaybackTime(track, EditorState.playbackPosition);
            if (EditorState.isPlaying) {
                const timelineStart = getTrackTimelineOffset(track);
                const timelineEnd = getTrackTimelineEnd(track, getTotalDuration());
                if (EditorState.playbackPosition < timelineStart || EditorState.playbackPosition >= timelineEnd) {
                    track.element.pause();
                } else if (!track.muted && track.file) {
                    track.element.play().catch(() => {});
                }
            }
        }
    };

    const onMouseUp = () => {
        document.removeEventListener('mousemove', onMouseMove);
        document.removeEventListener('mouseup', onMouseUp);
        if (clip) {
            clip.classList.remove('audio-resizing', 'resize-hover-left', 'resize-hover-right');
        }

        const newTrim = {
            timelineOffset: getTrackTimelineOffset(track),
            startOffset: getTrackStartOffset(track),
            trimmedDuration: getTrackVisibleDuration(track) || track.duration
        };
        if (track.element && track.element.paused) {
            track.element.currentTime = getTrackPlaybackTime(track, EditorState.playbackPosition);
        }

        if (handleSide === 'left') {
            if (newTrim.startOffset !== startTrim.startOffset || newTrim.trimmedDuration !== startTrim.trimmedDuration) {
                recordEdit(`Trim ${track.label} start`, track.id, 'trimRange', startTrim, newTrim);
            }
        } else if (newTrim.trimmedDuration !== startTrim.trimmedDuration) {
            recordEdit(`Resize ${track.label} duration`, track.id, 'trimmedDuration', startTrim.trimmedDuration, newTrim.trimmedDuration);
        }
        recalculateDuration();
        renderTimeRuler();
        if (EditorState.preview) EditorState.preview.setDuration(getTotalDuration());
        showToast(`${track.label} duration: ${formatTimestamp(newTrim.trimmedDuration)}`, 'info');
    };

    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
}

/**
 * Toggle volume popup for a given audio track
 */
function _showTrackGearMenu(trackId, trackType, anchorBtn) {
    // Close any existing gear menu
    document.querySelector('.track-gear-menu')?.remove();

    const menu = document.createElement('div');
    menu.className = 'track-gear-menu';

    const isMusic = trackType === 'music';
    const items = [];

    if (isMusic) {
        items.push({ icon: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><polyline points="16 3 21 3 21 8"/><line x1="4" y1="20" x2="21" y2="3"/><polyline points="21 16 21 21 16 21"/><line x1="15" y1="15" x2="21" y2="21"/><line x1="4" y1="4" x2="9" y2="9"/></svg>`, label: 'Random', action: () => { menu.remove(); _replaceMusicTrackRandom(trackId); } });
        items.push({ icon: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M21 2v6h-6"/><path d="M3 12a9 9 0 0115.4-6.4L21 8"/><path d="M3 22v-6h6"/><path d="M21 12a9 9 0 01-15.4 6.4L3 16"/></svg>`, label: 'Replace', action: () => { menu.remove(); removeAudioTrack(trackId); if (typeof showMusicPicker === 'function') showMusicPicker(); } });
    }
    items.push({ icon: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 6h18"/><path d="M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/></svg>`, label: 'Remove', cls: 'danger', action: () => { menu.remove(); removeAudioTrack(trackId); } });

    menu.innerHTML = items.map(it =>
        `<button class="track-gear-item${it.cls ? ' ' + it.cls : ''}">${it.icon}<span>${it.label}</span></button>`
    ).join('');

    // Position
    const rect = anchorBtn.getBoundingClientRect();
    menu.style.position = 'fixed';
    menu.style.left = `${rect.left}px`;
    menu.style.top = `${rect.bottom + 4}px`;
    menu.style.zIndex = '300';
    document.body.appendChild(menu);

    // Wire actions
    menu.querySelectorAll('.track-gear-item').forEach((btn, i) => {
        btn.addEventListener('click', (e) => { e.stopPropagation(); items[i].action(); });
    });

    // Close on click outside
    const close = (e) => {
        if (!menu.contains(e.target) && e.target !== anchorBtn) {
            menu.remove();
            document.removeEventListener('mousedown', close);
        }
    };
    setTimeout(() => document.addEventListener('mousedown', close), 0);
}

function toggleVolumePopup(trackId, anchorBtn) {
    const track = getAudioTrackById(trackId);
    if (!track) return;

    // Close any existing popup
    const existing = document.querySelector('.volume-popup');
    if (existing) {
        const existingTrackId = existing.dataset.trackId;
        existing.remove();
        if (existingTrackId === trackId) return; // was toggling same popup off
    }

    const popup = document.createElement('div');
    popup.className = 'volume-popup';
    popup.dataset.trackId = trackId;
    const volPct = Math.round(track.volume * 100);
    const isDucked = track.type === 'music' && track.duckingEnabled;
    const duckPct = isDucked ? Math.round((track.duckingLevel ?? DEFAULT_MUSIC_DUCKING_LEVEL) * 100) : 0;
    const duckRow = isDucked
        ? `<div style="display:flex; align-items:center; gap:10px; padding:4px 12px 8px;">
            <button class="ducking-toggle-btn" title="Toggle ducking" style="background:none;border:none;color:var(--text-secondary);cursor:pointer;padding:4px;display:flex;">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 20l2.7-6.8a6 6 0 011.2-1.8L18 1l-2 6 6-2L12 17.1a6 6 0 01-1.8 1.2L4 21z"/></svg>
            </button>
            <input type="range" class="ducking-slider volume-slider" min="5" max="100" step="1" value="${duckPct}" style="width:120px;">
            <span class="ducking-label" style="font-size:10px; font-family:var(--font-mono); color:var(--text-secondary); min-width:32px; text-align:right;">${duckPct}%</span>
          </div>
          <div class="ducking-note" style="font-size:9px; color:var(--text-muted); padding:0 12px 6px; font-family:var(--font-mono);">Ducking to ${duckPct}% when voice plays</div>`
        : '';
    popup.innerHTML = `
        <div style="display:flex; align-items:center; gap:10px; padding:8px 12px;">
            <button class="volume-mute-toggle" title="${track.muted ? 'Unmute' : 'Mute'}" style="background:none;border:none;color:${track.muted ? 'var(--coral)' : 'var(--text-secondary)'};cursor:pointer;padding:4px;display:flex;">
                ${track.muted
                    ? '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><line x1="23" y1="9" x2="17" y2="15"/><line x1="17" y1="9" x2="23" y2="15"/></svg>'
                    : '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 010 14.14M15.54 8.46a5 5 0 010 7.08"/></svg>'}
            </button>
            <input type="range" class="volume-slider" min="0" max="300" step="1" value="${volPct}" style="width:120px;">
            <span class="volume-label" style="font-size:10px; font-family:var(--font-mono); color:var(--text-secondary); min-width:32px; text-align:right;">${volPct}%</span>
        </div>
        ${duckRow}
    `;

    // Position popup near the speaker button
    const rect = anchorBtn.getBoundingClientRect();
    popup.style.position = 'fixed';
    popup.style.left = `${rect.right + 4}px`;
    popup.style.top = `${rect.top - 4}px`;
    popup.style.zIndex = '200';
    document.body.appendChild(popup);

    // Wire slider — update volume immediately on every drag tick
    const slider = popup.querySelector('.volume-slider');
    const label = popup.querySelector('.volume-label');
    const volBefore = track.volume;

    // One-time setup: ensure AudioContext + gain node are ready on first interaction
    let _audioReady = false;
    const _ensureAudio = async () => {
        if (_audioReady) return;
        if (!EditorState._audioCtx) {
            EditorState._audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        }
        if (EditorState._audioCtx.state === 'suspended') {
            await EditorState._audioCtx.resume();
        }
        if (track.element) {
            ensureTrackGainNode(track);
        }
        _audioReady = true;
    };

    // Set volume directly — synchronous, no awaits (fires 60+ fps during drag)
    const _setVol = (vol) => {
        track.volume = vol;
        if (vol > 0) { track.muted = false; }
        label.textContent = `${Math.round(vol * 100)}%`;
        anchorBtn.title = `${track.label} - Vol ${Math.round(vol * 100)}%`;

        if (track.element) { track.element.muted = false; }

        if (track._gainNode && EditorState._audioCtx) {
            // Use linearRampToValueAtTime to avoid pops/clicks from instant jumps
            try {
                const gain = track._gainNode.gain;
                const now = EditorState._audioCtx.currentTime;
                gain.cancelScheduledValues(now);
                gain.setValueAtTime(gain.value, now);
                gain.linearRampToValueAtTime(vol, now + 0.03); // 30ms ramp — smooth, no pop
            } catch (_) {
                track._gainNode.gain.value = vol;
            }
            if (track.element) track.element.volume = 1.0;
        } else if (track.element) {
            track.element.volume = Math.min(1.0, vol);
        }
    };

    // While dragging, block playback loop from overriding the gain value
    slider.addEventListener('pointerdown', () => {
        _ensureAudio();
        track._volumeDragging = true;
    });
    slider.addEventListener('input', () => {
        const vol = parseInt(slider.value) / 100;
        _setVol(vol);
    });
    const _finishDrag = () => {
        track._volumeDragging = false;
        const vol = parseInt(slider.value) / 100;
        _setVol(vol);
        _saveVolume(track.type, vol);
        applyTrackVolumeLive(track, vol, { resumeContext: true });
        renderAllAudioTracks();
        const volAfter = track.volume;
        if (volBefore !== volAfter) {
            recordEdit(`Change ${track.label} volume`, track.id, 'volume', volBefore, volAfter);
        } else {
            saveProjectEdits();
        }
    };
    slider.addEventListener('change', _finishDrag);
    slider.addEventListener('pointerup', () => { track._volumeDragging = false; });
    slider.addEventListener('pointercancel', () => { track._volumeDragging = false; });

    // Wire ducking slider (music tracks only)
    const duckSlider = popup.querySelector('.ducking-slider');
    const duckLabelEl = popup.querySelector('.ducking-label');
    const duckNoteEl = popup.querySelector('.ducking-note');
    if (duckSlider) {
        const duckBefore = track.duckingLevel;
        duckSlider.addEventListener('input', () => {
            const duck = parseInt(duckSlider.value) / 100;
            track.duckingLevel = duck;
            if (duckLabelEl) duckLabelEl.textContent = `${duckSlider.value}%`;
            if (duckNoteEl) duckNoteEl.textContent = `Ducking to ${duckSlider.value}% when voice plays`;
        });
        duckSlider.addEventListener('change', () => {
            const duck = parseInt(duckSlider.value) / 100;
            track.duckingLevel = duck;
            saveProjectEdits();
            if (duckBefore !== duck) {
                recordEdit(`Change ${track.label} ducking`, track.id, 'duckingLevel', duckBefore, duck);
            }
        });
    }

    // Wire ducking toggle button
    const duckToggleBtn = popup.querySelector('.ducking-toggle-btn');
    if (duckToggleBtn) {
        duckToggleBtn.addEventListener('click', () => {
            track.duckingEnabled = !track.duckingEnabled;
            duckToggleBtn.style.color = track.duckingEnabled ? 'var(--text-secondary)' : 'var(--text-muted)';
            duckToggleBtn.style.opacity = track.duckingEnabled ? '1' : '0.3';
            if (duckSlider) duckSlider.disabled = !track.duckingEnabled;
            if (duckNoteEl) duckNoteEl.textContent = track.duckingEnabled
                ? `Ducking to ${Math.round(track.duckingLevel * 100)}% when voice plays`
                : 'Ducking disabled';
            applyTrackVolumeLive(track, track.volume, { resumeContext: true });
            saveProjectEdits();
        });
    }

    // Wire mute toggle
    popup.querySelector('.volume-mute-toggle').addEventListener('click', () => {
        const wasMuted = track.muted;
        track.muted = !track.muted;
        applyTrackVolumeLive(track, track.volume, { resumeContext: true });
        popup.remove();
        renderAllAudioTracks();
        recordEdit(`${track.muted ? 'Mute' : 'Unmute'} ${track.label}`, track.id, 'muted', wasMuted, track.muted);
    });

    // Close on click outside
    const closeHandler = (e) => {
        if (!popup.contains(e.target) && e.target !== anchorBtn && !anchorBtn.contains(e.target)) {
            popup.remove();
            document.removeEventListener('mousedown', closeHandler);
        }
    };
    setTimeout(() => document.addEventListener('mousedown', closeHandler), 0);
}

/**
 * Remove an audio track by ID (voice track is protected)
 */
function removeAudioTrack(trackId) {
    const track = getAudioTrackById(trackId);
    if (!track) return;
    if (track.type === 'voice') {
        showToast('Cannot remove voice track', 'warning');
        return;
    }
    // Save track data for undo (strip non-serializable element)
    const trackIndex = EditorState.audioTracks.indexOf(track);
    const { element, clips, ...trackData } = track;
    trackData._index = trackIndex;

    if (element) {
        element.pause();
        element.src = '';
    }
    // Clean up multi-clip elements
    if (clips) {
        for (const clip of clips) {
            if (clip.element) { clip.element.pause(); clip.element.src = ''; }
        }
    }
    EditorState.audioTracks = EditorState.audioTracks.filter(t => t.id !== trackId);
    recalculateDuration();
    renderAllAudioTracks();
    renderTimeRuler();

    recordEdit(`Remove ${track.label}`, trackId, 'removeTrack', trackData, null);
    showToast(`${track.label} removed`, 'info');
}

/**
 * Update project info in the UI
 */
function updateProjectInfo() {
    if (elements.projectName) {
        const name = EditorState.project.name || '';
        const styleName = EditorState.project.styleName;
        const styleColor = EditorState.project.styleColor;
        const esc = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
        if (styleName) {
            elements.projectName.innerHTML = `${esc(name)} <span style="display:inline-flex;align-items:center;gap:3px;margin-left:6px"><span style="width:6px;height:6px;border-radius:50%;background:${styleColor || 'var(--text-muted)'};display:inline-block"></span><span style="color:${styleColor || 'var(--text-muted)'};font-size:0.75em;font-weight:600">${esc(styleName)}</span></span>`;
        } else {
            elements.projectName.textContent = name;
        }
    }
    if (elements.infoScenes) {
        elements.infoScenes.textContent = EditorState.project.sceneCount;
    }

    const displayTotalDuration = getTotalDuration();

    if (elements.infoDuration) {
        elements.infoDuration.textContent = formatTimestamp(displayTotalDuration);
    }
    if (elements.totalTime) {
        elements.totalTime.textContent = formatTimecode(displayTotalDuration);
    }

}

// ---------------------------------------------------------------------------
// Project Share Dialog (Export ZIP / Import ZIP / Open Folder)
// ---------------------------------------------------------------------------

function openShareDialog() {
    // Tell Vue to render the modal (v-if="visible")
    if (window._vueShowShareDialog) {
        window._vueShowShareDialog();
    }

    // Vue renders async — wait one frame for the DOM to exist
    requestAnimationFrame(() => {
        const modal = document.getElementById('project-share-modal');
        if (!modal) return;

        // Bind inner-element listeners (fresh DOM from v-if)
        _bindShareDialogInner();

        // Populate project info
        const nameEl = document.getElementById('share-project-name');
        const metaEl = document.getElementById('share-project-meta');
        if (nameEl) nameEl.textContent = EditorState.project?.name || EditorState.project?.id || '';
        const isWip = EditorState.project?.loadedFrom === 'wip';
        const wipBadge = isWip ? ' <span style="opacity:0.3">/</span> <span style="color:#FFB347;font-weight:600">edited</span>' : '';
        if (metaEl) metaEl.innerHTML = `<span style="color:#4ECDC4">${EditorState.scenes.length} scenes</span> <span style="opacity:0.3">/</span> ${formatTimestamp(getTotalDuration())}${wipBadge}`;

        // Reset progress indicators
        _resetShareStatus('export');
        _resetShareStatus('import');
    });
}

function closeShareDialog() {
    document.getElementById('project-share-modal')?.classList.remove('active');
    if (window._vueHideShareDialog) {
        window._vueHideShareDialog();
    }
}

// --- Share dialog helpers ---
const _spinnerSvg16 = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="animation:spin 0.8s linear infinite"><circle cx="12" cy="12" r="10" stroke-dasharray="32" stroke-dashoffset="12"/></svg>';
const _checkSvg16 = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>';
const _errorSvg16 = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
const _exportIconSvg = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>';
const _importIconSvg = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#A78BFA" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>';
const _exportIconBg = 'rgba(78,205,196,0.1)';
const _importIconBg = 'rgba(167,139,250,0.1)';

function _shareSetIcon(prefix, svg, bg) {
    const el = document.getElementById(`share-${prefix}-icon`);
    if (el) {
        el.innerHTML = svg;
        if (bg) el.style.background = bg;
    }
}

function _shareSetLabel(prefix, label, desc, descColor) {
    const lbl = document.getElementById(`share-${prefix}-label`);
    const dsc = document.getElementById(`share-${prefix}-desc`);
    if (lbl) lbl.textContent = label;
    if (dsc) { dsc.textContent = desc; dsc.style.color = descColor || 'var(--text-muted)'; }
}

function _setShareBtnLoading(btn, loading) {
    if (!btn) return;
    if (loading) {
        btn.dataset.busy = '1';
        btn.style.opacity = '0.7';
        btn.style.pointerEvents = 'none';
    } else {
        delete btn.dataset.busy;
        btn.style.opacity = '';
        btn.style.pointerEvents = '';
    }
}

function _resetShareStatus(prefix) {
    const progress = document.getElementById(`share-${prefix}-progress`);
    const bar = document.getElementById(`share-${prefix}-bar`);
    const status = document.getElementById(`share-${prefix}-status`);
    if (progress) progress.style.display = 'none';
    if (bar) { bar.style.width = '0%'; bar.style.background = 'var(--accent)'; }
    if (status) { status.textContent = ''; status.style.color = ''; }
    // Reset icon and labels
    if (prefix === 'export') {
        _shareSetIcon('export', _exportIconSvg, _exportIconBg);
        _shareSetLabel('export', 'Export ZIP', 'Download project with all assets, audio & data');
    } else if (prefix === 'import') {
        _shareSetIcon('import', _importIconSvg, _importIconBg);
        _shareSetLabel('import', 'Import ZIP', 'Restore a project from a shared ZIP file');
    }
}

function _showShareProgress(prefix, pct, text) {
    const progress = document.getElementById(`share-${prefix}-progress`);
    const bar = document.getElementById(`share-${prefix}-bar`);
    const status = document.getElementById(`share-${prefix}-status`);
    if (progress) progress.style.display = '';
    if (bar) bar.style.width = pct + '%';
    if (status) status.textContent = text || '';
}

function _showShareDone(prefix, text) {
    const bar = document.getElementById(`share-${prefix}-bar`);
    const status = document.getElementById(`share-${prefix}-status`);
    if (bar) { bar.style.width = '100%'; bar.style.background = '#26DE81'; }
    if (status) { status.textContent = text || 'Done'; status.style.color = '#26DE81'; }
    _shareSetIcon(prefix, _checkSvg16, '#26DE81');
}

function _showShareError(prefix, text) {
    const bar = document.getElementById(`share-${prefix}-bar`);
    const status = document.getElementById(`share-${prefix}-status`);
    if (bar) { bar.style.width = '100%'; bar.style.background = '#FF6B6B'; }
    if (status) { status.textContent = text || 'Failed'; status.style.color = '#FF6B6B'; }
    _shareSetIcon(prefix, _errorSvg16, '#FF6B6B');
}

async function shareExportZip() {
    const pid = EditorState.project?.id;
    if (!pid) return;

    const btn = document.getElementById('share-export-zip');
    if (btn?.dataset.busy) return;
    _resetShareStatus('export');
    _setShareBtnLoading(btn, true);

    // Step 1: Compressing
    _shareSetIcon('export', _spinnerSvg16, 'rgba(78,205,196,0.15)');
    _shareSetLabel('export', 'Compressing...', 'Packaging all project files');
    _showShareProgress('export', 15, 'Compressing scenes, assets & audio...');

    try {
        const res = await fetch(`/api/editor/export-zip/${encodeURIComponent(pid)}`);
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.error || `Export failed (${res.status})`);
        }

        // Step 2: Downloading
        _shareSetLabel('export', 'Downloading...', 'Receiving compressed data');
        _showShareProgress('export', 50, 'Downloading ZIP...');
        const blob = await res.blob();
        const sizeMB = (blob.size / 1024 / 1024).toFixed(1);

        // Step 3: Saving
        _shareSetLabel('export', 'Saving...', `${sizeMB} MB ready`);
        _showShareProgress('export', 85, 'Saving to downloads folder...');
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${pid}.zip`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);

        // Done
        _shareSetLabel('export', 'Exported', `${pid}.zip · ${sizeMB} MB`, '#26DE81');
        _showShareDone('export', `${pid}.zip saved to downloads (${sizeMB} MB)`);
        showToast(`Project ZIP downloaded (${sizeMB} MB)`, 'success');
    } catch (e) {
        _shareSetLabel('export', 'Export Failed', e.message, '#FF6B6B');
        _showShareError('export', e.message);
        showToast('ZIP export failed: ' + e.message, 'error');
    } finally {
        _setShareBtnLoading(btn, false);
    }
}

function shareImportZip() {
    const fileInput = document.getElementById('share-import-file');
    if (!fileInput) return;
    fileInput.value = '';
    fileInput.click();
}

async function _handleImportZipFile(file) {
    if (!file) return;

    const btn = document.getElementById('share-import-zip');
    if (btn?.dataset.busy) return;
    _resetShareStatus('import');
    _setShareBtnLoading(btn, true);

    const fileSizeMB = (file.size / 1024 / 1024).toFixed(1);

    // Step 1: Validate locally
    _shareSetIcon('import', _spinnerSvg16, 'rgba(167,139,250,0.15)');
    _shareSetLabel('import', 'Validating...', file.name + ' (' + fileSizeMB + ' MB)');
    _showShareProgress('import', 10, 'Checking file format...');

    try {
        if (!file.name.toLowerCase().endsWith('.zip')) throw new Error('File must be a .zip archive');
        if (file.size < 100) throw new Error('File is too small to be a valid project ZIP');
        if (file.size > 2 * 1024 * 1024 * 1024) throw new Error('File exceeds 2 GB limit');

        // Step 2: Upload
        _shareSetLabel('import', 'Uploading...', fileSizeMB + ' MB');
        _showShareProgress('import', 25, 'Uploading ' + fileSizeMB + ' MB...');

        const form = new FormData();
        form.append('file', file);
        const res = await fetch('/api/editor/import-zip', { method: 'POST', body: form });

        // Step 3: Processing
        _shareSetLabel('import', 'Processing...', 'Extracting and validating files');
        _showShareProgress('import', 70, 'Extracting project structure...');
        const data = await res.json();

        if (!res.ok) throw new Error(data.error || 'Import failed');

        // Step 4: Done
        const pid = data.project_id;
        const renamed = data.renamed_from;
        const fileCount = data.imported_files || 0;

        let titleMsg, descMsg;
        if (renamed) {
            titleMsg = 'Imported (renamed)';
            descMsg = `"${renamed}" → "${pid}" (name existed) · ${fileCount} files`;
        } else {
            titleMsg = 'Imported';
            descMsg = `${pid} · ${fileCount} files`;
        }

        _shareSetLabel('import', titleMsg, descMsg, '#26DE81');
        _showShareDone('import', descMsg);

        if (renamed) {
            showToast(`Project renamed: "${renamed}" → "${pid}" (${fileCount} files)`, 'success');
        } else {
            showToast(`Project "${pid}" imported (${fileCount} files)`, 'success');
        }

        // Show load button
        const statusEl = document.getElementById('share-import-status');
        if (statusEl) {
            statusEl.innerHTML = statusEl.textContent +
                ` <a href="#" onclick="event.preventDefault(); loadProjectFromServer('${pid.replace(/'/g, "\\'")}'); closeShareDialog();" style="color:var(--accent);font-weight:600;text-decoration:underline;margin-left:6px">Load project →</a>`;
        }
    } catch (e) {
        _shareSetLabel('import', 'Import Failed', e.message, '#FF6B6B');
        _showShareError('import', e.message);
        showToast('ZIP import failed: ' + e.message, 'error');
    } finally {
        _setShareBtnLoading(btn, false);
    }
}

async function shareOpenFolder() {
    const pid = EditorState.project?.id;
    if (!pid) return;
    try {
        const res = await fetch(`/api/editor/open-folder/${encodeURIComponent(pid)}`, { method: 'POST' });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.error || 'Failed');
        }
    } catch (e) {
        showToast('Could not open folder: ' + e.message, 'error');
    }
}

function _bindShareDialogInner() {
    // Bind listeners on elements inside the Vue-rendered modal.
    // Called each time the dialog opens (elements are created fresh by v-if).
    document.getElementById('close-share-modal')?.addEventListener('click', closeShareDialog);
    document.getElementById('share-export-video')?.addEventListener('click', () => {
        closeShareDialog();
        exportMp4();
    });
    document.getElementById('share-export-zip')?.addEventListener('click', shareExportZip);
    document.getElementById('share-import-zip')?.addEventListener('click', shareImportZip);
    document.getElementById('share-open-folder')?.addEventListener('click', shareOpenFolder);
    document.getElementById('share-import-file')?.addEventListener('change', (e) => {
        _handleImportZipFile(e.target.files?.[0]);
    });

    // Close on backdrop click
    const modal = document.getElementById('project-share-modal');
    modal?.addEventListener('click', (e) => {
        if (e.target === modal) closeShareDialog();
    });
}

function setupShareDialog() {
    // The trigger button lives in the static shell HTML — always present
    document.getElementById('export-share-btn')?.addEventListener('click', openShareDialog);
}

function resetToInitialState() {
    const pid = EditorState.project?.id;
    if (!pid) { showToast('No project loaded', 'error'); return; }

    // Close history dropdown and show confirm dialog
    document.getElementById('history-dropdown')?.classList.remove('show');
    const modal = document.getElementById('reset-confirm-modal');
    if (!modal) return;
    modal.classList.add('active');

    const confirmBtn = document.getElementById('reset-confirm-btn');
    const cancelBtn = document.getElementById('reset-cancel-btn');

    const cleanup = () => {
        modal.classList.remove('active');
        confirmBtn.replaceWith(confirmBtn.cloneNode(true));
        cancelBtn.replaceWith(cancelBtn.cloneNode(true));
    };

    cancelBtn.addEventListener('click', cleanup, { once: true });
    modal.addEventListener('click', (e) => { if (e.target === modal) cleanup(); }, { once: true });

    confirmBtn.addEventListener('click', async () => {
        cleanup();
        showLoadingOverlay('Resetting to initial state...');

        try {
            // Stop playback and release audio before resetting
            cancelPendingProjectSave();
            if (EditorState.isPlaying) togglePlayback();
            for (const track of EditorState.audioTracks) {
                if (track.element) { track.element.pause(); track.element.src = ''; }
            }
            EditorState.audioTracks = [];
            EditorState.audio = null;
            EditorState.audioElement = null;
            EditorState.savedAudioSettings = null;
            EditorState.selectedAudioTrack = null;

            const res = await fetch(`/api/editor/reset/${encodeURIComponent(pid)}`, { method: 'POST' });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.error || `Reset failed (${res.status})`);
            }

            // Clear all localStorage edits and history for this project
            clearProjectEdits();
            clearEditorBootCaches();

            // Reload the project from initial state (force bypass "already loaded" guard)
            await loadProjectFromServer(pid, { force: true });
            showToast('Project reset to initial state', 'success');
        } catch (e) {
            hideLoadingOverlay();
            showToast('Reset failed: ' + e.message, 'error');
        }
    }, { once: true });
}

/**
 * Render the timeline with scene clips - uses helper for width calculation
 */
function renderTimeline() {
    if (!elements.videoTrack) return;

    const clips = EditorState.scenes.map((scene, idx) => {
        const width = getScenePixelWidth(scene);
        const color = SCENE_COLORS[scene.type] || '#666666';
        const icon = SCENE_ICONS[scene.type] || SCENE_ICONS.default;
        const selectedClass = EditorState.selectedScene?.id === scene.id &&
            EditorState.selectedTextOverlaySceneId !== scene.id ? ' selected' : '';
        const leftHandle = `<div class="resize-handle resize-handle-left"><svg class="resize-arrows" viewBox="0 0 8 14"><path d="M5 1L1 7l4 6M3 1l4 6-4 6"/></svg></div>`;
        const rightHandle = `<div class="resize-handle resize-handle-right"><svg class="resize-arrows" viewBox="0 0 8 14"><path d="M3 1l4 6-4 6M5 1L1 7l4 6"/></svg></div>`;

        return `
            <div class="scene-clip${selectedClass}"
                 data-id="${scene.id}"
                 data-type="${scene.type}"
                 style="width: ${width}px; --scene-color: ${color};"
                 title="${scene.type} - ${scene.duration}s">
                ${getSceneClipThumbMarkup(scene, icon)}
                <div class="scene-clip-info">
                    <div class="scene-clip-id">${scene.id}</div>
                    <div class="scene-clip-duration">${scene.duration}s</div>
                </div>
                ${leftHandle}${rightHandle}
            </div>
        `;
    }).join('');

    elements.videoTrack.innerHTML = clips;

    // Render text track — text clips positioned at matching scene times
    renderTextTrack();

    // Render caption track
    renderCaptionTrack();

    // Add click listeners
    elements.videoTrack.querySelectorAll('.scene-clip').forEach(clip => {
        clip.addEventListener('click', (e) => {
            if (e.target.closest('.resize-handle')) return;
            selectScene(parseInt(clip.dataset.id));
        });

        // Double-click to jump playhead and start playback
        clip.addEventListener('dblclick', (e) => {
            e.stopPropagation();
            const sceneId = parseInt(clip.dataset.id);
            const sceneIndex = EditorState.scenes.findIndex(s => s.id === sceneId);
            if (sceneIndex < 0) return;
            const startTime = getSceneStartTime(sceneIndex);
            EditorState.playbackPosition = startTime;
            if (EditorState.preview) {
                EditorState.preview.seek(startTime);
                EditorState.preview.play();
            }
            EditorState.audioTracks.forEach(t => {
                if (t.element) t.element.currentTime = getTrackPlaybackTime(t, startTime);
            });
            updatePlayhead();
            updateTimeScrubber();
        });
    });

    // Add resize listeners
    setupResizeHandlers();

    // Validate and show errors
    validateScenes();
    applySceneErrorStyles();
}

/**
 * Render text track — shows text_content for scenes that have it, aligned to scene times
 */
function renderTextTrack() {
    if (!elements.textTrack) return;

    // Build text clips for scenes that have text_content
    const totalWidth = timeToPixels(getScenesDuration());
    const textClips = [];

    EditorState.scenes.forEach((scene, sceneIndex) => {
        const text = getSceneTextValue(scene);
        if (!hasSceneTextOverlay(scene)) return;
        normalizeSceneTextOverlay(scene);

        const left = timeToPixels(getSceneTextTimelineStart(sceneIndex));
        const width = timeToPixels(getSceneTextDuration(scene));
        const isTextScene = scene.type === 'text' || scene.type === 'cta';
        const isSelected = EditorState.selectedTextOverlaySceneId === scene.id ||
            (isTextScene && EditorState.selectedScene?.id === scene.id);
        const selectedClass = isSelected ? ' selected' : '';

        const truncText = text.length > 30 ? text.substring(0, 30) + '...' : text;
        textClips.push(`
            <div class="text-clip${selectedClass}"
                 data-id="${scene.id}"
                 style="position:absolute;left:${left}px;width:${width}px;"
                 title="${text.replace(/"/g, '&quot;')}">
                <div class="resize-handle resize-handle-left"><svg class="resize-arrows" viewBox="0 0 8 14"><path d="M5 1L1 7l4 6M3 1l4 6-4 6"/></svg></div>
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="flex-shrink:0;opacity:0.6">
                    <path d="M4 7V4h16v3"/><path d="M12 4v16"/><path d="M8 20h8"/>
                </svg>
                <span class="text-clip-label">${truncText.replace(/</g, '&lt;')}</span>
                <span class="text-clip-duration">${getSceneTextDuration(scene)}s</span>
                <div class="resize-handle resize-handle-right"><svg class="resize-arrows" viewBox="0 0 8 14"><path d="M3 1l4 6-4 6M5 1L1 7l4 6"/></svg></div>
            </div>
        `);
    });

    if (textClips.length > 0) {
        elements.textTrack.innerHTML = `<div style="position:relative;width:${totalWidth}px;height:100%">${textClips.join('')}</div>`;

        // Click to select scene
        elements.textTrack.querySelectorAll('.text-clip').forEach(clip => {
            clip.addEventListener('click', (e) => {
                if (e.target.closest('.resize-handle')) return;
                if (clip.dataset.suppressClick === '1') {
                    delete clip.dataset.suppressClick;
                    return;
                }
                const sceneId = parseInt(clip.dataset.id);
                const scene = EditorState.scenes.find(s => s.id === sceneId);
                if (!scene) return;
                if (scene.type === 'text' || scene.type === 'cta') {
                    selectScene(sceneId);
                } else {
                    selectTextOverlay(sceneId);
                }
            });
        });
        setupTextOverlayHandlers();
    } else {
        elements.textTrack.innerHTML = `<div class="text-track-empty">No text overlays</div>`;
    }
}

/**
 * Render caption track — shows caption text clips from caption data
 */
function renderCaptionTrack() {
    if (!elements.captionTrack) return;

    const captionData = EditorState.captionData;
    if (!captionData || !captionData.captions || !captionData.captions.length) {
        EditorState.selectedCaptionIdx = null;
        elements.captionTrack.innerHTML = `<div class="caption-track-empty">No captions</div>`;
        return;
    }

    const captions = captionData.captions;
    const totalDuration = EditorState.scenes.reduce((sum, s) => sum + (s.duration || 0), 0);
    if (!totalDuration) return;

    // Total timeline width from scenes
    let totalWidth = 0;
    for (const scene of EditorState.scenes) {
        totalWidth += getScenePixelWidth(scene);
    }

    const pxPerSec = totalWidth / totalDuration;
    if (EditorState.selectedCaptionIdx != null && (EditorState.selectedCaptionIdx < 0 || EditorState.selectedCaptionIdx >= captions.length)) {
        EditorState.selectedCaptionIdx = null;
    }

    const clips = captions.map((c, i) => {
        const left = c.start * pxPerSec;
        const width = Math.max((c.end - c.start) * pxPerSec, 8);
        const label = c.text.length > 20 ? c.text.substring(0, 20) + '...' : c.text;
        const selectedClass = EditorState.selectedCaptionIdx === i ? ' selected' : '';
        return `<div class="caption-clip${selectedClass}" data-cap-idx="${i}" style="left:${left}px;width:${width}px" title="${c.text.replace(/"/g, '&quot;')}">
            <span class="caption-clip-label">${label.replace(/</g, '&lt;')}</span>
        </div>`;
    }).join('');

    elements.captionTrack.innerHTML = `<div style="position:relative;width:${totalWidth}px;height:100%">${clips}</div>`;

    // Bind click delegation once
    if (!elements.captionTrack._capClickBound) {
        elements.captionTrack._capClickBound = true;
        elements.captionTrack.addEventListener('click', (e) => {
            const clip = e.target.closest('.caption-clip');
            if (!clip) return;
            const idx = parseInt(clip.dataset.capIdx, 10);
            if (!isNaN(idx)) selectCaption(idx);
        });
    }
}

/**
 * Select a caption clip and show its details in the properties panel
 */
function selectCaption(idx) {
    const captionData = EditorState.captionData;
    if (!captionData || !captionData.captions || idx < 0 || idx >= captionData.captions.length) return;

    // Deselect scenes and audio
    EditorState.selectedScene = null;
    EditorState.selectedTextOverlaySceneId = null;
    EditorState.selectedAudioTrack = null;
    EditorState.selectedOverlayIdx = null;
    document.querySelectorAll('.scene-clip.selected').forEach(el => el.classList.remove('selected'));
    document.querySelectorAll('.text-clip.selected').forEach(el => el.classList.remove('selected'));
    document.querySelectorAll('.audio-clip-universal.selected').forEach(el => el.classList.remove('selected'));

    // Deselect previous caption clip
    document.querySelectorAll('.caption-clip.selected').forEach(el => el.classList.remove('selected'));

    EditorState.selectedCaptionIdx = idx;

    // Highlight selected
    const clip = elements.captionTrack.querySelector(`.caption-clip[data-cap-idx="${idx}"]`);
    if (clip) clip.classList.add('selected');

    // Seek playback to caption start
    const cap = captionData.captions[idx];
    EditorState.playbackPosition = cap.start;
    if (EditorState.preview) EditorState.preview.seek(cap.start);
    seekAudio(cap.start);
    updateTimeScrubber();
    updatePlayhead();

    renderSceneProperties();
    renderTextToolState();
}

/**
 * Render caption properties in the detail panel
 */
function renderCaptionProperties() {
    if (!elements.sceneProperties) return;

    const idx = EditorState.selectedCaptionIdx;
    const captionData = EditorState.captionData;
    if (idx == null || !captionData || !captionData.captions || idx >= captionData.captions.length) {
        return;
    }

    const cap = captionData.captions[idx];
    const duration = (cap.end - cap.start).toFixed(2);
    const totalCaptions = captionData.captions.length;

    const fmtTime = (s) => {
        const m = Math.floor(s / 60);
        const sec = (s % 60).toFixed(2).padStart(5, '0');
        return `${m}:${sec}`;
    };

    elements.sceneProperties.innerHTML = `
        <div class="caption-props-header">
            <span class="caption-props-icon">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="4" width="20" height="16" rx="2"/><line x1="6" y1="12" x2="18" y2="12"/><line x1="6" y1="16" x2="14" y2="16"/></svg>
            </span>
            <span class="caption-props-title">Caption ${idx + 1} / ${totalCaptions}</span>
        </div>
        <div class="property-group">
            <label>Start</label>
            <span class="property-value">${fmtTime(cap.start)}</span>
        </div>
        <div class="property-group">
            <label>End</label>
            <span class="property-value">${fmtTime(cap.end)}</span>
        </div>
        <div class="property-group">
            <label>Duration</label>
            <span class="property-value">${duration}s</span>
        </div>
        <div class="property-group property-stack">
            <label>Text</label>
            <textarea class="property-textarea" id="caption-text-edit"
                      rows="4" spellcheck="false">${cap.text.replace(/</g, '&lt;')}</textarea>
        </div>
        ${cap.words && cap.words.length ? `
        <div class="property-group property-stack">
            <div class="caption-words-header">
                <label>Words</label>
                <span>${cap.words.length} words</span>
            </div>
            <div class="caption-words-list">
                ${cap.words.map((w, wi) => `
                <div class="caption-word-row" data-word-idx="${wi}">
                    <input class="caption-word-input" value="${(w.word || '').replace(/"/g, '&quot;')}" data-word-idx="${wi}" />
                    <span class="caption-word-time">${fmtTime(w.begin)}</span>
                    <span class="caption-word-time">${fmtTime(w.end)}</span>
                </div>`).join('')}
            </div>
        </div>` : ''}
    `;

    // Bind text editing
    const textarea = document.getElementById('caption-text-edit');
    if (textarea) {
        textarea.addEventListener('input', () => {
            const newText = textarea.value;
            captionData.captions[idx].text = newText;
            _saveCaptionsToStorage();

            // Update the clip label on the timeline
            const clipEl = elements.captionTrack.querySelector(`.caption-clip[data-cap-idx="${idx}"]`);
            if (clipEl) {
                const label = newText.length > 20 ? newText.substring(0, 20) + '...' : newText;
                const labelEl = clipEl.querySelector('.caption-clip-label');
                if (labelEl) labelEl.textContent = label;
                clipEl.title = newText;
            }
        });
    }

    // Bind word-level editing
    if (cap.words && cap.words.length) {
        elements.sceneProperties.querySelectorAll('.caption-word-input').forEach(input => {
            input.addEventListener('input', () => {
                const wi = parseInt(input.dataset.wordIdx, 10);
                if (isNaN(wi) || !cap.words[wi]) return;
                cap.words[wi].word = input.value;
                // Rebuild full text from words
                cap.text = cap.words.map(w => w.word).join(' ');
                captionData.captions[idx].text = cap.text;
                if (textarea) textarea.value = cap.text;
                _saveCaptionsToStorage();
                // Update timeline clip label
                const clipEl = elements.captionTrack.querySelector(`.caption-clip[data-cap-idx="${idx}"]`);
                if (clipEl) {
                    const label = cap.text.length > 20 ? cap.text.substring(0, 20) + '...' : cap.text;
                    const labelEl = clipEl.querySelector('.caption-clip-label');
                    if (labelEl) labelEl.textContent = label;
                    clipEl.title = cap.text;
                }
            });
        });

        // Click word row → seek to that word's begin time
        elements.sceneProperties.querySelectorAll('.caption-word-row').forEach(row => {
            row.addEventListener('click', (e) => {
                if (e.target.classList.contains('caption-word-input')) return; // don't seek when clicking input
                const wi = parseInt(row.dataset.wordIdx, 10);
                if (isNaN(wi) || !cap.words[wi]) return;
                const t = cap.words[wi].begin;
                EditorState.playbackPosition = t;
                if (EditorState.preview) EditorState.preview.seek(t);
                seekAudio(t);
                updateTimeScrubber();
                updatePlayhead();
            });
        });
    }
}

/**
 * Close timing gaps in the timeline — trims excess silence from scenes
 * and shifts caption times to eliminate visual gaps.
 */
function closeTimelineGaps() {
    const scenes = EditorState.scenes;
    if (!scenes || scenes.length < 2) return;

    const BUFFER = 0.15;   // keep small gap between segments
    const MIN_GAP = 0.3;   // only close gaps larger than this

    // 1. Collect gap info from scenes (based on original timing)
    const gaps = [];
    for (const scene of scenes) {
        if (scene.segment_start != null && scene.segment_end != null) {
            const speechDur = scene.segment_end - scene.segment_start;
            const excess = scene.duration - speechDur;
            if (excess > MIN_GAP) {
                gaps.push({
                    afterTime: scene.segment_end,       // original time where gap starts
                    trimAmount: excess - BUFFER           // how much to remove
                });
            }
        }
    }

    if (gaps.length === 0) return;
    gaps.sort((a, b) => a.afterTime - b.afterTime);

    // Helper: cumulative shift for a given original time
    function getShift(t) {
        let s = 0;
        for (const g of gaps) {
            if (g.afterTime < t) s += g.trimAmount;
        }
        return s;
    }

    // 2. Trim scene durations & shift segment times
    for (const scene of scenes) {
        if (scene.segment_start == null) continue;
        const speechDur = scene.segment_end - scene.segment_start;
        const excess = scene.duration - speechDur;

        // Trim this scene's silence
        if (excess > MIN_GAP) {
            scene.duration = parseFloat((speechDur + BUFFER).toFixed(3));
        }

        // Shift segment times for scenes after earlier gaps
        const shift = getShift(scene.segment_start);
        if (shift > 0) {
            scene.segment_start = parseFloat((scene.segment_start - shift).toFixed(3));
            scene.segment_end = parseFloat((scene.segment_end - shift).toFixed(3));
        }
    }

    // 3. Shift caption times
    const captions = EditorState.captionData?.captions;
    if (captions) {
        for (const cap of captions) {
            const shift = getShift(cap.start);
            if (shift > 0) {
                cap.start = parseFloat(Math.max(0, cap.start - shift).toFixed(3));
                cap.end = parseFloat(Math.max(0, cap.end - shift).toFixed(3));
            }
        }
    }

    // 4. Re-render everything
    renderTimeline();
    renderTimeRuler();
    renderCaptionTrack();
    saveProjectEdits();
    _saveCaptionsToStorage();
    _debouncedServerSave();
}

/**
 * Timing Adjust — shift scene cuts earlier/later by N seconds.
 *
 * Simple: take N seconds from prev scene, give to curr scene.
 * No segment timing needed — just durations.
 * Prev scene keeps at least 0.3s so it doesn't vanish.
 *
 * Toggle: click to apply, click again to restore.
 */
function flipFillers() {
    const scenes = EditorState.scenes;
    if (!scenes || scenes.length < 2) {
        showToast('Need at least 2 scenes', 'info');
        return;
    }

    const MIN_PREV_DUR = 0.3; // never shrink prev below this

    // Snapshot durations + filler_shift before modification
    const oldState = scenes.map(s => ({ duration: s.duration, filler_shift: s.filler_shift || 0 }));

    // If already applied → undo
    const isApplied = scenes.some(s => s.filler_shift && s.filler_shift !== 0);

    if (isApplied) {
        let restored = 0;
        for (let i = 0; i < scenes.length; i++) {
            const shift = scenes[i].filler_shift || 0;
            if (shift === 0) continue;
            const prev = scenes[i - 1];
            if (prev) prev.duration = parseFloat((prev.duration - shift).toFixed(3));
            scenes[i].duration = parseFloat((scenes[i].duration + shift).toFixed(3));
            scenes[i].filler_shift = 0;
            restored++;
        }
        elements.flipFillerBtn?.classList.remove('active');
        showToast(`Restored ${restored} scene(s)`, 'info');
    } else {
        const shiftSec = parseFloat(document.getElementById('flip-filler-amount')?.value || '0');
        if (shiftSec === 0) { showToast('Select a shift amount first', 'info'); return; }
        const randomDir = document.getElementById('flip-filler-random')?.checked || false;

        let earlierCount = 0, laterCount = 0;
        for (let i = 1; i < scenes.length; i++) {
            const prev = scenes[i - 1];
            const curr = scenes[i];

            const goEarlier = randomDir ? Math.random() < 0.5 : true;
            const wanted = randomDir ? shiftSec * (0.4 + Math.random() * 0.6) : shiftSec;

            if (goEarlier) {
                // Earlier: prev shrinks, curr grows
                const maxTake = Math.max(0, prev.duration - MIN_PREV_DUR);
                const shift = parseFloat(Math.min(wanted, maxTake).toFixed(3));
                if (shift < 0.02) continue;
                prev.duration = parseFloat((prev.duration - shift).toFixed(3));
                curr.duration = parseFloat((curr.duration + shift).toFixed(3));
                curr.filler_shift = -shift;
                earlierCount++;
            } else {
                // Later: prev grows, curr shrinks
                const maxTake = Math.max(0, curr.duration - MIN_PREV_DUR);
                const shift = parseFloat(Math.min(wanted, maxTake).toFixed(3));
                if (shift < 0.02) continue;
                prev.duration = parseFloat((prev.duration + shift).toFixed(3));
                curr.duration = parseFloat((curr.duration - shift).toFixed(3));
                curr.filler_shift = shift;
                laterCount++;
            }
        }

        elements.flipFillerBtn?.classList.add('active');
        const total = earlierCount + laterCount;
        const detail = randomDir
            ? `${earlierCount} earlier, ${laterCount} later`
            : `${total} earlier`;
        showToast(`Adjusted ${total} scene(s) (${detail})`, 'success');
    }

    // Record the bulk edit for undo/redo
    const newState = scenes.map(s => ({ duration: s.duration, filler_shift: s.filler_shift || 0 }));
    recordEdit(isApplied ? 'Restore filler timing' : 'Flip filler timing', 'bulk', 'flipFillers', oldState, newState);

    renderTimeline();
    renderTimeRuler();
    renderCaptionTrack();
    renderSceneProperties();
}

/**
 * Setup caption enable toggle and style controls in the sidebar Caption tab.
 */
function setupCaptionControls() {
    const toggle = document.getElementById('caption-enabled-toggle');
    if (!toggle) return;

    // Sync toggle label text
    const capToggleLabel = toggle.parentElement?.querySelector('.cap-card-toggle-label');
    const updateCapToggleLabel = () => { if (capToggleLabel) capToggleLabel.textContent = toggle.checked ? 'On' : 'Off'; };
    updateCapToggleLabel();

    toggle.addEventListener('change', () => {
        const wasEnabled = EditorState.captionsEnabled;
        EditorState.captionsEnabled = toggle.checked;
        updateCapToggleLabel();
        const row = elements.captionTrackRow;
        if (row) row.style.display = toggle.checked ? '' : 'none';
        if (!toggle.checked) {
            EditorState.selectedCaptionIdx = null;
            document.querySelectorAll('.caption-clip.selected').forEach(el => el.classList.remove('selected'));
            renderSceneProperties();
        }

        // Show/hide caption overlay in preview
        if (EditorState.preview) {
            if (toggle.checked && EditorState.captionData) {
                EditorState.preview.setCaptions(EditorState.captionData.captions, EditorState.captionData.style || {});
            } else {
                EditorState.preview.setCaptions(null, null);
            }
        }

        // Update UI
        _capUpdateUI();
        renderCaptionTrack();
        _saveCaptionsToStorage();
        _debouncedServerSave();
        recordEdit(toggle.checked ? 'Enable captions' : 'Disable captions', 'captions', 'captionsEnabled', wasEnabled, toggle.checked);
    });

    // Style controls
    const presetSel = document.getElementById('cap-ed-preset');
    const fontSel = document.getElementById('cap-ed-font');
    if (fontSel) buildFontOptions(fontSel, EditorState.captionData?.style?.font_family || 'Montserrat');
    const sizeInput = document.getElementById('cap-ed-size');
    const colorInput = document.getElementById('cap-ed-color');
    const strokeInput = document.getElementById('cap-ed-stroke');
    const posInput = document.getElementById('cap-ed-position');
    const posVal = document.getElementById('cap-ed-pos-val');

    const updateStyle = (key, value) => {
        if (!EditorState.captionData?.style) return;
        const oldVal = EditorState.captionData.style[key];
        EditorState.captionData.style[key] = value;
        if (EditorState.preview && EditorState.captionsEnabled) {
            EditorState.preview.setCaptions(EditorState.captionData.captions, EditorState.captionData.style);
        }
        _saveCaptionsToStorage();
        _debouncedServerSave();
        if (oldVal !== value) {
            recordEdit(`Change caption ${key}`, 'captions', `style.${key}`, oldVal, value);
        }
    };

    loadCaptionPresetOptions(presetSel, EditorState.captionData?.style?.preset || 'bold_popup');

    presetSel?.addEventListener('change', () => {
        const p = captionPresetMap[presetSel.value];
        if (p && EditorState.captionData) {
            const oldStyle = { ...EditorState.captionData.style };
            EditorState.captionData.style = { ...p, preset: presetSel.value };
            _capSyncStyleUI();
            if (EditorState.preview && EditorState.captionsEnabled) {
                EditorState.preview.setCaptions(EditorState.captionData.captions, EditorState.captionData.style);
            }
            _saveCaptionsToStorage();
            // Immediate save — preset change is a significant action
            saveProjectToServer();
            recordEdit(`Change caption preset to ${presetSel.value}`, 'captions', 'style', oldStyle, { ...EditorState.captionData.style });
        }
    });

    fontSel?.addEventListener('change', () => updateStyle('font_family', fontSel.value));
    sizeInput?.addEventListener('change', () => updateStyle('font_size', parseInt(sizeInput.value)));
    colorInput?.addEventListener('input', () => updateStyle('color', colorInput.value));
    strokeInput?.addEventListener('input', () => updateStyle('stroke_color', strokeInput.value));

    // Stroke width (px)
    const strokeWidthInput = document.getElementById('cap-ed-stroke-width');
    strokeWidthInput?.addEventListener('change', () => updateStyle('stroke_width', parseInt(strokeWidthInput.value) || 0));

    posInput?.addEventListener('input', () => {
        if (posVal) posVal.textContent = posInput.value + '%';
        updateStyle('position_y', parseInt(posInput.value));
    });

    // Letter spacing slider (-5 to 20 px, step 1)
    const lsInput = document.getElementById('cap-ed-letter-spacing');
    const lsVal = document.getElementById('cap-ed-ls-val');
    lsInput?.addEventListener('input', () => {
        const px = parseInt(lsInput.value);
        if (lsVal) lsVal.textContent = px + 'px';
        updateStyle('letter_spacing', px);
    });

    // Shadow controls
    const shadowColorInput = document.getElementById('cap-ed-shadow-color');
    const shadowBlurInput = document.getElementById('cap-ed-shadow-blur');
    const shadowXInput = document.getElementById('cap-ed-shadow-x');
    const shadowYInput = document.getElementById('cap-ed-shadow-y');
    shadowColorInput?.addEventListener('input', () => updateStyle('shadow_color', shadowColorInput.value));
    shadowBlurInput?.addEventListener('change', () => updateStyle('shadow_blur', parseInt(shadowBlurInput.value) || 0));
    shadowXInput?.addEventListener('change', () => updateStyle('shadow_offset_x', parseInt(shadowXInput.value) || 0));
    shadowYInput?.addEventListener('change', () => updateStyle('shadow_offset_y', parseInt(shadowYInput.value) || 0));

    // Highlight color
    const highlightColorInput = document.getElementById('cap-ed-highlight-color');
    highlightColorInput?.addEventListener('input', () => updateStyle('highlight_color', highlightColorInput.value));

    // Clean special characters checkbox
    const cleanToggle = document.getElementById('cap-clean-text-toggle');
    cleanToggle?.addEventListener('change', () => {
        if (cleanToggle.checked) {
            capCleanAllSpecialChars();
        }
    });
}

/**
 * Sync style controls UI from caption data
 */
function _capSyncStyleUI() {
    const style = EditorState.captionData?.style;
    if (!style) return;
    const s = (id, val) => { const el = document.getElementById(id); if (el) el.value = val; };
    s('cap-ed-preset', style.preset || 'bold_popup');

    // Rebuild font dropdown with correct selection (ensures preset fonts appear even if not in registry)
    const fontSel = document.getElementById('cap-ed-font');
    if (fontSel) buildFontOptions(fontSel, style.font_family || 'Montserrat');
    s('cap-ed-size', style.font_size || 64);
    s('cap-ed-color', style.color || '#FFFFFF');
    s('cap-ed-stroke', style.stroke_color || '#000000');
    s('cap-ed-stroke-width', style.stroke_width ?? 4);
    s('cap-ed-position', style.position_y || 80);
    const posVal = document.getElementById('cap-ed-pos-val');
    if (posVal) posVal.textContent = (style.position_y || 80) + '%';

    const ls = style.letter_spacing || 0;
    s('cap-ed-letter-spacing', ls);
    const lsVal = document.getElementById('cap-ed-ls-val');
    if (lsVal) lsVal.textContent = ls + 'px';

    // Shadow
    // Convert rgba/named shadow_color to hex for color input
    const sc = style.shadow_color || '#000000';
    if (sc.startsWith('#')) {
        s('cap-ed-shadow-color', sc);
    } else {
        // rgba(...) → parse to hex
        const m = sc.match(/(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
        if (m) s('cap-ed-shadow-color', '#' + [m[1],m[2],m[3]].map(v => parseInt(v).toString(16).padStart(2,'0')).join(''));
    }
    s('cap-ed-shadow-blur', style.shadow_blur || 0);
    s('cap-ed-shadow-x', style.shadow_offset_x || 0);
    s('cap-ed-shadow-y', style.shadow_offset_y || 0);

    // Highlight
    const hlSection = document.getElementById('cap-highlight-section');
    if (hlSection) hlSection.style.display = style.highlight ? '' : 'none';
    s('cap-ed-highlight-color', style.highlight_color || '#4ECDC4');
}

/**
 * Strip all punctuation/symbols from caption text, keeping only
 * letters, numbers, spaces, !, ?, [ and ]
 */
function _cleanCaptionSpecialChars(text) {
    return text
        .replace(/[^\p{L}\p{N}\s!?\[\]]/gu, '')
        .replace(/\s{2,}/g, ' ')
        .trim();
}

/**
 * Clean special characters from all captions and refresh UI + preview
 */
function capCleanAllSpecialChars() {
    if (!EditorState.captionData?.captions?.length) return;
    let changed = 0;
    for (const cap of EditorState.captionData.captions) {
        const cleaned = _cleanCaptionSpecialChars(cap.text);
        if (cleaned !== cap.text) {
            cap.text = cleaned;
            changed++;
        }
    }
    if (changed > 0) {
        if (EditorState.preview && EditorState.captionsEnabled) {
            EditorState.preview.setCaptions(EditorState.captionData.captions, EditorState.captionData.style);
        }
        renderCaptionTrack();
        showToast(`Cleaned ${changed} caption${changed > 1 ? 's' : ''}`, 'success');
    } else {
        showToast('No special characters found', 'info');
    }
}

/**
 * Update caption tab UI based on whether data is loaded
 */
function _capUpdateUI() {
    const hasData = !!(EditorState.captionData && EditorState.captionData.captions && EditorState.captionData.captions.length);
    const noDataEl = document.getElementById('caption-no-data');
    const infoEl = document.getElementById('caption-info');
    const styleEl = document.getElementById('caption-style-controls');

    if (noDataEl) noDataEl.style.display = hasData ? 'none' : '';
    if (infoEl) infoEl.style.display = hasData ? '' : 'none';
    if (styleEl) styleEl.style.display = hasData ? 'flex' : 'none';

    if (hasData) {
        const countEl = document.getElementById('caption-info-count');
        if (countEl) countEl.textContent = EditorState.captionData.captions.length + ' captions';
    }
}

/**
 * Save current caption data (style + captions) to localStorage
 */
function _saveCaptionsToStorage() {
    if (!EditorState.captionData) return;
    try {
        // Stamp project identifiers so we can detect cross-project stale captions
        const data = { ...EditorState.captionData };
        if (EditorState.project?.id) data._editor_project = EditorState.project.id;
        if (EditorState.project?.sourceFolder) data.source_folder = EditorState.project.sourceFolder;
        localStorage.setItem('sts-editor-captions', JSON.stringify(data));
    } catch { /* ignore */ }
}

/**
 * Load captions from localStorage (sent by studio)
 * Validates that captions belong to the current project to prevent cross-project bleed.
 */
function _loadCaptionsFromStorage() {
    try {
        const stored = localStorage.getItem('sts-editor-captions');
        if (stored) {
            const data = JSON.parse(stored);
            const currentSF = EditorState.project?.sourceFolder;
            const currentPID = EditorState.project?.id;

            // Fail closed: if the current project has a source_folder, captions must carry the same source_folder.
            if (currentSF && (!data.source_folder || data.source_folder !== currentSF)) {
                console.log('Skipping stale captions (missing/mismatch source_folder):', data.source_folder, '!=', currentSF);
                localStorage.removeItem('sts-editor-captions');
                return;
            }
            // Skip if _editor_project doesn't match
            if (data._editor_project && currentPID && data._editor_project !== currentPID) {
                console.log('Skipping stale captions (project mismatch):', data._editor_project, '!=', currentPID);
                localStorage.removeItem('sts-editor-captions');
                return;
            }
            _receiveCaptionData(data);
        }
    } catch { /* ignore */ }
}

/**
 * Receive caption data (from postMessage or localStorage) and update editor state
 */
function _receiveCaptionData(captionData) {
    if (!captionData || !captionData.captions || !captionData.captions.length) return;
    EditorState.captionData = captionData;

    // Auto-clean special characters if toggle is checked
    const cleanToggle = document.getElementById('cap-clean-text-toggle');
    if (cleanToggle?.checked) {
        for (const cap of captionData.captions) {
            cap.text = _cleanCaptionSpecialChars(cap.text);
        }
    }

    // Auto-enable captions when data arrives
    EditorState.captionsEnabled = true;
    const toggle = document.getElementById('caption-enabled-toggle');
    if (toggle) {
        toggle.checked = true;
        const lbl = toggle.parentElement?.querySelector('.cap-card-toggle-label');
        if (lbl) lbl.textContent = 'On';
    }
    if (elements.captionTrackRow) elements.captionTrackRow.style.display = '';

    // Update preview
    if (EditorState.preview) {
        EditorState.preview.setCaptions(captionData.captions, captionData.style || {});
    }

    normalizeTimelineDurations();
    recalculateDuration();

    _capSyncStyleUI();
    _capUpdateUI();
    renderCaptionTrack();
    _saveCaptionsToStorage();
    saveProjectEdits();
}

/**
 * Setup resize handlers for scene clips
 */
function setupResizeHandlers() {
    const attachResizeHandlers = (clip) => {
        const leftHandle = clip.querySelector('.resize-handle-left');
        const rightHandle = clip.querySelector('.resize-handle-right');
        const sceneId = parseInt(clip.dataset.id);

        if (rightHandle && rightHandle.dataset.resizeBound !== '1') {
            rightHandle.dataset.resizeBound = '1';
            rightHandle.addEventListener('mousedown', (e) => {
                e.stopPropagation();
                startResize(sceneId, 'right', e);
            });
        }

        if (leftHandle && leftHandle.dataset.resizeBound !== '1') {
            leftHandle.dataset.resizeBound = '1';
            leftHandle.addEventListener('mousedown', (e) => {
                e.stopPropagation();
                startResize(sceneId, 'left', e);
            });
        }
    };

    elements.videoTrack.querySelectorAll('.scene-clip').forEach(attachResizeHandlers);
}

function updateSceneAndTextClipLayout() {
    for (let sceneIndex = 0; sceneIndex < EditorState.scenes.length; sceneIndex++) {
        const scene = EditorState.scenes[sceneIndex];
        const widthPx = getScenePixelWidth(scene);
        const sceneClip = elements.videoTrack?.querySelector(`.scene-clip[data-id="${scene.id}"]`);
        if (sceneClip) {
            sceneClip.style.width = `${widthPx}px`;
            sceneClip.title = `${scene.type} - ${scene.duration}s`;
            const durationEl = sceneClip.querySelector('.scene-clip-duration');
            if (durationEl) durationEl.textContent = `${scene.duration}s`;
        }

        const textClip = elements.textTrack?.querySelector(`.text-clip[data-id="${scene.id}"]`);
        if (textClip) {
            textClip.style.left = `${timeToPixels(getSceneTextTimelineStart(sceneIndex))}px`;
            textClip.style.width = `${timeToPixels(getSceneTextDuration(scene))}px`;
            const durationEl = textClip.querySelector('.text-clip-duration');
            if (durationEl) durationEl.textContent = `${getSceneTextDuration(scene)}s`;
        }
    }

    const textTrackInner = elements.textTrack?.firstElementChild;
    if (textTrackInner && textTrackInner.style.position === 'relative') {
        textTrackInner.style.width = `${timeToPixels(getScenesDuration())}px`;
    }
}

function setupTextOverlayHandlers() {
    elements.textTrack?.querySelectorAll('.text-clip').forEach(clip => {
        const leftHandle = clip.querySelector('.resize-handle-left');
        const rightHandle = clip.querySelector('.resize-handle-right');
        const sceneId = parseInt(clip.dataset.id);

        if (leftHandle && leftHandle.dataset.textResizeBound !== '1') {
            leftHandle.dataset.textResizeBound = '1';
            leftHandle.addEventListener('mousedown', (e) => {
                e.stopPropagation();
                startTextOverlayResize(sceneId, 'left', e);
            });
        }

        if (rightHandle && rightHandle.dataset.textResizeBound !== '1') {
            rightHandle.dataset.textResizeBound = '1';
            rightHandle.addEventListener('mousedown', (e) => {
                e.stopPropagation();
                startTextOverlayResize(sceneId, 'right', e);
            });
        }

        if (clip.dataset.textDragBound !== '1') {
            clip.dataset.textDragBound = '1';
            clip.addEventListener('mousedown', (e) => {
                if (e.button !== 0) return;
                if (e.target.closest('.resize-handle')) return;
                startTextOverlayDrag(sceneId, e);
            });
        }
    });
}

function startTextOverlayDrag(sceneId, startEvent) {
    const sceneIndex = EditorState.scenes.findIndex(s => s.id === sceneId);
    const scene = EditorState.scenes[sceneIndex];
    const clip = elements.textTrack?.querySelector(`.text-clip[data-id="${sceneId}"]`);
    if (!scene || !clip) return;

    normalizeSceneTextOverlay(scene);
    startEvent.preventDefault();

    const startX = startEvent.clientX;
    const startOffset = getSceneTextOffset(scene);
    const textDuration = getSceneTextDuration(scene);
    const maxOffset = Math.max(0, scene.duration - textDuration);
    let moved = false;

    clip.classList.add('text-clip-dragging');

    const sceneStart = getSceneStartTime(sceneIndex);

    const onMouseMove = (e) => {
        const deltaDuration = pixelsToTime(e.clientX - startX);
        let newOffset = Math.max(0, Math.min(maxOffset, startOffset + deltaDuration));

        // Scene boundary snap (in absolute time) takes priority, then 0.5s grid
        const absStart = sceneStart + newOffset;
        const absEnd = absStart + textDuration;
        const snappedStart = snapToSceneBoundary(absStart, 8);
        const snappedEnd = snapToSceneBoundary(absEnd, 8);
        if (snappedStart !== absStart) {
            newOffset = Math.max(0, Math.min(maxOffset, snappedStart - sceneStart));
        } else if (snappedEnd !== absEnd) {
            newOffset = Math.max(0, Math.min(maxOffset, snappedEnd - textDuration - sceneStart));
        } else {
            newOffset = Math.round(newOffset * 2) / 2;
        }
        moved = moved || Math.abs(e.clientX - startX) > 2;

        scene.text_timeline_offset = newOffset;
        updateSceneAndTextClipLayout();
    };

    const onMouseUp = () => {
        document.removeEventListener('mousemove', onMouseMove);
        document.removeEventListener('mouseup', onMouseUp);
        clip.classList.remove('text-clip-dragging');

        if (moved) {
            clip.dataset.suppressClick = '1';
            if (scene.text_timeline_offset !== startOffset) {
                recordEdit(`Move text overlay (Scene ${sceneId})`, sceneId, 'text_timeline_offset', startOffset, scene.text_timeline_offset);
            }
            if (EditorState.preview) EditorState.preview.seek(EditorState.playbackPosition);
        }
    };

    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
}

function startTextOverlayResize(sceneId, handle, startEvent) {
    const scene = EditorState.scenes.find(s => s.id === sceneId);
    const clip = elements.textTrack?.querySelector(`.text-clip[data-id="${sceneId}"]`);
    if (!scene || !clip) return;

    normalizeSceneTextOverlay(scene);
    startEvent.preventDefault();

    const startX = startEvent.clientX;
    const startOffset = getSceneTextOffset(scene);
    const startDuration = getSceneTextDuration(scene);

    const onMouseMove = (e) => {
        const deltaDuration = Math.round(pixelsToTime(e.clientX - startX) * 2) / 2;
        if (handle === 'left') {
            const fixedEnd = startOffset + startDuration;
            const nextOffset = Math.max(0, Math.min(fixedEnd - MIN_TEXT_OVERLAY_DURATION, startOffset + deltaDuration));
            scene.text_timeline_offset = Math.round(nextOffset * 2) / 2;
            scene.text_overlay_duration = Math.round((fixedEnd - nextOffset) * 2) / 2;
        } else {
            const maxDuration = Math.max(MIN_TEXT_OVERLAY_DURATION, scene.duration - startOffset);
            scene.text_overlay_duration = Math.max(MIN_TEXT_OVERLAY_DURATION, Math.min(maxDuration, startDuration + deltaDuration));
            scene.text_overlay_duration = Math.round(scene.text_overlay_duration * 2) / 2;
        }
        normalizeSceneTextOverlay(scene);
        updateSceneAndTextClipLayout();
    };

    const onMouseUp = () => {
        document.removeEventListener('mousemove', onMouseMove);
        document.removeEventListener('mouseup', onMouseUp);

        if (scene.text_timeline_offset !== startOffset) {
            recordEdit(`Move text start (Scene ${sceneId})`, sceneId, 'text_timeline_offset', startOffset, scene.text_timeline_offset);
        }
        if (getSceneTextDuration(scene) !== startDuration) {
            recordEdit(`Resize text duration (Scene ${sceneId})`, sceneId, 'text_overlay_duration', startDuration, getSceneTextDuration(scene));
        }
        if (EditorState.preview) EditorState.preview.seek(EditorState.playbackPosition);
        renderSceneProperties();
    };

    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
}

/**
 * Start resizing a scene clip
 */
function startResize(sceneId, handle, startEvent) {
    const sceneIndex = EditorState.scenes.findIndex(s => s.id === sceneId);
    const scene = EditorState.scenes[sceneIndex];
    if (!scene) return;

    const prevScene = EditorState.scenes[sceneIndex - 1] || null;
    const nextScene = EditorState.scenes[sceneIndex + 1] || null;
    const minDuration = 0.5;

    const startX = startEvent.clientX;
    const startDuration = scene.duration;
    const startPrevDuration = prevScene?.duration ?? null;
    const startNextDuration = nextScene?.duration ?? null;

    const onMouseMove = (e) => {
        const deltaX = e.clientX - startX;
        let deltaDuration = deltaX / (EditorState.pixelsPerSecond * EditorState.zoomLevel);
        deltaDuration = Math.round(deltaDuration * 2) / 2;

        if (handle === 'right' && nextScene) {
            const maxGrow = Math.max(0, startNextDuration - minDuration);
            const maxShrink = Math.max(0, startDuration - minDuration);
            deltaDuration = Math.max(-maxShrink, Math.min(maxGrow, deltaDuration));
            scene.duration = Math.round((startDuration + deltaDuration) * 2) / 2;
            nextScene.duration = Math.round((startNextDuration - deltaDuration) * 2) / 2;
        } else if (handle === 'left' && prevScene) {
            const maxGrow = Math.max(0, startPrevDuration - minDuration);
            const maxShrink = Math.max(0, startDuration - minDuration);
            deltaDuration = Math.max(-maxGrow, Math.min(maxShrink, deltaDuration));
            prevScene.duration = Math.round((startPrevDuration + deltaDuration) * 2) / 2;
            scene.duration = Math.round((startDuration - deltaDuration) * 2) / 2;
        } else {
            let newDuration;
            if (handle === 'right') {
                newDuration = Math.max(minDuration, startDuration + deltaDuration);
            } else {
                newDuration = Math.max(minDuration, startDuration - deltaDuration);
            }
            scene.duration = Math.round(newDuration * 2) / 2;
        }

        updateSceneAndTextClipLayout();
    };

    const onMouseUp = () => {
        document.removeEventListener('mousemove', onMouseMove);
        document.removeEventListener('mouseup', onMouseUp);

        // Record edits for changed durations
        if (scene.duration !== startDuration) {
            recordEdit(`Resize duration (Scene ${sceneId})`, sceneId, 'duration', startDuration, scene.duration);
        }
        if (prevScene && prevScene.duration !== startPrevDuration) {
            recordEdit(`Resize duration (Scene ${prevScene.id})`, prevScene.id, 'duration', startPrevDuration, prevScene.duration);
        }
        if (nextScene && nextScene.duration !== startNextDuration) {
            recordEdit(`Resize duration (Scene ${nextScene.id})`, nextScene.id, 'duration', startNextDuration, nextScene.duration);
        }

        // Recalculate total duration
        recalculateDuration();
        renderTimeRuler();
        renderTextTrack();
        setupResizeHandlers();

        // Sync preview with updated scenes
        if (EditorState.preview) {
            EditorState.preview.setScenes(EditorState.scenes);
            EditorState.preview.render();
        }

        showToast(`Scene ${sceneId} duration: ${scene.duration}s`, 'info');
    };

    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
}

/**
 * Recalculate total duration from scenes and audio - uses helper functions
 */
function recalculateDuration() {
    normalizeTimelineDurations();

    // Use helper to get total duration (max of scenes and audio)
    const totalDuration = _roundTimelineSeconds(getScenesDuration());
    EditorState.project.totalDuration = totalDuration;

    // Update preview duration if available
    if (EditorState.preview) {
        EditorState.preview.setDuration(totalDuration);
    }

    updateProjectInfo();
    updateTimeScrubber();
    renderAllAudioTracks();
    renderTimeRuler();
}

/**
 * Select a scene
 */
function selectScene(sceneId) {
    // Deselect previous
    elements.videoTrack.querySelectorAll('.scene-clip.selected').forEach(el => {
        el.classList.remove('selected');
    });
    document.querySelectorAll('.text-clip.selected').forEach(el => el.classList.remove('selected'));

    // Deselect any selected audio track
    EditorState.selectedAudioTrack = null;
    EditorState.selectedTextOverlaySceneId = null;
    EditorState.selectedCaptionIdx = null;
    EditorState.selectedOverlayIdx = null;
    document.querySelectorAll('.audio-clip-universal.selected').forEach(el => el.classList.remove('selected'));
    document.querySelectorAll('.caption-clip.selected').forEach(el => el.classList.remove('selected'));

    // Select new
    const clip = elements.videoTrack.querySelector(`[data-id="${sceneId}"]`);
    if (clip) {
        clip.classList.add('selected');
    }
    const textClip = elements.textTrack?.querySelector(`.text-clip[data-id="${sceneId}"]`);
    const sceneForClip = EditorState.scenes.find(s => s.id === sceneId);
    if (textClip && sceneForClip && (sceneForClip.type === 'text' || sceneForClip.type === 'cta')) {
        textClip.classList.add('selected');
    }

    EditorState.selectedScene = EditorState.scenes.find(s => s.id === sceneId);

    // Calculate scene start time and seek to it using helper
    const sceneIndex = EditorState.scenes.findIndex(s => s.id === sceneId);
    if (sceneIndex >= 0) {
        const startTime = getSceneStartTime(sceneIndex);

        // Seek preview and timeline to scene start
        EditorState.playbackPosition = startTime;
        if (EditorState.preview) {
            EditorState.preview.seek(startTime);
        }
        seekAudio(startTime);
        updateTimeScrubber();
        updatePlayhead();
    }

    renderSceneProperties();
    updateEffectsTab();
    updateTransitionsTab();
    updateOverlaysTab();

    // Sync media grid selection
    document.querySelectorAll('.media-grid-item').forEach(item => {
        item.classList.toggle('selected', parseInt(item.dataset.sceneId) === sceneId);
    });
    renderTextToolState();
}

function selectTextOverlay(sceneId) {
    const sceneIndex = EditorState.scenes.findIndex(s => s.id === sceneId);
    const scene = EditorState.scenes[sceneIndex];
    if (!scene) return;

    EditorState.selectedScene = scene;
    EditorState.selectedTextOverlaySceneId = sceneId;
    EditorState.selectedAudioTrack = null;
    EditorState.selectedCaptionIdx = null;
    EditorState.selectedOverlayIdx = null;

    document.querySelectorAll('.scene-clip.selected').forEach(el => el.classList.remove('selected'));
    document.querySelectorAll('.audio-clip-universal.selected').forEach(el => el.classList.remove('selected'));
    document.querySelectorAll('.text-clip.selected').forEach(el => el.classList.remove('selected'));
    document.querySelectorAll('.caption-clip.selected').forEach(el => el.classList.remove('selected'));

    const clip = elements.textTrack?.querySelector(`.text-clip[data-id="${sceneId}"]`);
    if (clip) clip.classList.add('selected');

    const startTime = getSceneTextTimelineStart(sceneIndex);
    EditorState.playbackPosition = startTime;
    if (EditorState.preview) EditorState.preview.seek(startTime);
    seekAudio(startTime);
    updateTimeScrubber();
    updatePlayhead();
    renderSceneProperties();
    renderTextToolState();
}

/**
 * Render scene properties panel
 */
function renderSceneProperties() {
    if (!elements.sceneProperties) return;

    const scene = EditorState.selectedScene;
    if (!scene) {
        // If an audio track is selected, show its properties instead
        if (EditorState.selectedAudioTrack) {
            renderAudioProperties();
            return;
        }
        // If a caption is selected, show its properties instead
        if (EditorState.selectedCaptionIdx != null) {
            renderCaptionProperties();
            return;
        }
        // If an overlay is selected, show its properties instead
        if (EditorState.selectedOverlayIdx != null) {
            renderOverlayProperties();
            return;
        }
        elements.sceneProperties.innerHTML = '<div class="detail-placeholder">Select a scene to edit</div>';
        return;
    }

    const isTextScene = scene.type === 'text' || scene.type === 'cta';
    const isTextOverlaySelected = EditorState.selectedTextOverlaySceneId === scene.id && !isTextScene;
    if (isTextOverlaySelected) normalizeSceneTextOverlay(scene);
    const sceneIndex = EditorState.scenes.findIndex(s => s.id === scene.id);
    const previousScene = sceneIndex > 0 ? EditorState.scenes[sceneIndex - 1] : null;
    const hasStoredSceneBackground = hasSceneBackgroundMedia(scene);
    const canConvertTextSceneToOverlay = isTextScene &&
        !!previousScene &&
        !['text', 'cta'].includes(previousScene.type) &&
        !getSceneTextValue(previousScene);

    elements.sceneProperties.innerHTML = (isTextScene || isTextOverlaySelected) ? `
        <div class="caption-props-header">
            <span class="caption-props-icon" style="background:rgba(78,205,196,0.15);color:rgba(78,205,196,0.9)">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 7V4h16v3"/><path d="M9 20h6"/><path d="M12 4v16"/></svg>
            </span>
            <span class="caption-props-title">${isTextOverlaySelected ? 'Text Overlay' : 'Text Scene'}</span>
        </div>

        <div class="property-group">
            <label>Scene ID</label>
            <span class="property-value">${scene.id}</span>
        </div>
        ${!isTextOverlaySelected ? `
        <div class="property-group">
            <label>Duration</label>
            <input type="number" class="property-input" id="prop-duration"
                   value="${scene.duration}" min="0.5" step="0.5">
        </div>
        ` : `
        <div class="property-group">
            <label>Overlay Duration</label>
            <input type="number" class="property-input" id="prop-text-overlay-duration"
                   value="${getSceneTextDuration(scene)}" min="0.5" max="${scene.duration}" step="0.5">
        </div>
        <div class="property-group">
            <label>Start In Scene</label>
            <span class="property-value">${getSceneTextOffset(scene).toFixed(1)}s</span>
        </div>
        `}

        <div class="property-group property-stack">
            <label>Text Content</label>
            <textarea class="property-textarea" id="prop-text-content"
                      rows="3" placeholder="Enter text to display...">${scene.text_content || scene.script || ''}</textarea>
        </div>

        <div class="property-section-divider"></div>

        <div class="property-section-label">Display &amp; Animation</div>

        <div class="property-group">
            <label>Display Mode</label>
            <div class="property-mode-buttons">
                <button class="property-mode-btn${(scene.text_display_mode || 'emphasis') === 'full' ? ' active' : ''}"
                        id="prop-text-mode-full" title="Show the complete text with fade animation">
                    Full Text
                </button>
                <button class="property-mode-btn${(scene.text_display_mode || 'emphasis') !== 'full' ? ' active' : ''}"
                        id="prop-text-mode-emphasis" title="Show only emphasis/key words from the text">
                    Emphasis
                </button>
            </div>
        </div>
        <div class="property-group">
            <label>Hook Animation</label>
            <select class="property-select" id="prop-hook-animation">
                ${_buildHookAnimationOptions(scene.text_hook_animation || getDefaultHookAnimation())}
            </select>
        </div>

        <div class="property-section-divider"></div>

        <div class="property-section-label">Typography</div>

        <div class="property-group">
            <label>Font</label>
            <select class="property-select" id="prop-font-family"></select>
        </div>
        <div class="property-group">
            <label>Size</label>
            <input type="number" class="property-input" id="prop-text-size"
                   value="${scene.text_size || 72}" min="12" max="200" step="2">
        </div>
        <div class="property-group">
            <label>Style</label>
            <select class="property-select" id="prop-font-style">
                <option value="bold" ${(scene.font_style || 'bold') === 'bold' ? 'selected' : ''}>Bold</option>
                <option value="normal" ${scene.font_style === 'normal' ? 'selected' : ''}>Regular</option>
                <option value="light" ${scene.font_style === 'light' ? 'selected' : ''}>Light</option>
                <option value="italic" ${scene.font_style === 'italic' ? 'selected' : ''}>Italic</option>
                <option value="bold-italic" ${scene.font_style === 'bold-italic' ? 'selected' : ''}>Bold Italic</option>
            </select>
        </div>
        <div class="property-group">
            <label>Color</label>
            <div class="text-color-picker">
                <button class="text-color-swatch${(scene.text_color || 'white') === 'white' ? ' active' : ''}" data-color="white" style="background:#fff" title="White"></button>
                <button class="text-color-swatch${scene.text_color === 'black' ? ' active' : ''}" data-color="black" style="background:#000" title="Black"></button>
                <label class="text-color-custom-wrap" title="Custom color">
                    <input type="color" id="prop-text-color-picker"
                           value="${(scene.text_color || 'white') === 'white' ? '#ffffff' : scene.text_color === 'black' ? '#000000' : scene.text_color || '#ffffff'}">
                    <span class="text-color-custom-swatch${scene.text_color && scene.text_color !== 'white' && scene.text_color !== 'black' ? ' active' : ''}"
                          style="background:${scene.text_color && scene.text_color.startsWith('#') ? scene.text_color : 'conic-gradient(red,yellow,lime,aqua,blue,magenta,red)'}"></span>
                </label>
            </div>
        </div>

        <div class="property-section-divider"></div>

        <div class="property-section-label">Layout</div>

        <div class="property-group">
            <label>Horizontal</label>
            <select class="property-select" id="prop-text-align">
                <option value="center" ${(scene.text_align || 'center') === 'center' ? 'selected' : ''}>Center</option>
                <option value="left" ${scene.text_align === 'left' ? 'selected' : ''}>Left</option>
                <option value="right" ${scene.text_align === 'right' ? 'selected' : ''}>Right</option>
            </select>
        </div>
        <div class="property-group">
            <label>Vertical</label>
            <select class="property-select" id="prop-vertical-align">
                <option value="center" ${(scene.vertical_align || 'center') === 'center' ? 'selected' : ''}>Center</option>
                <option value="top" ${scene.vertical_align === 'top' ? 'selected' : ''}>Top</option>
                <option value="bottom" ${scene.vertical_align === 'bottom' ? 'selected' : ''}>Bottom</option>
            </select>
        </div>
        <div class="property-group property-stack">
            <label>Position</label>
            <div class="property-position-info">
                ${scene.text_x !== undefined && scene.text_x !== null ?
            `<span class="position-value">X: ${Math.round(scene.text_x)}%, Y: ${Math.round(scene.text_y)}%</span>` :
            `<span class="position-value position-auto">Using alignment</span>`}
                <button class="btn btn-small btn-reset-position" id="reset-text-position"
                        ${scene.text_x === undefined || scene.text_x === null ? 'disabled' : ''}>
                    Reset
                </button>
            </div>
            <span class="property-hint">Drag text in preview to reposition</span>
        </div>

        <div class="property-section-divider"></div>

        <div class="property-section-label">Background</div>

        <div class="property-group property-stack">
            ${isTextScene ? `
                <div class="property-mode-buttons">
                    <button class="property-mode-btn${!scene.text_background_enabled ? ' active' : ''}"
                            id="prop-text-bg-scene"
                            ${hasStoredSceneBackground ? '' : 'disabled'}>
                        Scene Media
                    </button>
                    <button class="property-mode-btn${scene.text_background_enabled ? ' active' : ''}"
                            id="prop-text-bg-solid">
                        Solid Color
                    </button>
                </div>
                <span class="property-hint">${hasStoredSceneBackground ? 'Switch between scene background and solid color.' : 'No stored scene background — solid color only.'}</span>
            ` : `
                <label style="display:flex;align-items:center;justify-content:space-between;gap:8px">
                    <span>Solid Background</span>
                    <input type="checkbox" id="prop-text-bg-enabled" ${scene.text_background_enabled ? 'checked' : ''}>
                </label>
            `}
        </div>
        <div class="property-group">
            <label>Color</label>
            <input type="color" class="property-input property-input-color" id="prop-text-bg-color"
                   value="${scene.text_background_color || '#000000'}"
                   ${scene.text_background_enabled ? '' : 'disabled'}>
        </div>

        ${isTextOverlaySelected ? `
            <div class="property-section-divider"></div>
            <div class="property-group">
                <button class="btn btn-small" id="convert-text-overlay-to-scene">Turn Text Into Scene</button>
            </div>
        ` : ''}
        ${isTextScene ? `
            <div class="property-section-divider"></div>
            <div class="property-group property-stack">
                <label style="display:flex;align-items:center;justify-content:space-between;gap:8px">
                    <span>Hide captions during scene</span>
                    <input type="checkbox" id="prop-text-hide-captions" ${scene.text_hide_captions !== false ? 'checked' : ''}>
                </label>
                <span class="property-hint">Suppress burned-in captions while this text scene is on screen.</span>
            </div>
            <div class="property-section-divider"></div>
            <div class="property-group property-stack">
                <button class="btn btn-small" id="convert-text-scene-to-overlay" ${canConvertTextSceneToOverlay ? '' : 'disabled'}>
                    Turn Text Into Overlay
                </button>
                <span class="property-hint">${canConvertTextSceneToOverlay ? 'Move into the previous visual scene as an overlay.' : 'Needs a previous image/video scene without a text overlay.'}</span>
            </div>
        ` : ''}
    ` : `
        <div class="property-group">
            <label>Scene ID</label>
            <span class="property-value">${scene.id}</span>
        </div>
        <div class="property-group">
            <label>Type</label>
            <span class="property-value">${scene.type}</span>
        </div>
        <div class="property-group">
            <label>Duration</label>
            <input type="number" class="property-input" id="prop-duration"
                   value="${scene.duration}" min="0.5" step="0.5">
        </div>
        <div class="property-group">
            <label>Effect</label>
            <select class="property-select" id="prop-effect">
                <option value="static" ${scene.visual_fx === 'static' ? 'selected' : ''}>Static</option>
                <option value="zoom_in" ${scene.visual_fx === 'zoom_in' ? 'selected' : ''}>Zoom In</option>
                <option value="zoom_out" ${scene.visual_fx === 'zoom_out' ? 'selected' : ''}>Zoom Out</option>
                <option value="pan_left" ${scene.visual_fx === 'pan_left' ? 'selected' : ''}>Pan Left</option>
                <option value="pan_right" ${scene.visual_fx === 'pan_right' ? 'selected' : ''}>Pan Right</option>
                <option value="fade" ${scene.visual_fx === 'fade' ? 'selected' : ''}>Fade</option>
                <option value="shake" ${scene.visual_fx === 'shake' ? 'selected' : ''}>Shake</option>
                <option value="pan_up" ${scene.visual_fx === 'pan_up' ? 'selected' : ''}>Pan Up</option>
                <option value="pan_down" ${scene.visual_fx === 'pan_down' ? 'selected' : ''}>Pan Down</option>
                <option value="pan_diagonal_tl" ${scene.visual_fx === 'pan_diagonal_tl' ? 'selected' : ''}>Pan Diagonal ↗</option>
                <option value="pan_diagonal_br" ${scene.visual_fx === 'pan_diagonal_br' ? 'selected' : ''}>Pan Diagonal ↘</option>
                <option value="ken_burns" ${scene.visual_fx === 'ken_burns' ? 'selected' : ''}>Ken Burns</option>
            </select>
        </div>
        ${scene.image ? `
            <div class="property-group">
                <label>Image</label>
                <span class="property-value">${scene.image}</span>
            </div>
        ` : ''}
    `;

    // Add event listeners for property changes
    const durationInput = document.getElementById('prop-duration');
    const effectSelect = document.getElementById('prop-effect');
    const textContentInput = document.getElementById('prop-text-content');
    const textColorPicker = document.getElementById('prop-text-color-picker');
    const fontFamilySelect = document.getElementById('prop-font-family');
    if (fontFamilySelect) buildFontOptions(fontFamilySelect, scene.font_family || 'Inter');
    const textSizeInput = document.getElementById('prop-text-size');
    const fontStyleSelect = document.getElementById('prop-font-style');
    const textAlignSelect = document.getElementById('prop-text-align');
    const verticalAlignSelect = document.getElementById('prop-vertical-align');
    const textOverlayDurationInput = document.getElementById('prop-text-overlay-duration');
    const textBgEnabledInput = document.getElementById('prop-text-bg-enabled');
    const textBgColorInput = document.getElementById('prop-text-bg-color');
    const textBgSceneBtn = document.getElementById('prop-text-bg-scene');
    const textBgSolidBtn = document.getElementById('prop-text-bg-solid');
    const convertTextOverlayBtn = document.getElementById('convert-text-overlay-to-scene');
    const convertTextSceneBtn = document.getElementById('convert-text-scene-to-overlay');
    const textDisplayModeFullBtn = document.getElementById('prop-text-mode-full');
    const textDisplayModeEmphasisBtn = document.getElementById('prop-text-mode-emphasis');
    const textAnimationSelect = document.getElementById('prop-text-animation');

    // Display mode toggle
    textDisplayModeFullBtn?.addEventListener('click', () => {
        const old = scene.text_display_mode;
        scene.text_display_mode = 'full';
        textDisplayModeFullBtn.classList.add('active');
        textDisplayModeEmphasisBtn?.classList.remove('active');
        recordEdit(`Set display mode to Full (Scene ${scene.id})`, scene.id, 'text_display_mode', old, 'full');
        saveProjectEdits();
        if (EditorState.preview) { EditorState.preview.setScenes(EditorState.scenes); EditorState.preview.seek(EditorState.playbackPosition); }
    });
    textDisplayModeEmphasisBtn?.addEventListener('click', () => {
        const old = scene.text_display_mode;
        scene.text_display_mode = 'emphasis';
        textDisplayModeEmphasisBtn.classList.add('active');
        textDisplayModeFullBtn?.classList.remove('active');
        recordEdit(`Set display mode to Emphasis (Scene ${scene.id})`, scene.id, 'text_display_mode', old, 'emphasis');
        saveProjectEdits();
        if (EditorState.preview) { EditorState.preview.setScenes(EditorState.scenes); EditorState.preview.seek(EditorState.playbackPosition); }
    });

    // Hook animation select (unified animation + emphasis)
    const hookAnimationSelect = document.getElementById('prop-hook-animation');
    hookAnimationSelect?.addEventListener('change', (e) => {
        const old = scene.text_hook_animation;
        scene.text_hook_animation = e.target.value;
        // Resolve to legacy fields for backward compat
        const parts = _resolveHookParts(e.target.value);
        scene.text_animation = parts.animation;
        scene.text_emphasis = parts.emphasis;
        recordEdit(`Change hook animation (Scene ${scene.id})`, scene.id, 'text_hook_animation', old, e.target.value);
        saveProjectEdits();
        if (EditorState.preview) { EditorState.preview.setScenes(EditorState.scenes); EditorState.preview.seek(EditorState.playbackPosition); }
    });

    durationInput?.addEventListener('change', (e) => {
        const oldValue = scene.duration;
        const newValue = parseFloat(e.target.value) || 0.5;
        scene.duration = newValue;
        normalizeSceneTextOverlay(scene);
        recordEdit(`Change duration (Scene ${scene.id})`, scene.id, 'duration', oldValue, newValue);
        recalculateDuration();
        renderTimeline();
    });

    textOverlayDurationInput?.addEventListener('change', (e) => {
        const oldValue = getSceneTextDuration(scene);
        scene.text_overlay_duration = parseFloat(e.target.value) || oldValue || scene.duration;
        normalizeSceneTextOverlay(scene);
        const newValue = getSceneTextDuration(scene);
        recordEdit(`Change text duration (Scene ${scene.id})`, scene.id, 'text_overlay_duration', oldValue, newValue);
        renderTextTrack();
        if (EditorState.preview) EditorState.preview.seek(EditorState.playbackPosition);
        renderSceneProperties();
    });

    effectSelect?.addEventListener('change', (e) => {
        const oldValue = scene.visual_fx;
        const newValue = e.target.value;
        scene.visual_fx = newValue;
        recordEdit(`Change effect (Scene ${scene.id})`, scene.id, 'visual_fx', oldValue, newValue);
    });

    // Text content change - update scene and refresh preview (debounced save)
    let textDebounceTimer = null;
    textContentInput?.addEventListener('input', (e) => {
        const oldValue = scene.text_content;
        scene.text_content = e.target.value;
        normalizeSceneTextOverlay(scene);
        renderTextTrack();
        // Refresh preview to show updated text
        if (EditorState.preview) {
            EditorState.preview.seek(EditorState.playbackPosition);
        }
        // Debounce recording to avoid saving every keystroke
        clearTimeout(textDebounceTimer);
        textDebounceTimer = setTimeout(() => {
            if (oldValue !== scene.text_content) {
                recordEdit(`Edit text (Scene ${scene.id})`, scene.id, 'text_content', oldValue, scene.text_content);
                saveProjectEdits();
            }
        }, 1000);
    });

    // Text size change (pixels) - update scene and refresh preview
    textSizeInput?.addEventListener('change', (e) => {
        const oldValue = scene.text_size;
        const newValue = parseInt(e.target.value) || 48;
        scene.text_size = newValue;
        recordEdit(`Change font size (Scene ${scene.id})`, scene.id, 'text_size', oldValue, newValue);
        if (EditorState.preview) {
            EditorState.preview.seek(EditorState.playbackPosition);
        }
    });

    // Font family change - update scene and refresh preview
    fontFamilySelect?.addEventListener('change', (e) => {
        const oldValue = scene.font_family;
        const newValue = e.target.value;
        scene.font_family = newValue;
        recordEdit(`Change font family (Scene ${scene.id})`, scene.id, 'font_family', oldValue, newValue);
        if (EditorState.preview) {
            EditorState.preview.seek(EditorState.playbackPosition);
        }
    });

    // Font style change - update scene and refresh preview
    fontStyleSelect?.addEventListener('change', (e) => {
        const oldValue = scene.font_style;
        const newValue = e.target.value;
        scene.font_style = newValue;
        recordEdit(`Change font style (Scene ${scene.id})`, scene.id, 'font_style', oldValue, newValue);
        if (EditorState.preview) {
            EditorState.preview.seek(EditorState.playbackPosition);
        }
    });

    // Text align change - update scene and refresh preview
    textAlignSelect?.addEventListener('change', (e) => {
        const oldValue = scene.text_align;
        const newValue = e.target.value;
        scene.text_align = newValue;
        recordEdit(`Change text align (Scene ${scene.id})`, scene.id, 'text_align', oldValue, newValue);
        if (EditorState.preview) {
            EditorState.preview.seek(EditorState.playbackPosition);
        }
    });

    // Vertical align change - update scene and refresh preview
    verticalAlignSelect?.addEventListener('change', (e) => {
        const oldValue = scene.vertical_align;
        const newValue = e.target.value;
        scene.vertical_align = newValue;
        recordEdit(`Change vertical align (Scene ${scene.id})`, scene.id, 'vertical_align', oldValue, newValue);
        if (EditorState.preview) {
            EditorState.preview.seek(EditorState.playbackPosition);
        }
    });

    // Text color change - update scene and refresh preview
    // Text color — swatch buttons + custom picker
    const _applyTextColor = (newValue) => {
        const oldValue = scene.text_color;
        if (oldValue === newValue) return;
        scene.text_color = newValue;
        recordEdit(`Change text color (Scene ${scene.id})`, scene.id, 'text_color', oldValue, newValue);
        if (EditorState.preview) EditorState.preview.seek(EditorState.playbackPosition);
        // Update swatch active states
        elements.sceneProperties.querySelectorAll('.text-color-swatch').forEach(s => {
            s.classList.toggle('active', s.dataset.color === newValue);
        });
        const customSwatch = elements.sceneProperties.querySelector('.text-color-custom-swatch');
        if (customSwatch) {
            const isCustom = newValue !== 'white' && newValue !== 'black';
            customSwatch.classList.toggle('active', isCustom);
            if (isCustom) customSwatch.style.background = newValue;
        }
    };
    elements.sceneProperties.querySelectorAll('.text-color-swatch').forEach(btn => {
        btn.addEventListener('click', () => _applyTextColor(btn.dataset.color));
    });
    textColorPicker?.addEventListener('input', (e) => {
        _applyTextColor(e.target.value);
    });

    textBgEnabledInput?.addEventListener('change', (e) => {
        const oldValue = !!scene.text_background_enabled;
        scene.text_background_enabled = e.target.checked;
        recordEdit(`Toggle text background (Scene ${scene.id})`, scene.id, 'text_background_enabled', oldValue, scene.text_background_enabled);
        if (textBgColorInput) textBgColorInput.disabled = !scene.text_background_enabled;
        renderTimeline();
        if (EditorState.preview) EditorState.preview.seek(EditorState.playbackPosition);
    });

    textBgColorInput?.addEventListener('change', (e) => {
        const oldValue = scene.text_background_color || '#000000';
        scene.text_background_color = e.target.value || '#000000';
        recordEdit(`Change text background color (Scene ${scene.id})`, scene.id, 'text_background_color', oldValue, scene.text_background_color);
        renderTimeline();
        if (EditorState.preview) EditorState.preview.seek(EditorState.playbackPosition);
    });

    textBgSceneBtn?.addEventListener('click', () => {
        if (!hasStoredSceneBackground) return;
        const oldValue = !!scene.text_background_enabled;
        if (!oldValue) return;
        scene.text_background_enabled = false;
        recordEdit(`Use scene background (Scene ${scene.id})`, scene.id, 'text_background_enabled', oldValue, false);
        renderTimeline();
        renderSceneProperties();
        if (EditorState.preview) EditorState.preview.seek(EditorState.playbackPosition);
    });

    textBgSolidBtn?.addEventListener('click', () => {
        const oldValue = !!scene.text_background_enabled;
        if (oldValue) return;
        scene.text_background_enabled = true;
        recordEdit(`Use solid background (Scene ${scene.id})`, scene.id, 'text_background_enabled', oldValue, true);
        renderTimeline();
        renderSceneProperties();
        if (EditorState.preview) EditorState.preview.seek(EditorState.playbackPosition);
    });

    convertTextOverlayBtn?.addEventListener('click', () => {
        convertTextOverlayToScene(scene.id);
    });

    convertTextSceneBtn?.addEventListener('click', () => {
        convertTextSceneToOverlay(scene.id);
    });

    // Hide-captions toggle for text scenes — suppress burned-in captions
    // while this scene is on screen.
    const hideCaptionsInput = document.getElementById('prop-text-hide-captions');
    hideCaptionsInput?.addEventListener('change', (e) => {
        const oldValue = scene.text_hide_captions !== false;
        const newValue = !!e.target.checked;
        scene.text_hide_captions = newValue;
        recordEdit(`Toggle hide captions (Scene ${scene.id})`, scene.id, 'text_hide_captions', oldValue, newValue);
        saveProjectEdits();
        if (EditorState.preview) {
            EditorState.preview.setScenes(EditorState.scenes);
            EditorState.preview.seek(EditorState.playbackPosition);
        }
    });

    // Reset text position - clear custom position to use alignment
    const resetPositionBtn = document.getElementById('reset-text-position');
    resetPositionBtn?.addEventListener('click', () => {
        const oldX = scene.text_x;
        const oldY = scene.text_y;
        scene.text_x = undefined;
        scene.text_y = undefined;
        recordEdit(`Reset text position (Scene ${scene.id})`, scene.id, 'text_position', { x: oldX, y: oldY }, null);
        saveProjectEdits();
        if (EditorState.preview) {
            EditorState.preview.seek(EditorState.playbackPosition);
        }
        // Re-render properties to update position display
        renderSceneProperties();
    });
}

/**
 * Render time ruler
 */
function renderTimeRuler() {
    if (!elements.timeRuler) return;

    const totalSeconds = getTotalDuration();
    const pps = EditorState.pixelsPerSecond * EditorState.zoomLevel;

    // Adaptive tick intervals based on effective pixels-per-second
    let majorInterval, minorInterval;
    if (pps >= 80) { majorInterval = 1; minorInterval = 0.5; }
    else if (pps >= 40) { majorInterval = 2; minorInterval = 1; }
    else if (pps >= 20) { majorInterval = 5; minorInterval = 1; }
    else if (pps >= 10) { majorInterval = 10; minorInterval = 5; }
    else { majorInterval = 30; minorInterval = 10; }

    let markers = '';

    // Minor ticks
    for (let t = 0; t <= totalSeconds; t += minorInterval) {
        // Skip positions that coincide with major ticks
        if (Math.abs(t % majorInterval) < 0.001 || Math.abs(t % majorInterval - majorInterval) < 0.001) continue;
        const left = timeToPixels(t);
        markers += `<span class="time-tick-minor" style="left:${left}px"></span>`;
    }

    // Major ticks with labels
    for (let t = 0; t <= totalSeconds; t += majorInterval) {
        const left = timeToPixels(t);
        markers += `<span class="time-marker" style="left: ${left}px">${formatTimestamp(t)}</span>`;
    }

    elements.timeRuler.innerHTML = markers;
    renderMinimap();
}

/**
 * Render timeline minimap (overview bar above time ruler)
 */
function renderMinimap() {
    const container = elements.timelineMinimap;
    if (!container) return;
    const totalDur = getTotalDuration();
    if (!totalDur) { container.innerHTML = ''; return; }

    // The minimap always represents the full project duration spread across 100% width.
    // The viewport indicator shows which portion is visible in the scrollable timeline.
    const contentPct = 100;

    // Helper: convert time fraction to percentage within the content area
    const pct = (timeFrac) => timeFrac * contentPct;

    let html = '';
    let t = 0;

    // Scene blocks with color coding
    EditorState.scenes.forEach((s, i) => {
        const left = pct(t / totalDur);
        const width = pct((s.duration || 0) / totalDur);
        const isText = s.type === 'text';
        const alpha = isText ? 0.15 : (i % 2 === 0 ? 0.35 : 0.22);
        const hue = isText ? '167,139,250' : '45,212,191';
        const selected = EditorState.selectedScene?.id === s.id ? ' minimap-scene-selected' : '';
        html += `<div class="minimap-scene${selected}" data-scene-id="${s.id}" style="left:${left}%;width:${width}%;background:rgba(${hue},${alpha});"></div>`;
        t += s.duration || 0;
    });

    // Audio track indicators
    const voiceTrack = EditorState.audioTracks.find(t => t.type === 'voice' && !t.muted);
    const musicTrack = EditorState.audioTracks.find(t => t.type === 'music' && !t.muted);
    if (voiceTrack) {
        const vStart = pct(getTrackTimelineOffset(voiceTrack) / totalDur);
        const vEnd = pct((getTrackTimelineEnd(voiceTrack, totalDur) || totalDur) / totalDur);
        html += `<div class="minimap-audio minimap-audio-voice" style="left:${vStart}%;width:${Math.min(vEnd - vStart, contentPct - vStart)}%;"></div>`;
    }
    if (musicTrack) {
        const mWidth = musicTrack.loop ? contentPct : pct(Math.min(1, (musicTrack.duration || totalDur) / totalDur));
        html += `<div class="minimap-audio minimap-audio-music" style="left:0%;width:${mWidth}%;"></div>`;
    }

    // Playhead
    const playPct = pct(EditorState.playbackPosition / totalDur);
    html += `<div class="minimap-playhead" style="left:${playPct}%"></div>`;

    // Viewport indicator
    if (elements.timelineTracks) {
        const scrollLeft = elements.timelineTracks.scrollLeft;
        const visibleWidth = elements.timelineTracks.clientWidth;
        const viewLeft = pct(pixelsToTime(scrollLeft) / totalDur);
        const viewWidth = pct(pixelsToTime(visibleWidth) / totalDur);
        html += `<div class="minimap-viewport" style="left:${viewLeft}%;width:${Math.min(viewWidth, contentPct - viewLeft)}%"></div>`;
    }

    container.innerHTML = html;
}

/**
 * Update time scrubber
 */
function updateTimeScrubber() {
    if (elements.timeScrubber) {
        elements.timeScrubber.max = getTotalDuration();
        elements.timeScrubber.value = EditorState.playbackPosition;
    }
    if (elements.currentTime) {
        elements.currentTime.textContent = formatTimecode(EditorState.playbackPosition);
    }
}

/**
 * Scroll timeline to show a specific time position with smooth behavior
 * Keeps playhead at a fixed position from left, then gradually scrolls
 * as content approaches the end
 */
function scrollTimelineToTime(time) {
    if (!elements.timelineTracks) return;

    const containerWidth = elements.timelineTracks.clientWidth;
    const totalDuration = getTotalDuration();
    const totalContentWidth = timeToPixels(totalDuration);
    const pixelPos = timeToPixels(time);

    // Fixed playhead position from left edge (20% or 150px max)
    const fixedPlayheadOffset = Math.min(150, containerWidth * 0.2);

    // Right edge buffer - how far from right edge playhead should stay
    const rightEdgeBuffer = 50;

    // Calculate the maximum scroll position (when content ends)
    const maxScroll = Math.max(0, totalContentWidth - containerWidth + TRACK_BASE_OFFSET + rightEdgeBuffer);

    // Calculate target scroll to keep playhead at fixed position
    const targetScrollLeft = pixelPos - fixedPlayheadOffset + TRACK_BASE_OFFSET;

    // Smooth interpolation when near the end
    // As we get closer to end, gradually allow playhead to move right
    const progress = time / totalDuration;
    const endPhaseStart = 0.7; // Start transitioning at 70% progress

    let finalScrollLeft;

    if (progress > endPhaseStart && totalContentWidth > containerWidth) {
        // In the end phase - smoothly transition playhead from fixed position to end
        const endProgress = (progress - endPhaseStart) / (1 - endPhaseStart); // 0 to 1 in end phase
        const eased = easeOutCubic(endProgress);

        // Interpolate between keeping playhead fixed and letting it reach the end
        const normalScroll = pixelPos - fixedPlayheadOffset + TRACK_BASE_OFFSET;
        const endScroll = maxScroll;

        finalScrollLeft = normalScroll + (endScroll - normalScroll) * eased;
    } else {
        // Normal phase - keep playhead at fixed position
        finalScrollLeft = targetScrollLeft;
    }

    // Clamp to valid range and apply
    elements.timelineTracks.scrollLeft = Math.max(0, Math.min(finalScrollLeft, maxScroll));
}

/**
 * Easing function for smooth end-phase transition
 */
function easeOutCubic(t) {
    return 1 - Math.pow(1 - t, 3);
}

/**
 * Setup playhead drag functionality
 * Uses the header marker trail for visual feedback
 */
function setupPlayheadDrag() {
    const playhead = document.getElementById('timeline-playhead');
    const timelineTracks = document.getElementById('timeline-tracks');
    const headerMarker = elements.timelineHeaderMarker;
    const headerTrail = elements.headerMarkerTrail;

    if (!playhead || !timelineTracks) return;

    let isDragging = false;
    let dragStartPosition = 0;

    // Calculate time from X position using helper
    const getTimeFromX = (clientX) => {
        const tracksRect = timelineTracks.getBoundingClientRect();
        const relativeX = clientX - tracksRect.left - TRACK_BASE_OFFSET + timelineTracks.scrollLeft;
        const time = pixelsToTime(relativeX);
        return Math.max(0, Math.min(time, getTotalDuration()));
    };

    // Convert time position to header marker position (relative to visible area)
    const timeToMarkerPosition = (time) => {
        if (!headerMarker) return 0;
        const scrollLeft = timelineTracks.scrollLeft;
        const visibleWidth = timelineTracks.clientWidth - TRACK_BASE_OFFSET;
        const markerWidth = headerMarker.getBoundingClientRect().width;
        const timePixels = timeToPixels(time);
        const visiblePixelPos = timePixels - scrollLeft;
        return (visiblePixelPos / visibleWidth) * markerWidth;
    };

    // Update header marker trail based on drag
    const updateTrail = () => {
        if (!headerTrail || !headerMarker) return;

        const startMarkerPos = timeToMarkerPosition(dragStartPosition);
        const currentMarkerPos = timeToMarkerPosition(EditorState.playbackPosition);

        const left = Math.min(startMarkerPos, currentMarkerPos);
        const width = Math.abs(currentMarkerPos - startMarkerPos);

        headerTrail.style.left = `${Math.max(0, left)}px`;
        headerTrail.style.width = `${width}px`;
    };

    // Reset trail
    const resetTrail = () => {
        if (headerTrail) {
            setTimeout(() => {
                headerTrail.style.width = '0px';
            }, 300);
        }
    };

    // Start drag on playhead
    playhead.addEventListener('mousedown', (e) => {
        e.preventDefault();
        isDragging = true;
        dragStartPosition = EditorState.playbackPosition;
        playhead.classList.add('dragging');
        headerMarker?.classList.add('scrubbing');

        // Initialize trail at start position
        if (headerTrail) {
            const startPos = timeToMarkerPosition(dragStartPosition);
            headerTrail.style.left = `${startPos}px`;
            headerTrail.style.width = '0px';
        }

        // Pause playback while dragging
        if (EditorState.isPlaying) {
            togglePlayback();
        }
    });

    // Also allow clicking on timeline to seek
    timelineTracks.addEventListener('mousedown', (e) => {
        // Only if clicking on track content area, not on clips or audio clips
        if (
            e.target.closest('.scene-clip') ||
            e.target.closest('.text-clip') ||
            e.target.closest('.caption-clip') ||
            e.target.closest('.track-header') ||
            e.target.closest('.audio-clip-universal') ||
            e.target.closest('.audio-track-empty-target') ||
            e.target.closest('.add-track-row')
        ) return;

        isDragging = true;
        dragStartPosition = EditorState.playbackPosition;
        playhead.classList.add('dragging');
        headerMarker?.classList.add('scrubbing');

        // Initialize trail at start position
        if (headerTrail) {
            const startPos = timeToMarkerPosition(dragStartPosition);
            headerTrail.style.left = `${startPos}px`;
            headerTrail.style.width = '0px';
        }

        // Pause playback while dragging
        if (EditorState.isPlaying) {
            togglePlayback();
        }

        // Seek to clicked position
        EditorState.playbackPosition = getTimeFromX(e.clientX);
        if (EditorState.preview) {
            EditorState.preview.seek(EditorState.playbackPosition);
        }
        seekAudio(EditorState.playbackPosition);
        updateTimeScrubber();
        updatePlayhead();
        updateTrail();
    });

    // Handle drag movement
    document.addEventListener('mousemove', (e) => {
        if (!isDragging) return;

        EditorState.playbackPosition = getTimeFromX(e.clientX);
        if (EditorState.preview) {
            EditorState.preview.seek(EditorState.playbackPosition);
        }
        seekAudio(EditorState.playbackPosition);
        updateTimeScrubber();
        updatePlayhead();
        updateTrail();
    });

    // End drag
    document.addEventListener('mouseup', () => {
        if (isDragging) {
            isDragging = false;
            playhead.classList.remove('dragging');
            headerMarker?.classList.remove('scrubbing');
            resetTrail();
        }
    });
}


let _eventListenersReady = false;
function setupEventListeners() {
    if (_eventListenersReady) return;
    _eventListenersReady = true;

    // Play/Pause
    elements.playBtn?.addEventListener('click', togglePlayback);
    setupTextTool();

    // Skip to Start / End
    document.getElementById('skip-start-btn')?.addEventListener('click', skipToStart);
    document.getElementById('skip-end-btn')?.addEventListener('click', skipToEnd);

    // Loop Toggle
    elements.loopBtn?.addEventListener('click', toggleLoop);

    // Volume/Mute Toggle
    elements.volumeBtn?.addEventListener('click', toggleMute);

    // Fullscreen Toggle
    elements.fullscreenBtn?.addEventListener('click', toggleFullscreen);
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && elements.previewPanel?.classList.contains('fullscreen-mode')) {
            toggleFullscreen();
        }
    });

    // Undo/Redo buttons
    document.getElementById('undo-btn')?.addEventListener('click', undoEdit);
    document.getElementById('redo-btn')?.addEventListener('click', redoEdit);

    // Project share dialog
    setupShareDialog();

    // History dropdown
    setupHistoryDropdown();

    // Error dropdown
    setupErrorDropdown();

    // Keyboard shortcuts for undo/redo
    document.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'z') {
            e.preventDefault();
            if (e.shiftKey) {
                redoEdit();
            } else {
                undoEdit();
            }
        }
        if ((e.ctrlKey || e.metaKey) && e.key === 'y') {
            e.preventDefault();
            redoEdit();
        }
    });

    // Time scrubber
    elements.timeScrubber?.addEventListener('input', (e) => {
        EditorState.playbackPosition = parseFloat(e.target.value);
        if (EditorState.preview) {
            EditorState.preview.seek(EditorState.playbackPosition);
        }
        seekAudio(EditorState.playbackPosition);
        updateTimeScrubber();
        updatePlayhead();
    });

    // Playhead dragging
    setupPlayheadDrag();

    // Zoom controls
    elements.zoomIn?.addEventListener('click', () => {
        EditorState.zoomLevel = Math.min(4, EditorState.zoomLevel * 1.5);
        updateZoom();
    });

    elements.zoomOut?.addEventListener('click', () => {
        EditorState.zoomLevel = Math.max(0.25, EditorState.zoomLevel / 1.5);
        updateZoom();
    });

    // Select folder (File System Access API)
    elements.selectFolderBtn?.addEventListener('click', selectMediaFolder);

    // Randomize scene media (dice button)
    elements.randomizeMediaBtn?.addEventListener('click', randomizeSceneMedia);

    // Flip filler (shift cuts into silence gaps)
    elements.flipFillerBtn?.addEventListener('click', flipFillers);

    // Sync playhead with manual scroll
    if (elements.timelineTracks) {
        elements.timelineTracks.addEventListener('scroll', () => {
            updatePlayhead();
            updateHeaderMarker();
            renderMinimap();
        });
    }

    // Minimap click/drag to scroll timeline
    if (elements.timelineMinimap) {
        let minimapDragging = false;
        const scrollMinimapTo = (e) => {
            const rect = elements.timelineMinimap.getBoundingClientRect();
            const frac = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
            const time = frac * getTotalDuration();
            if (elements.timelineTracks) {
                const pps = EditorState.pixelsPerSecond * EditorState.zoomLevel;
                elements.timelineTracks.scrollLeft = time * pps - elements.timelineTracks.clientWidth / 2;
            }
        };
        elements.timelineMinimap.addEventListener('mousedown', (e) => {
            minimapDragging = true;
            scrollMinimapTo(e);
        });
        document.addEventListener('mousemove', (e) => {
            if (minimapDragging) scrollMinimapTo(e);
        });
        document.addEventListener('mouseup', () => {
            minimapDragging = false;
        });
    }

    // Timeline header marker click to seek
    setupHeaderMarkerScrub();

    // Preview JSON button
    elements.previewJsonBtn?.addEventListener('click', previewJson);

    // Keyboard shortcuts
    document.addEventListener('keydown', handleKeyboard);

    // Prevent global browser zoom
    window.addEventListener('wheel', (e) => {
        if (e.ctrlKey) {
            e.preventDefault();
        }
    }, { passive: false });

    // Timeline Zoom on Scroll (Ctrl + Wheel)
    if (elements.timelineTracks) {
        elements.timelineTracks.addEventListener('wheel', (e) => {
            if (e.ctrlKey) {
                e.preventDefault();

                // Determine zoom direction
                if (e.deltaY < 0) {
                    // Zoom In
                    EditorState.zoomLevel = Math.min(4, EditorState.zoomLevel * 1.1);
                } else {
                    // Zoom Out
                    EditorState.zoomLevel = Math.max(0.25, EditorState.zoomLevel / 1.1);
                }
                updateZoom();
            }
        }, { passive: false });
    }

    // Timeline vertical resize
    setupTimelineResize();

    // Setup export modal
    setupExportModal();

    // Setup export progress modal (cancel/close and download buttons)
    setupExportProgressModal();
    setupExportProfileSelector();

    // Background music
    document.getElementById('add-bgmusic')?.addEventListener('click', showMusicPicker);

    // Prevent accidental window close - warn user about unsaved changes
    setupBeforeUnloadWarning();

    // Caption controls
    setupCaptionControls();

    // Effects, Transitions & Overlays tabs
    setupEffectsTab();
    setupTransitionsTab();
    setupOverlaysTab();

    // Track toggling
    document.querySelectorAll('.track-toggle').forEach(icon => {
        icon.addEventListener('click', (e) => {
            const trackEl = e.target.closest('.track');
            if (!trackEl) return;

            const trackType = trackEl.dataset.track;
            const wasDisabled = EditorState.disabledTracks.has(trackType);

            // Toggle state
            if (wasDisabled) {
                EditorState.disabledTracks.delete(trackType);
                trackEl.classList.remove('disabled');
                showToast(`${trackType.charAt(0).toUpperCase() + trackType.slice(1)} track enabled`, 'info');
            } else {
                EditorState.disabledTracks.add(trackType);
                trackEl.classList.add('disabled');
                showToast(`${trackType.charAt(0).toUpperCase() + trackType.slice(1)} track disabled`, 'info');
            }

            // Update preview and playback if necessary
            updatePreviewFromDisabledTracks();
            recordEdit(`${wasDisabled ? 'Enable' : 'Disable'} ${trackType} track`, trackType, 'trackDisabled', wasDisabled, !wasDisabled);
        });
    });

    // Video audio toggle — enable/disable embedded video audio (muted by default)
    const videoAudioToggle = document.getElementById('video-audio-toggle');
    videoAudioToggle?.addEventListener('click', (e) => {
        e.stopPropagation();
        EditorState.videoAudioEnabled = !EditorState.videoAudioEnabled;
        videoAudioToggle.classList.toggle('muted', !EditorState.videoAudioEnabled);
        videoAudioToggle.title = EditorState.videoAudioEnabled ? 'Video Audio (on)' : 'Video Audio (muted)';
        if (EditorState.preview) {
            EditorState.preview.setVideoAudioEnabled(EditorState.videoAudioEnabled);
        }
        showToast(EditorState.videoAudioEnabled ? 'Video audio enabled' : 'Video audio muted', 'info');
    });

    // Add Track row — click anywhere on the row to show dropdown
    const addTrackRow = document.getElementById('add-track-row');
    addTrackRow?.addEventListener('mousedown', (e) => {
        if (e.button !== 0) return;
        e.stopPropagation();
    });
    addTrackRow?.addEventListener('click', (e) => {
        e.stopPropagation();
        showAddTrackMenu(addTrackRow);
    });
}

/**
 * Show dropdown menu for adding a new audio track
 */
function showAddTrackMenu(anchor) {
    // Close any existing menu
    document.querySelector('.add-track-menu')?.remove();

    const rect = anchor.getBoundingClientRect();
    const menu = document.createElement('div');
    menu.className = 'add-track-menu';
    menu.style.left = `${rect.left + 36}px`;
    menu.style.bottom = `${window.innerHeight - rect.top + 4}px`;

    menu.innerHTML = `
        <div class="add-track-menu-header">New audio track</div>
        <button class="add-track-menu-item" data-action="music">
            <div class="add-track-menu-icon music">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="rgba(167,139,250,0.9)" stroke-width="1.5">
                    <circle cx="5.5" cy="17.5" r="2.5"/><circle cx="17.5" cy="15.5" r="2.5"/>
                    <path d="M8 17.5V5l12-2v12.5"/>
                </svg>
            </div>
            <div class="add-track-menu-text">
                <span>Music</span>
                <span class="add-track-menu-desc">Browse music library</span>
            </div>
        </button>
        <button class="add-track-menu-item" data-action="fx">
            <div class="add-track-menu-icon fx">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="rgba(255,183,77,0.9)" stroke-width="1.5">
                    <path d="M2 12h4l3-9 4 18 3-9h4"/>
                </svg>
            </div>
            <div class="add-track-menu-text">
                <span>Sound FX</span>
                <span class="add-track-menu-desc">Add an empty FX track</span>
            </div>
        </button>
        <div class="add-track-menu-sep"></div>
        <button class="add-track-menu-item" data-action="upload">
            <div class="add-track-menu-icon upload">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                    <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/>
                    <polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>
                </svg>
            </div>
            <div class="add-track-menu-text">
                <span>Upload File</span>
                <span class="add-track-menu-desc">mp3, wav, ogg, m4a</span>
            </div>
        </button>
    `;

    document.body.appendChild(menu);

    // Handle menu clicks
    menu.querySelectorAll('.add-track-menu-item').forEach(item => {
        item.addEventListener('click', (e) => {
            e.stopPropagation();
            const action = item.dataset.action;
            menu.remove();

            if (action === 'music') {
                showMusicPicker();
            } else if (action === 'fx') {
                // Create an empty SFX track
                const fxTrack = createAudioTrack({
                    label: `SFX ${EditorState.audioTracks.filter(t => isSfxTrackType(t.type)).length + 1}`,
                    type: 'sfx',
                    color: AUDIO_TRACK_COLORS.sfx,
                    volume: 1.0,
                });
                EditorState.audioTracks.push(fxTrack);
                selectAudioTrack(fxTrack.id);
                renderAllAudioTracks();
                saveProjectEdits();
                showToast('SFX track added. Click the new lane to upload audio.', 'info');
            } else if (action === 'upload') {
                promptAudioFileUpload();
            }
        });
    });

    // Close on click outside
    const closeHandler = (e) => {
        if (!menu.contains(e.target) && !anchor.contains(e.target)) {
            menu.remove();
            document.removeEventListener('mousedown', closeHandler);
        }
    };
    setTimeout(() => document.addEventListener('mousedown', closeHandler), 0);
}

/**
 * Handle audio file upload — creates a new audio track with the uploaded file
 */
function promptAudioFileUpload(targetTrackId = null) {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.mp3,.wav,.ogg,.m4a,.aac';
    input.onchange = () => {
        if (!input.files?.length) return;
        _handleAudioFileUpload(input.files[0], { targetTrackId });
    };
    input.click();
}

function populateUploadedAudioTrack(track, file, data) {
    if (!track) return;

    if (track.element) {
        try {
            track.element.pause();
            track.element.src = '';
        } catch (_) { /* ignore */ }
    }

    track.file = data.filename || file.name;
    track.path = data.path || `/output/musics/${file.name}`;
    track.duration = 0;
    track.startOffset = 0;
    track.trimmedDuration = null;
    track.loaded = false;
    track.error = false;

    const audio = new Audio(track.path);
    track.element = audio;
    ensureTrackGainNode(track);

    audio.addEventListener('loadedmetadata', () => {
        track.duration = audio.duration || 0;
        track.loaded = true;
        applyTrackTrimState(track, {
            timelineOffset: getTrackTimelineOffset(track),
            startOffset: 0,
            trimmedDuration: null
        });
        recalculateDuration();
        renderTimeRuler();
        renderAllAudioTracks();
        updateTimeScrubber();
        updatePlayhead();
        if (EditorState.preview) EditorState.preview.setDuration(getTotalDuration());
        if (EditorState.isPlaying) {
            syncAudioPlayback();
        } else {
            track.element.currentTime = getTrackPlaybackTime(track, EditorState.playbackPosition);
        }
        saveProjectEdits();
        if (EditorState.selectedAudioTrack?.id === track.id) {
            EditorState.selectedAudioTrack = track;
            renderAudioProperties();
        }
    }, { once: true });

    audio.addEventListener('error', () => {
        track.error = true;
        renderAllAudioTracks();
        if (EditorState.selectedAudioTrack?.id === track.id) {
            renderAudioProperties();
        }
    }, { once: true });
}

async function _handleAudioFileUpload(file, options = {}) {
    const fd = new FormData();
    fd.append('file', file);
    try {
        const res = await fetch('/api/music/upload', { method: 'POST', body: fd });
        if (!res.ok) throw new Error('Upload failed');
        const data = await res.json();
        const targetTrack = options.targetTrackId ? getAudioTrackById(options.targetTrackId) : null;
        if (targetTrack) {
            populateUploadedAudioTrack(targetTrack, file, data);
            showToast(`Added to ${targetTrack.label}: ${file.name}`, 'success');
            return;
        }
        // Add as a new audio track
        const ext = file.name.split('.').pop().toLowerCase();
        const type = ['mp3', 'wav', 'ogg', 'm4a', 'aac'].includes(ext) ? 'sfx' : 'sfx';
        const track = createAudioTrack({
            label: file.name.replace(/\.[^.]+$/, ''),
            type: type,
            file: data.filename || file.name,
            path: data.path || `/output/musics/${file.name}`,
            volume: 1.0,
            color: AUDIO_TRACK_COLORS[type],
            loaded: true,
        });
        const audio = new Audio(track.path);
        track.element = audio;
        ensureTrackGainNode(track);
        audio.addEventListener('loadedmetadata', () => {
            track.duration = audio.duration;
            track.loaded = true;
            renderAllAudioTracks();
        });
        EditorState.audioTracks.push(track);
        renderAllAudioTracks();
        saveProjectEdits();
        showToast(`Added: ${file.name}`, 'success');
    } catch (e) {
        showToast('Upload failed: ' + e.message, 'error');
    }
}

/**
 * Update the preview state based on which tracks are disabled.
 */
function updatePreviewFromDisabledTracks() {
    // 1. Video track disabled - Hide/Show scenes in preview
    if (EditorState.preview) {
        if (EditorState.disabledTracks.has('video')) {
            EditorState.preview.setScenes([]);
        } else {
            EditorState.preview.setScenes(EditorState.scenes);
        }
    }

    // 2. Audio tracks — mute/unmute based on global mute or per-track disable
    for (const track of EditorState.audioTracks) {
        if (!track.element) continue;
        applyTrackVolumeLive(track, track.volume);
    }

    // 4. Caption track disabled - Hide/Show captions in preview
    if (EditorState.preview) {
        if (EditorState.disabledTracks.has('caption') || !EditorState.captionsEnabled) {
            EditorState.preview.setCaptions(null, null);
        } else if (EditorState.captionData) {
            EditorState.preview.setCaptions(EditorState.captionData.captions, EditorState.captionData.style);
        }
    }

    // Sync disabled tracks to preview so text scenes are hidden
    if (EditorState.preview) {
        EditorState.preview.disabledTracks = new Set(EditorState.disabledTracks);
        EditorState.preview.render();
    }
}

/**
 * Setup timeline vertical resize functionality
 */
function setupTimelineResize() {
    const handle = elements.timelineResizeHandle;
    const layout = elements.editorLayout;

    if (!handle || !layout) return;

    let isResizing = false;
    let startY = 0;
    let startHeight = 180;

    handle.addEventListener('mousedown', (e) => {
        isResizing = true;
        startY = e.clientY;
        startHeight = elements.timelinePanel?.offsetHeight || 180;
        handle.classList.add('dragging');
        document.body.style.cursor = 'ns-resize';
        document.body.style.userSelect = 'none';
        e.preventDefault();
    });

    document.addEventListener('mousemove', (e) => {
        if (!isResizing) return;

        const deltaY = startY - e.clientY;
        const newHeight = Math.max(150, Math.min(500, startHeight + deltaY));

        layout.style.setProperty('--timeline-height', `${newHeight}px`);
        updateClipSizes(newHeight);
    });

    document.addEventListener('mouseup', () => {
        if (isResizing) {
            isResizing = false;
            handle.classList.remove('dragging');
            document.body.style.cursor = '';
            document.body.style.userSelect = '';

            // Save timeline height to localStorage
            const currentHeight = elements.timelinePanel?.offsetHeight || 180;
            EditorState.timelineHeight = currentHeight;
            if (EditorState.storageEnabled) localStorage.setItem(STORAGE_KEYS.TIMELINE_HEIGHT, currentHeight.toString());
        }
    });
}

/**
 * Update clip and thumbnail sizes based on timeline height
 */
function updateClipSizes(timelineHeight) {
    const videoTrack = elements.videoTrack;
    if (!videoTrack) return;

    // Scale clip height based on timeline height (subtract toolbar ~44px, ruler ~24px, padding)
    const availableHeight = timelineHeight - 100;
    const clipHeight = Math.max(40, Math.min(120, availableHeight * 0.6));
    const thumbWidth = Math.max(36, clipHeight * 0.9);

    videoTrack.style.setProperty('--clip-height', `${clipHeight}px`);
    videoTrack.style.setProperty('--thumb-width', `${thumbWidth}px`);
}

/**
 * Setup header marker scrub functionality
 * The header marker represents the VISIBLE portion of the timeline (what you can see)
 */
function setupHeaderMarkerScrub() {
    const marker = elements.timelineHeaderMarker;
    const trail = elements.headerMarkerTrail;
    if (!marker) return;

    let isScrubbing = false;
    let scrubStartX = 0;

    const updateTrail = (currentX, markerWidth) => {
        if (!trail) return;

        const left = Math.min(scrubStartX, currentX);
        const width = Math.abs(currentX - scrubStartX);

        trail.style.left = `${left}px`;
        trail.style.width = `${width}px`;
    };

    const handleScrub = (e) => {
        if (!elements.timelineTracks) return;

        const rect = marker.getBoundingClientRect();
        const x = Math.max(0, Math.min(rect.width, e.clientX - rect.left));
        const markerWidth = rect.width;

        // Update trail
        updateTrail(x, markerWidth);

        // Get the visible timeline dimensions
        const scrollLeft = elements.timelineTracks.scrollLeft;
        const visibleWidth = elements.timelineTracks.clientWidth - TRACK_BASE_OFFSET;

        // Map click position on marker to pixel position on visible timeline
        const visiblePixelPos = (x / markerWidth) * visibleWidth;
        const actualPixelPos = scrollLeft + visiblePixelPos;
        const time = Math.max(0, Math.min(getTotalDuration(), pixelsToTime(actualPixelPos)));

        // Seek to position
        EditorState.playbackPosition = time;
        if (EditorState.preview) {
            EditorState.preview.seek(time);
        }
        seekAudio(time);
        updateTimeScrubber();
        updatePlayhead();
    };

    marker.addEventListener('mousedown', (e) => {
        isScrubbing = true;
        marker.classList.add('scrubbing');

        // Record start position for trail
        const rect = marker.getBoundingClientRect();
        scrubStartX = Math.max(0, Math.min(rect.width, e.clientX - rect.left));

        // Reset trail
        if (trail) {
            trail.style.left = `${scrubStartX}px`;
            trail.style.width = '0px';
        }

        handleScrub(e);
        document.body.style.cursor = 'ew-resize';
        document.body.style.userSelect = 'none';
    });

    document.addEventListener('mousemove', (e) => {
        if (isScrubbing) {
            handleScrub(e);
        }
    });

    document.addEventListener('mouseup', () => {
        if (isScrubbing) {
            isScrubbing = false;
            marker.classList.remove('scrubbing');
            document.body.style.cursor = '';
            document.body.style.userSelect = '';

            // Fade out trail (handled by CSS transition)
            if (trail) {
                setTimeout(() => {
                    trail.style.width = '0px';
                }, 300);
            }
        }
    });
}

/**
 * Update header marker indicator position
 * The indicator shows where the playhead is within the VISIBLE portion of the timeline
 */
function updateHeaderMarker() {
    const indicator = elements.headerMarkerIndicator;
    const marker = elements.timelineHeaderMarker;
    if (!indicator || !marker || !elements.timelineTracks) return;

    const markerWidth = marker.offsetWidth;

    // Get the visible timeline dimensions
    const scrollLeft = elements.timelineTracks.scrollLeft;
    const visibleWidth = elements.timelineTracks.clientWidth - TRACK_BASE_OFFSET;

    // Calculate playhead position in pixels
    const playheadPixelPos = timeToPixels(EditorState.playbackPosition);

    // Map playhead position to marker position based on visible area
    const relativePos = playheadPixelPos - scrollLeft;
    const left = (relativePos / visibleWidth) * markerWidth;

    indicator.style.left = `${Math.max(0, Math.min(markerWidth - 3, left))}px`;
}

/**
 * Toggle playback
 */
function togglePlayback() {
    if (EditorState.preview) {
        EditorState.isPlaying = EditorState.preview.toggle();
    } else {
        EditorState.isPlaying = !EditorState.isPlaying;
        if (EditorState.isPlaying) {
            startPlayback();
        }
    }

    // Sync audio playback
    syncAudioPlayback();

    updatePlayButton();
}

/**
 * Jump to start of timeline
 */
function skipToStart() {
    EditorState.playbackPosition = 0;
    if (EditorState.preview) EditorState.preview.seek(0);
    seekAudio(0);
    updatePlayhead();
    updateTimeScrubber();

    // Scroll timeline to start
    if (elements.timelineTracks) elements.timelineTracks.scrollLeft = 0;
}

/**
 * Jump to end of timeline
 */
function skipToEnd() {
    const totalDuration = getTotalDuration();
    if (totalDuration <= 0) return;

    // Pause first if playing
    if (EditorState.isPlaying) togglePlayback();

    EditorState.playbackPosition = Math.max(0, totalDuration - 0.01);
    if (EditorState.preview) EditorState.preview.seek(EditorState.playbackPosition);
    seekAudio(EditorState.playbackPosition);
    updatePlayhead();
    updateTimeScrubber();

    // Scroll timeline so the end is visible
    if (elements.timelineTracks) {
        const pixelPos = timeToPixels(totalDuration);
        const containerWidth = elements.timelineTracks.clientWidth;
        elements.timelineTracks.scrollLeft = Math.max(0, pixelPos - containerWidth + TRACK_BASE_OFFSET + 40);
    }
}

/**
 * Toggle fullscreen preview mode
 */
function toggleFullscreen() {
    const panel = elements.previewPanel;
    if (!panel) return;

    const isFullscreen = panel.classList.toggle('fullscreen-mode');

    if (elements.fullscreenBtn) {
        if (isFullscreen) {
            elements.fullscreenBtn.innerHTML = `
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
                    <path d="M8 3v3a2 2 0 01-2 2H3m18 0h-3a2 2 0 01-2-2V3m0 18v-3a2 2 0 012-2h3M3 16h3a2 2 0 012 2v3"/>
                </svg>`;
            elements.fullscreenBtn.classList.add('active');
        } else {
            elements.fullscreenBtn.innerHTML = `
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
                    <path d="M8 3H5a2 2 0 00-2 2v3m18 0V5a2 2 0 00-2-2h-3m0 18h3a2 2 0 002-2v-3M3 16v3a2 2 0 002 2h3"/>
                </svg>`;
            elements.fullscreenBtn.classList.remove('active');
        }
    }

    // Re-render preview at new size
    if (EditorState.preview) {
        requestAnimationFrame(() => EditorState.preview.render());
    }
}

/**
 * Toggle loop mode
 */
function toggleLoop() {
    EditorState.isLooping = !EditorState.isLooping;

    // Save to localStorage
    if (EditorState.storageEnabled) localStorage.setItem(STORAGE_KEYS.LOOP_STATE, EditorState.isLooping.toString());

    if (elements.loopBtn) {
        if (EditorState.isLooping) {
            elements.loopBtn.classList.add('active');
            showToast('Loop enabled', 'info');
        } else {
            elements.loopBtn.classList.remove('active');
            showToast('Loop disabled', 'info');
        }
    }
}

/**
 * Toggle audio mute
 */
function toggleMute() {
    EditorState.isMuted = !EditorState.isMuted;

    // Keep mute state in the same live output path as the volume sliders.
    for (const track of EditorState.audioTracks) {
        applyTrackVolumeLive(track, track.volume);
    }

    // Update button icon
    updateVolumeIcon();

    showToast(EditorState.isMuted ? 'Audio muted' : 'Audio unmuted', 'info');
}

/**
 * Update volume button icon based on mute state
 */
function updateVolumeIcon() {
    if (!elements.volumeBtn) return;

    if (EditorState.isMuted) {
        elements.volumeBtn.innerHTML = `
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
                <line x1="23" y1="9" x2="17" y2="15" />
                <line x1="17" y1="9" x2="23" y2="15" />
            </svg>`;
        elements.volumeBtn.classList.add('muted');
    } else {
        elements.volumeBtn.innerHTML = `
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
                <path d="M15.54 8.46a5 5 0 0 1 0 7.07" />
            </svg>`;
        elements.volumeBtn.classList.remove('muted');
    }
}

/**
 * Sync audio with current playback state
 */
function syncAudioPlayback() {
    const voiceTrack = getVoiceTrack();

    if (EditorState.isPlaying) {
        ensureAudioContextReady();

        // Play all audio tracks
        for (const track of EditorState.audioTracks) {
            if (!track.element || !track.file) continue;
            if (track.muted) { track.element.pause(); continue; }

            // Determine effective end time for this track
            const trackStart = getTrackTimelineOffset(track);
            const trackEnd = getTrackTimelineEnd(track, getTotalDuration()) || Infinity;

            if (EditorState.playbackPosition < trackStart) {
                track.element.pause();
                track.element.currentTime = getTrackPlaybackTime(track, trackStart);
                continue;
            }

            if (track.loop) {
                track.element.currentTime = getTrackPlaybackTime(track, EditorState.playbackPosition);
            } else {
                // Don't play past trimmed/actual duration
                if (EditorState.playbackPosition >= trackEnd) {
                    track.element.pause();
                    continue;
                }
                track.element.currentTime = getTrackPlaybackTime(track, EditorState.playbackPosition);
            }

            // Apply ducking on music tracks when voice is playing
            applyTrackVolumeLive(track, track.volume, { resumeContext: true });

            track.element.play().catch(() => {});
        }

        // Use voice track as master clock for preview sync
        if (EditorState.preview) {
            const startSysTime = performance.now();
            const startPlayPos = EditorState.playbackPosition;
            EditorState.preview.setTimeSource(() => {
                const timeFromStart = startPlayPos + (performance.now() - startSysTime) / 1000;
                if (voiceTrack?.element && voiceTrack.loaded && !voiceTrack.element.paused) {
                    const audioTrimEnd = getTrackSourceEnd(voiceTrack);
                    if (voiceTrack.element.currentTime < audioTrimEnd) {
                        return getTrackTimelineOffset(voiceTrack) + Math.max(0, voiceTrack.element.currentTime - getTrackStartOffset(voiceTrack));
                    }
                }
                return timeFromStart;
            });
        }
    } else {
        // Pause all tracks
        for (const track of EditorState.audioTracks) {
            if (track.element) track.element.pause();
        }

        // Clear external time source when paused
        if (EditorState.preview) {
            EditorState.preview.setTimeSource(null);
        }
    }
}

/**
 * Seek audio to specific time
 */
function seekAudio(time) {
    for (const track of EditorState.audioTracks) {
        // Multi-clip FX tracks
        if (track.clips && track.clips.length > 0) {
            for (const clip of track.clips) {
                if (!clip.element) continue;
                const clipStart = clip.offset;
                const clipEnd = clip.offset + (clip.duration || 0);
                if (time >= clipStart && time < clipEnd) {
                    clip.element.currentTime = time - clipStart;
                } else {
                    clip.element.pause();
                    clip.element.currentTime = 0;
                }
            }
            continue;
        }
        if (!track.element) continue;
        track.element.currentTime = getTrackPlaybackTime(track, time);
    }
}

/**
 * Update play button icon
 */
function updatePlayButton() {
    if (!elements.playBtn) return;

    if (EditorState.isPlaying) {
        elements.playBtn.innerHTML = `
            <svg viewBox="0 0 24 24" fill="currentColor">
                <rect x="6" y="4" width="4" height="16"/>
                <rect x="14" y="4" width="4" height="16"/>
            </svg>
        `;
    } else {
        elements.playBtn.innerHTML = `
            <svg viewBox="0 0 24 24" fill="currentColor">
                <polygon points="6 4 20 12 6 20 6 4"/>
            </svg>
        `;
    }
}

/**
 * Start playback loop (fallback when no preview - uses helper functions)
 */
function startPlayback() {
    if (!EditorState.isPlaying) return;

    const startTime = performance.now();
    const startPosition = EditorState.playbackPosition;

    function tick() {
        if (!EditorState.isPlaying) return;

        const elapsed = (performance.now() - startTime) / 1000;
        EditorState.playbackPosition = startPosition + elapsed;

        const totalDuration = getTotalDuration();
        if (EditorState.playbackPosition >= totalDuration) {
            EditorState.playbackPosition = 0;
            EditorState.isPlaying = false;

            // Return to start
            if (elements.timelineTracks) {
                elements.timelineTracks.scrollLeft = 0;
            }

            togglePlayback();
            return;
        }

        // Scroll timeline using helper
        scrollTimelineToTime(EditorState.playbackPosition);

        updateTimeScrubber();
        updatePlayhead();
        requestAnimationFrame(tick);
    }

    requestAnimationFrame(tick);
}

/**
 * Update playhead position - uses helper functions for precise calculation
 */
function updatePlayhead() {
    const playhead = document.getElementById('timeline-playhead');
    if (playhead) {
        const scrollLeft = elements.timelineTracks ? elements.timelineTracks.scrollLeft : 0;
        const pixelPos = timeToPixels(EditorState.playbackPosition);
        const left = TRACK_BASE_OFFSET + pixelPos - scrollLeft;
        playhead.style.left = `${left}px`;

        // Update floating time label
        const timeLabel = document.getElementById('playhead-time-label');
        if (timeLabel) {
            if (EditorState.playbackPosition > 0) {
                timeLabel.textContent = formatTimestamp(EditorState.playbackPosition);
                timeLabel.classList.add('visible');
            } else {
                timeLabel.classList.remove('visible');
            }
        }
    }

    // Update minimap playhead (lightweight — just move the existing element)
    const mmPlayhead = elements.timelineMinimap?.querySelector('.minimap-playhead');
    if (mmPlayhead) {
        const totalDur = getTotalDuration();
        if (totalDur) {
            mmPlayhead.style.left = `${(EditorState.playbackPosition / totalDur) * 100}%`;
        }
    }

    // Also update header marker indicator
    updateHeaderMarker();
}

/**
 * Update zoom level - uses helper functions for precise calculation
 */
function updateZoom() {
    // Save to localStorage
    if (EditorState.storageEnabled) localStorage.setItem(STORAGE_KEYS.ZOOM_LEVEL, EditorState.zoomLevel.toString());

    if (elements.zoomLevel) {
        elements.zoomLevel.textContent = `${Math.round(EditorState.zoomLevel * 100)}%`;
    }
    renderTimeline();
    renderTimeRuler();
    renderAllAudioTracks();

    // Keep playhead visible after zoom by scrolling to current position
    if (elements.timelineTracks) {
        const containerWidth = elements.timelineTracks.clientWidth;
        const pixelPos = timeToPixels(EditorState.playbackPosition);

        // Center the playhead in the view after zoom
        const targetScrollLeft = pixelPos - (containerWidth / 2) + TRACK_BASE_OFFSET;
        elements.timelineTracks.scrollLeft = Math.max(0, targetScrollLeft);
    }

    updatePlayhead();

    // Sync preview with current position
    if (EditorState.preview) {
        EditorState.preview.setScenes(EditorState.scenes);
        EditorState.preview.seek(EditorState.playbackPosition);
    }
}

/**
 * Select media folder using File System Access API
 */
async function selectMediaFolder() {
    if (!('showDirectoryPicker' in window)) {
        showToast('Folder selection not supported in this browser', 'error');
        return;
    }

    try {
        const dirHandle = await window.showDirectoryPicker();
        EditorState.mediaFolder = dirHandle;

        // Scan for media files
        await scanMediaFiles(dirHandle);

        showToast(`Loaded ${EditorState.mediaFiles.size} media files`, 'success');
        elements.mediaStatus.textContent = `${EditorState.mediaFiles.size} files loaded`;

        // Match files to scenes
        matchMediaToScenes();
        renderTimeline();
    } catch (error) {
        if (error.name !== 'AbortError') {
            console.error('Error selecting folder:', error);
            showToast('Failed to access folder', 'error');
        }
    }
}

/**
 * Scan directory for media files
 */
async function scanMediaFiles(dirHandle, path = '') {
    for await (const entry of dirHandle.values()) {
        if (entry.kind === 'file') {
            const name = entry.name.toLowerCase();
            if (name.match(/\.(jpg|jpeg|png|gif|webp|mp4|webm|mov)$/)) {
                EditorState.mediaFiles.set(entry.name, { handle: entry, path: path });
            }
        } else if (entry.kind === 'directory') {
            await scanMediaFiles(entry, `${path}${entry.name}/`);
        }
    }
}

/**
 * Match media files to scenes
 */
async function matchMediaToScenes() {
    for (const scene of EditorState.scenes) {
        if (!scene.image) continue;

        // Try exact match first
        let fileEntry = EditorState.mediaFiles.get(scene.image);

        // Try without extension
        if (!fileEntry) {
            const baseName = scene.image.replace(/\.[^/.]+$/, '');
            for (const [name, entry] of EditorState.mediaFiles) {
                if (name.toLowerCase().startsWith(baseName.toLowerCase())) {
                    fileEntry = entry;
                    break;
                }
            }
        }

        if (fileEntry) {
            try {
                const file = await fileEntry.handle.getFile();
                scene.mediaUrl = URL.createObjectURL(file);
                scene.mediaLoaded = true;
            } catch (error) {
                console.warn(`Failed to load ${scene.image}:`, error);
            }
        }
    }

    // Hide placeholder if we have media
    if (EditorState.scenes.some(s => s.mediaLoaded)) {
        elements.previewPlaceholder?.classList.add('hidden');
    }

    // Update preview with loaded media
    if (EditorState.preview) {
        EditorState.preview.setScenes(EditorState.scenes);
        EditorState.preview.render();
    }
}

/**
 * Randomize scene media — fetches all asset files per scene from the API,
 * then picks a random file from each scene's own subfolder.
 */
async function randomizeSceneMedia() {
    const projectId = EditorState.project?.id;
    if (!projectId) {
        showToast('No project loaded', 'warning');
        return;
    }

    // Always fetch latest to ensure we see newly added files
    try {
        const resp = await fetch(`/api/animator/project/${encodeURIComponent(projectId)}`);
        if (!resp.ok) throw new Error(resp.status);
        EditorState._assetFilesCache = await resp.json();
    } catch (e) {
        showToast('Failed to load asset files', 'error');
        console.error('Asset fetch error:', e);
        return;
    }

    const assetScenes = EditorState._assetFilesCache.scenes || {};
    let assignedCount = 0;
    const mediaTypeLimit = document.getElementById('randomize-media-type')?.value || 'mixed';

    for (let i = 0; i < EditorState.scenes.length; i++) {
        const scene = EditorState.scenes[i];
        if (scene.type === 'text' || scene.type === 'cta') continue;

        // Find this scene's asset folder using its true index
        const sceneNumber = String(i);
        const sceneAsset = assetScenes[sceneNumber] || assetScenes[String(scene.id)];
        const files = sceneAsset?.files_on_disk;
        if (!files || !files.length) continue;

        // Filter to only image/video files
        const mediaFiles = files.filter(f => {
            const ext = (f.filename || '').split('.').pop().toLowerCase();
            const isImg = IMAGE_EXTENSIONS.includes(ext);
            const isVid = VIDEO_EXTENSIONS.includes(ext);

            if (mediaTypeLimit === 'images' && !isImg) return false;
            if (mediaTypeLimit === 'videos' && !isVid) return false;

            return isImg || isVid;
        });
        if (!mediaFiles.length) continue;

        // Pick a random media file from this scene's asset folder
        const pick = mediaFiles[Math.floor(Math.random() * mediaFiles.length)];

        // Only update if it's different to be efficient
        if (scene.image !== pick.filename || scene.mediaUrl !== pick.url) {
            scene.mediaUrl = pick.url;
            scene.image = pick.filename;
            scene.mediaLoaded = true;

            const isVideo = isVideoFile(pick.filename);
            scene.isVideo = isVideo;

            if (isVideo) {
                // Extract video metadata + thumbnail
                const meta = await getVideoMeta(pick.url);
                if (meta) {
                    scene.videoDuration = meta.duration;
                    scene.videoThumb = meta.thumbDataUrl;
                } else {
                    scene.videoDuration = null;
                    scene.videoThumb = null;
                }
            } else {
                // Clear video flags for image files
                scene.isVideo = false;
                scene.videoDuration = null;
                scene.videoThumb = null;
            }

            // Update DOM thumbnail with correct type info
            updateSceneClipThumb(scene.id, pick.url, isVideo, scene.videoThumb);

            // Clear only this specific scene from preview cache
            if (EditorState.preview) {
                EditorState.preview.imageCache.delete(scene.id);
            }

            assignedCount++;
        }
    }

    if (assignedCount === 0) {
        showToast('No new media assigned', 'info');
        return;
    }

    // Recalculate total duration
    recalculateDuration();

    // Re-sync preview so the new media is preloaded and rendered
    if (EditorState.preview) {
        EditorState.preview.setScenes(EditorState.scenes);
    }

    // Refresh timeline and media grid to show updated thumbnails and video badges
    renderTimeline();
    renderMediaGrid();

    // Record edit action
    recordEdit('Randomize scene media', 'all', 'media', null, null);
    saveProjectEdits();

    // Show summary with image/video counts
    const videoCount = EditorState.scenes.filter(s => s.isVideo).length;
    const imageCount = EditorState.scenes.filter(s => s.mediaUrl && !s.isVideo && s.type !== 'text' && s.type !== 'cta').length;
    const parts = [];
    if (imageCount) parts.push(`${imageCount} image${imageCount > 1 ? 's' : ''}`);
    if (videoCount) parts.push(`${videoCount} video${videoCount > 1 ? 's' : ''}`);
    showToast(`Randomized ${assignedCount} scenes (${parts.join(' + ')})`, 'success');
}

/**
 * Get prepared export data with audio config
 */
function getExportData() {
    console.log('[Editor] getExportData() called');
    console.log('[Editor] Project:', EditorState.project?.id, EditorState.project?.name);
    console.log('[Editor] Scenes:', EditorState.scenes?.length);
    console.log('[Editor] Selected profile:', EditorState.selectedExportProfile);

    // Prepare audio config from voice track
    const voiceTrack = getVoiceTrack();
    const audioConfig = voiceTrack?.loaded ? {
        file: voiceTrack.file,
        path: voiceTrack.path,
        duration: voiceTrack.duration,
        trimmedDuration: voiceTrack.trimmedDuration,
        timelineOffset: voiceTrack.timelineOffset || 0,
        startOffset: voiceTrack.startOffset || 0,
        volume: voiceTrack.volume || 1.0,
        timeline_offset: voiceTrack.timelineOffset || 0,
        start_offset: voiceTrack.startOffset || 0
    } : null;

    // Find first music track for legacy bgMusic export
    const firstMusicTrack = EditorState.audioTracks.find(t => t.type === 'music');

    console.log('[Editor] Audio config:', audioConfig ? { file: audioConfig.file, path: audioConfig.path, dur: audioConfig.duration } : 'none');
    console.log('[Editor] Captions enabled:', EditorState.captionsEnabled, '| entries:', EditorState.captionData?.captions?.length || 0);
    console.log('[Editor] Music tracks:', EditorState.audioTracks.filter(t => t.type === 'music').length);

    // Prepare export data with selected profile and bgMusic
    const profile = EXPORT_PROFILES[EditorState.selectedExportProfile] || EXPORT_PROFILES.yt_shorts;
    console.log('[Editor] Using profile:', profile.id, profile.width + 'x' + profile.height);

    // Deep clone scenes to prevent modifying the state
    let exportScenes = JSON.parse(JSON.stringify(EditorState.scenes));

    // Remove text from scenes if text track is disabled
    if (EditorState.disabledTracks.has('text')) {
        exportScenes = exportScenes.map(s => {
            delete s.text_content;
            return s;
        });
    }

    // Clear scenes if video track is disabled
    if (EditorState.disabledTracks.has('video')) {
        exportScenes = [];
    }

    const data = prepareExportData(
        EditorState.project,
        exportScenes,
        '',
        audioConfig,
        EditorState.captionsEnabled && !EditorState.disabledTracks.has('caption') ? EditorState.captionData : null,
        profile,
        firstMusicTrack || null,
        EditorState.overlays || [],
        EditorState.grainOverlay || null
    );

    console.log('[Editor] Export data prepared:', data.scenes?.length, 'scenes,', data.timeline?.total_duration + 's total');
    return data;
}

/**
 * Preview JSON - Show JSON modal with validation
 */
function previewJson() {
    const exportData = getExportData();

    // Validate export data
    const validation = validateExportData(exportData);

    // Show validation warnings/errors
    if (!validation.valid) {
        showToast(`Export errors: ${validation.errors.join(', ')}`, 'error');
    }

    if (validation.warnings.length > 0) {
        console.warn('Export warnings:', validation.warnings);
        showToast(`Warning: ${validation.warnings[0]}`, 'warning');
    }

    // Tell Vue to render the JSON modal (v-if="visible")
    if (window._vueShowExportJsonModal) {
        window._vueShowExportJsonModal();
    }

    requestAnimationFrame(() => {
        const modal = document.getElementById('export-modal');
        const jsonPre = document.getElementById('export-json');

        if (modal && jsonPre) {
            _bindExportJsonModalInner();
            jsonPre.textContent = JSON.stringify(exportData, null, 2);
        }
    });
}

/**
 * Export MP4 - Show profile selector, then process
 */
async function exportMp4() {
    // Tell Vue to render the modal (v-if="visible")
    if (window._vueShowExportProgressModal) {
        window._vueShowExportProgressModal();
    }

    // Vue renders async — wait one frame for the DOM to exist
    requestAnimationFrame(() => {
        // Re-cache export modal elements (fresh DOM from v-if)
        _refreshExportElements();

        // Bind inner-element listeners (fresh DOM each time)
        _bindExportModalInner();

        // Show profile selector step
        const stepProfile = document.getElementById('export-step-profile');
        const stepProgress = document.getElementById('export-step-progress');
        if (stepProfile) stepProfile.style.display = '';
        if (stepProgress) stepProgress.style.display = 'none';

    });
    return; // Wait for user to click "Export" button
}

/**
 * Actually start the export after profile is selected
 */
let currentJobId = null;

async function startExportWithProfile() {
    console.log('[Editor] startExportWithProfile() — preparing export data');
    const exportData = getExportData();

    // Validate export data
    const validation = validateExportData(exportData);

    if (!validation.valid) {
        console.error('[Editor] Export validation failed:', validation.errors);
        showToast(`Export errors: ${validation.errors.join(', ')}`, 'error');
        return;
    }

    if (validation.warnings.length > 0) {
        console.warn('[Editor] Export warnings:', validation.warnings);
    }

    console.log('[Editor] Validation passed. Switching to progress UI...');

    // Switch to progress step
    const stepProfile = document.getElementById('export-step-profile');
    const stepProgress = document.getElementById('export-step-progress');
    if (stepProfile) stepProfile.style.display = 'none';
    if (stepProgress) stepProgress.style.display = '';

    // Show progress modal
    showExportProgress();

    // Track current job for download
    currentJobId = null;

    console.log('[Editor] Calling exportAPI.startExport()...');

    // Start export
    const jobId = await exportAPI.startExport(
        exportData,
        // Progress callback
        (progress, message) => {
            console.log(`[Editor] Export progress: ${progress}% — ${message}`);
            updateExportProgress(progress, message);
        },
        // Complete callback
        (success, result) => {
            if (success) {
                console.log('[Editor] Export completed! Job:', result.jobId, 'Download:', result.downloadUrl);
                currentJobId = result.jobId;
                showExportComplete(result.downloadUrl);
            } else {
                console.error('[Editor] Export failed:', result.error);
                showExportError(result.error);
            }
        }
    );

    if (!jobId) {
        console.warn('[Editor] Export failed to start (no jobId returned)');
        return;
    }

    console.log('[Editor] Export job started:', jobId);
}

/**
 * Show export progress modal
 */
function showExportProgress() {
    if (elements.exportProgressModal) {
        elements.exportProgressModal.classList.add('active');
        elements.exportProgressModal.classList.remove('export-complete', 'export-error');
    }
    if (elements.exportProgressTitle) {
        const pid = EditorState.project?.id || '';
        elements.exportProgressTitle.textContent = pid ? `Exporting ${pid}...` : 'Exporting Video...';
    }
    if (elements.exportProgressBar) {
        elements.exportProgressBar.style.width = '0%';
    }
    if (elements.exportProgressPercent) {
        elements.exportProgressPercent.textContent = '0%';
    }
    if (elements.exportProgressMessage) {
        elements.exportProgressMessage.textContent = 'Starting export...';
    }
    if (elements.cancelExportBtn) {
        elements.cancelExportBtn.classList.remove('hidden');
    }
    if (elements.previewExportBtn) {
        elements.previewExportBtn.classList.add('hidden');
    }
    if (elements.openExportFolderBtn) {
        elements.openExportFolderBtn.classList.add('hidden');
    }
    if (elements.downloadExportBtn) {
        elements.downloadExportBtn.classList.add('hidden');
    }
}

/**
 * Update export progress
 */
function updateExportProgress(progress, message) {
    if (elements.exportProgressBar) {
        elements.exportProgressBar.style.width = `${progress}%`;
    }
    if (elements.exportProgressPercent) {
        elements.exportProgressPercent.textContent = `${Math.round(progress)}%`;
    }
    if (elements.exportProgressMessage) {
        elements.exportProgressMessage.textContent = message;
    }
}

/**
 * Show export complete state
 */
function showExportComplete(downloadUrl) {
    if (elements.exportProgressModal) {
        elements.exportProgressModal.classList.add('export-complete');
    }
    if (elements.exportProgressTitle) {
        elements.exportProgressTitle.textContent = 'Export Complete!';
    }
    if (elements.exportProgressBar) {
        elements.exportProgressBar.style.width = '100%';
    }
    if (elements.exportProgressPercent) {
        elements.exportProgressPercent.textContent = '100%';
    }
    if (elements.exportProgressMessage) {
        elements.exportProgressMessage.textContent = 'Your video is ready for download';
    }
    if (elements.cancelExportBtn) {
        elements.cancelExportBtn.textContent = 'Close';
        elements.cancelExportBtn.classList.remove('hidden');
    }
    if (elements.previewExportBtn) {
        elements.previewExportBtn.classList.remove('hidden');
    }
    if (elements.openExportFolderBtn) {
        elements.openExportFolderBtn.classList.remove('hidden');
    }
    if (elements.downloadExportBtn) {
        elements.downloadExportBtn.classList.remove('hidden');
    }
    showToast('Export completed!', 'success');
    // Sound check — iframe reads parent's localStorage setting
    if (STS.get('sts-sound-enabled') !== 'false') {
        try { new Audio('/assets/sounds/effects/done.mp3').play(); } catch (_) {}
    }
}

/**
 * Show export error state
 */
function showExportError(error) {
    if (elements.exportProgressModal) {
        elements.exportProgressModal.classList.add('export-error');
    }
    if (elements.exportProgressTitle) {
        elements.exportProgressTitle.textContent = 'Export Failed';
    }
    if (elements.exportProgressMessage) {
        elements.exportProgressMessage.textContent = error || 'An error occurred during export';
    }
    if (elements.cancelExportBtn) {
        elements.cancelExportBtn.textContent = 'Close';
        elements.cancelExportBtn.classList.remove('hidden');
    }
    if (elements.previewExportBtn) {
        elements.previewExportBtn.classList.add('hidden');
    }
    if (elements.openExportFolderBtn) {
        elements.openExportFolderBtn.classList.add('hidden');
    }
    if (elements.downloadExportBtn) {
        elements.downloadExportBtn.classList.add('hidden');
    }
    showToast(`Export failed: ${error}`, 'error');
}

/**
 * Hide export progress modal
 */
function hideExportProgress() {
    if (elements.exportProgressModal) {
        elements.exportProgressModal.classList.remove('active', 'export-complete', 'export-error');
    }
    // Reset cancel button text
    if (elements.cancelExportBtn) {
        elements.cancelExportBtn.textContent = 'Cancel';
    }
    if (window._vueHideExportProgressModal) {
        window._vueHideExportProgressModal();
    }
}

/**
 * Setup export progress modal event listeners
 */
function _refreshExportElements() {
    elements.exportProgressModal = document.getElementById('export-progress-modal');
    elements.exportProgressTitle = document.getElementById('export-progress-title');
    elements.exportProgressBar = document.getElementById('export-progress-bar');
    elements.exportProgressPercent = document.getElementById('export-progress-percent');
    elements.exportProgressMessage = document.getElementById('export-progress-message');
    elements.cancelExportBtn = document.getElementById('cancel-export');
    elements.previewExportBtn = document.getElementById('preview-export');
    elements.openExportFolderBtn = document.getElementById('open-export-folder');
    elements.downloadExportBtn = document.getElementById('download-export');
}

function _bindExportModalInner() {
    // Cancel/Close button - handles both cancelling and closing after error
    elements.cancelExportBtn?.addEventListener('click', async () => {
        const isCloseButton = elements.cancelExportBtn.textContent === 'Close';
        if (isCloseButton) {
            hideExportProgress();
        } else {
            await exportAPI.cancelExport();
            hideExportProgress();
            showToast('Export cancelled', 'info');
        }
    });

    // Download button
    elements.downloadExportBtn?.addEventListener('click', () => {
        if (currentJobId) {
            exportAPI.downloadExport(currentJobId);
        }
    });

    // Preview button
    elements.previewExportBtn?.addEventListener('click', () => {
        if (currentJobId) {
            const url = `${exportAPI.baseUrl}/api/export/${currentJobId}/preview`;
            window.open(url, '_blank');
        }
    });

    // Open Folder button
    elements.openExportFolderBtn?.addEventListener('click', async () => {
        if (currentJobId) {
            try {
                await fetch(`${exportAPI.baseUrl}/api/export/${currentJobId}/open-folder`, { method: 'POST' });
            } catch (e) {
                showToast('Failed to open folder', 'error');
            }
        }
    });

    // Profile card click
    const grid = document.getElementById('export-profile-grid');
    if (grid) {
        grid.querySelectorAll('.export-profile-card').forEach(card => {
            card.addEventListener('click', () => {
                grid.querySelectorAll('.export-profile-card').forEach(c => c.classList.remove('active'));
                card.classList.add('active');
                EditorState.selectedExportProfile = card.dataset.profile;
            });
        });
    }

    // Start export button
    document.getElementById('start-export-btn')?.addEventListener('click', () => {
        startExportWithProfile();
    });

    // Close button
    document.getElementById('close-export-profile')?.addEventListener('click', () => {
        hideExportProgress();
    });

    // Close on backdrop click (only when complete/error)
    elements.exportProgressModal?.addEventListener('click', (e) => {
        if (e.target === elements.exportProgressModal &&
            (elements.exportProgressModal.classList.contains('export-complete') ||
                elements.exportProgressModal.classList.contains('export-error'))) {
            hideExportProgress();
        }
    });
}

function setupExportProgressModal() {
    // Inner listeners are now bound per-open via _bindExportModalInner()
}

function setupExportProfileSelector() {
    // Inner listeners are now bound per-open via _bindExportModalInner()
}

// ---- Background Music ----

function whenMusicPickerReady(callback, attempts = 12) {
    const list = document.getElementById('music-picker-list');
    if (list) {
        callback(list);
        return;
    }
    if (attempts <= 0) return;
    requestAnimationFrame(() => whenMusicPickerReady(callback, attempts - 1));
}

function showMusicPicker() {
    if (typeof window._vueShowMusicPicker === 'function') {
        window._vueShowMusicPicker();
    }

    whenMusicPickerReady(() => {
        const dialog = document.getElementById('music-picker-dialog');
        if (dialog) {
            dialog.classList.remove('hidden');
            dialog.style.display = 'flex';
        }

        fetch('/api/music/library')
            .then(r => r.ok ? r.json() : [])
            .then(files => renderMusicList(files))
            .catch(() => renderMusicList([]));
    });
}

// Expose for inline onclick
window.loadProjectFromServer = loadProjectFromServer;
window.reloadProjectAssets = function () {
    _projectAssetsCache = null;
    _projectAssetsCacheId = null;
    loadProjectAssets();
};

window.openProjectAssetsFolder = async function () {
    const projectId = EditorState.project?.id;
    if (!projectId) { showToast('No project loaded', 'info'); return; }
    try {
        await fetch(`/api/animator/open-folder/${encodeURIComponent(projectId)}/0`, { method: 'POST' });
    } catch (_) { /* ignore */ }
};

window.editorCloseMusicPicker = function () {
    if (typeof window._vueHideMusicPicker === 'function') {
        window._vueHideMusicPicker();
    }
    const dialog = document.getElementById('music-picker-dialog');
    if (dialog) { dialog.classList.add('hidden'); dialog.style.display = ''; }
};

window.editorUploadMusic = async function (input) {
    if (!input.files?.length) return;
    const file = input.files[0];
    const fd = new FormData();
    fd.append('file', file);
    try {
        const res = await fetch('/api/music/upload', { method: 'POST', body: fd });
        if (!res.ok) throw new Error('Upload failed');
        const data = await res.json();
        showToast('Music uploaded', 'success');
        // Refresh list
        const files = await fetch('/api/music/library').then(r => r.json()).catch(() => []);
        renderMusicList(files);
    } catch (e) {
        showToast('Upload failed: ' + e.message, 'error');
    }
    input.value = '';
};

function renderMusicList(files) {
    const list = document.getElementById('music-picker-list');
    if (!list) return;
    const esc = (value) => {
        const div = document.createElement('div');
        div.textContent = String(value ?? '');
        return div.innerHTML;
    };
    if (!files.length) {
        list.innerHTML = '<div style="text-align:center;padding:32px 16px;color:var(--text-muted);font-size:12px"><p>No music files yet</p><p style="font-size:11px;opacity:0.6;margin-top:8px">Built-in music: resources/sounds/music/&lt;folder&gt;/<br>Or upload your own to output/musics/</p></div>';
        return;
    }
    list.innerHTML = files.map((f, index) => `
        <div class="music-picker-item" data-music-index="${index}" style="display:flex;align-items:center;gap:10px;padding:10px 12px;border-radius:8px;cursor:pointer;transition:background 0.12s">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--accent-secondary)" stroke-width="1.5"><circle cx="5.5" cy="17.5" r="2.5"/><circle cx="17.5" cy="15.5" r="2.5"/><path d="M8 17.5V5l12-2v12.5"/></svg>
            <div style="flex:1;min-width:0">
                <div style="font-size:12px;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(f.filename)}</div>
                <div style="font-size:10px;color:var(--text-muted)">${f.duration ? formatTimecode(f.duration) : ''} · ${f.size_mb || '?'}MB</div>
            </div>
        </div>
    `).join('');

    list.querySelectorAll('.music-picker-item').forEach(item => {
        item.addEventListener('mouseenter', () => {
            item.style.background = 'rgba(255,255,255,0.04)';
        });
        item.addEventListener('mouseleave', () => {
            item.style.background = '';
        });
        item.addEventListener('click', () => {
            const index = Number(item.dataset.musicIndex);
            const file = files[index];
            if (!file) return;
            window.selectBgMusic(file.filename, file.path, file.duration || 0);
        });
    });
}

window.selectBgMusic = function (filename, path, duration) {
    // Remove any existing music track to prevent duplicates
    const existingMusic = EditorState.audioTracks.filter(t => t.type === 'music');
    for (const old of existingMusic) {
        if (old.element) { old.element.pause(); old.element.src = ''; }
        EditorState.audioTracks.splice(EditorState.audioTracks.indexOf(old), 1);
    }

    // Create a new music track via the universal audio track system
    const musicTrack = createAudioTrack({
        label: 'Music',
        type: 'music',
        file: filename,
        path: path,
        duration: duration,
        volume: _getSavedVolume('music') ?? 0.08,
        loop: true,
        duckingEnabled: true,
        duckingLevel: getUserDuckingDefault(),
        fadeIn: 2.0,
        fadeOut: 3.0,
        color: AUDIO_TRACK_COLORS.music,
        loaded: true,
    });

    // Create audio element
    const audio = new Audio(path);
    audio.loop = true;
    musicTrack.element = audio;
    ensureTrackGainNode(musicTrack);

    // Update duration when metadata loads
    audio.addEventListener('loadedmetadata', () => {
        musicTrack.duration = audio.duration;
        musicTrack.loaded = true;
        renderAllAudioTracks();
    });

    EditorState.audioTracks.push(musicTrack);
    selectAudioTrack(musicTrack.id);

    // Legacy compat — keep bgMusic/bgMusicElement pointing at latest music track
    EditorState.bgMusic = musicTrack;
    EditorState.bgMusicElement = audio;

    renderAllAudioTracks();
    saveProjectEdits();
    window.editorCloseMusicPicker();
    showToast('Music track added', 'success');
};

/**
 * Auto-select background music based on project story_tone.
 * Only adds music if no music track is already loaded.
 */
async function _autoSelectBgMusic() {
    const tone = EditorState.project?.storyTone;
    const projectId = EditorState.project?.id || '';
    if (!tone) return;
    // Skip if a music track already exists (loaded or still loading)
    if (EditorState.audioTracks.some(t => t.type === 'music')) return;

    try {
        const params = new URLSearchParams({ tone });
        if (projectId) params.set('project_id', projectId);
        const res = await fetch(`/api/music/auto-select?${params.toString()}`);
        if (!res.ok) return;
        const music = await res.json();
        if (!music?.path) return;
        console.log('[Editor] Auto-selected bgMusic:', music.filename, 'for tone:', tone);
        window.selectBgMusic(music.filename, music.path, music.duration || 0);
    } catch (e) {
        console.warn('[Editor] Auto-music selection failed:', e);
    }
}

/**
 * Replace the current music track with a random one from the built-in library.
 *
 * Always pulls from resources/sounds/music/ via /api/music/auto-select — never
 * from user uploads (output/musics/). With story_tone, the picker uses the
 * tone→folder mapping; without tone, it picks fully random across all
 * built-in folders.
 */
async function _replaceMusicTrackRandom(trackId) {
    const tone = EditorState.project?.storyTone || EditorState.project?.story_tone;
    const projectId = EditorState.project?.id || '';
    const params = new URLSearchParams();
    if (tone) params.set('tone', tone);
    if (projectId) params.set('project_id', projectId);
    const url = params.toString()
        ? `/api/music/auto-select?${params.toString()}`
        : '/api/music/auto-select';
    try {
        const res = await fetch(url);
        if (!res.ok) { showToast('Failed to fetch music', 'error'); return; }
        const file = await res.json();
        if (!file?.path) { showToast('No music available', 'error'); return; }

        // Remove old music track first so selectBgMusic can install the new one
        if (trackId) removeAudioTrack(trackId);

        window.selectBgMusic(file.filename || file.file, file.path, file.duration || 0);
        showToast(`Music: ${file.filename || file.file}`, 'success');
    } catch (e) {
        console.error('[Editor] Random music failed:', e);
        showToast('Random music failed', 'error');
    }
}

// Legacy stubs — delegate to universal system
function renderBgMusicTrack() { renderAllAudioTracks(); }

window.removeBgMusic = function () {
    // Remove the first music track
    const musicTrack = EditorState.audioTracks.find(t => t.type === 'music');
    if (musicTrack) removeAudioTrack(musicTrack.id);
};

// ============================================================
// Sound Effects Library (Media panel sub-pane)
// ============================================================

let _sfxPreviewAudio = null;
let _sfxAllFiles = []; // flat list for drag index lookups

function loadSfxLibrary() {
    fetch('/api/sfx/library')
        .then(r => r.ok ? r.json() : { categories: [] })
        .then(data => renderSfxLibrary(data.categories || []))
        .catch(() => renderSfxLibrary([]));
}

function renderSfxLibrary(categories) {
    const list = document.getElementById('sfx-library-list');
    const countEl = document.getElementById('sfx-library-count');
    if (!list) return;

    // Build flat file list for drag references
    _sfxAllFiles = [];
    for (const cat of categories) {
        for (const f of cat.files) _sfxAllFiles.push(f);
    }
    if (countEl) countEl.textContent = String(_sfxAllFiles.length);

    if (!_sfxAllFiles.length) {
        list.innerHTML = '<div class="sfx-library-empty">No sound effects found<br><span>Place .mp3/.wav files in resources/sounds/sfx/</span></div>';
        return;
    }

    let globalIdx = 0;
    list.innerHTML = categories.map((cat, catIdx) => {
        const itemsHtml = cat.files.map(f => {
            const idx = globalIdx++;
            return `<div class="sfx-item" data-sfx-index="${idx}" draggable="true" title="${_sfxEsc(f.label)}">
                <button class="sfx-preview-btn" data-sfx-path="${f.path}" aria-label="Preview">
                    <svg class="sfx-icon-wave" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M2 12h4l3-9 4 18 3-9h4"/>
                    </svg>
                    <svg class="sfx-icon-play" width="12" height="12" viewBox="0 0 24 24" fill="currentColor" stroke="none">
                        <polygon points="5,3 19,12 5,21"/>
                    </svg>
                    <svg class="sfx-icon-stop" width="12" height="12" viewBox="0 0 24 24" fill="currentColor" stroke="none">
                        <rect x="4" y="4" width="16" height="16" rx="2"/>
                    </svg>
                </button>
                <div class="sfx-item-info">
                    <span class="sfx-item-label">${_sfxEsc(f.label)}</span>
                    <span class="sfx-item-meta">${f.duration ? formatTimecode(f.duration) : ''} · ${f.size_kb}KB</span>
                </div>
            </div>`;
        }).join('');

        return `<div class="sfx-category" data-cat="${catIdx}">
            <button class="sfx-category-toggle" aria-expanded="true">
                <svg class="sfx-category-chevron" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg>
                <span class="sfx-category-name">${_sfxEsc(cat.name)}</span>
                <span class="sfx-category-count">${cat.files.length}</span>
            </button>
            <div class="sfx-category-items">${itemsHtml}</div>
        </div>`;
    }).join('');

    // Wire category collapse toggles
    list.querySelectorAll('.sfx-category-toggle').forEach(btn => {
        btn.addEventListener('click', () => {
            const cat = btn.closest('.sfx-category');
            const items = cat.querySelector('.sfx-category-items');
            const expanded = btn.getAttribute('aria-expanded') === 'true';
            btn.setAttribute('aria-expanded', String(!expanded));
            items.style.display = expanded ? 'none' : '';
        });
    });

    // Wire preview buttons
    list.querySelectorAll('.sfx-preview-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const path = btn.dataset.sfxPath;
            const item = btn.closest('.sfx-item');
            const wasPlaying = item.classList.contains('sfx-playing');

            _sfxStopPreview();
            if (wasPlaying) return;

            _sfxPreviewAudio = new Audio(path);
            _sfxPreviewAudio.volume = 0.7;
            item.classList.add('sfx-playing');
            _sfxPreviewAudio.play().catch(() => {});
            _sfxPreviewAudio.addEventListener('ended', () => {
                item.classList.remove('sfx-playing');
                _sfxPreviewAudio = null;
            });
        });
    });

    // Wire drag-start for each item
    list.querySelectorAll('.sfx-item').forEach(item => {
        item.addEventListener('dragstart', (e) => {
            const idx = Number(item.dataset.sfxIndex);
            const f = _sfxAllFiles[idx];
            if (!f) return;
            e.dataTransfer.setData('application/x-sfx', JSON.stringify(f));
            e.dataTransfer.effectAllowed = 'copy';
            item.classList.add('sfx-dragging');
        });
        item.addEventListener('dragend', () => {
            item.classList.remove('sfx-dragging');
        });
    });
}

function _sfxStopPreview() {
    if (_sfxPreviewAudio) {
        _sfxPreviewAudio.pause();
        _sfxPreviewAudio.src = '';
        _sfxPreviewAudio = null;
    }
    document.querySelectorAll('.sfx-playing').forEach(el => el.classList.remove('sfx-playing'));
}

function _sfxEsc(value) {
    const div = document.createElement('div');
    div.textContent = String(value ?? '');
    return div.innerHTML;
}

// Expose for inline onclick in editor-shell HTML
window.loadSfxLibrary = loadSfxLibrary;

// Handle SFX drop onto the timeline (audio tracks or timeline-tracks)
function _initSfxDropZone() {
    // Accept drops on both the audio-tracks-container and the full timeline-tracks area
    const zones = [
        document.getElementById('audio-tracks-container'),
        document.getElementById('timeline-tracks'),
    ].filter(Boolean);

    for (const zone of zones) {
        zone.addEventListener('dragover', (e) => {
            if (e.dataTransfer.types.includes('application/x-sfx')) {
                e.preventDefault();
                e.dataTransfer.dropEffect = 'copy';
                zone.classList.add('sfx-drop-target');
            }
        });
        zone.addEventListener('dragleave', (e) => {
            if (!zone.contains(e.relatedTarget)) {
                zone.classList.remove('sfx-drop-target');
            }
        });
        zone.addEventListener('drop', (e) => {
            zone.classList.remove('sfx-drop-target');
            const raw = e.dataTransfer.getData('application/x-sfx');
            if (!raw) return;
            e.preventDefault();

            let sfx;
            try { sfx = JSON.parse(raw); } catch { return; }

            // Calculate timeline offset from drop X position
            const timelineTracks = document.getElementById('timeline-tracks');
            let dropTime = 0;
            if (timelineTracks) {
                const rect = timelineTracks.getBoundingClientRect();
                const relativeX = e.clientX - rect.left - TRACK_BASE_OFFSET + timelineTracks.scrollLeft;
                dropTime = Math.max(0, pixelsToTime(Math.max(0, relativeX)));
                dropTime = Math.round(dropTime * 1000) / 1000;
            }

            // Check if dropped on an existing FX track lane — add clip to it
            const dropTarget = e.target.closest('[data-audio-track-id]') || e.target.closest('[data-track-id]');
            let targetTrackId = dropTarget?.dataset?.audioTrackId || dropTarget?.dataset?.trackId;
            let targetTrack = targetTrackId ? getAudioTrackById(targetTrackId) : null;

            // Only add to existing SFX tracks (not voice/music)
            if (targetTrack && isSfxTrackType(targetTrack.type)) {
                addClipToFxTrack(targetTrack, sfx, dropTime);
                selectAudioTrack(targetTrack.id);
                renderAllAudioTracks();
                saveProjectEdits();
                showToast(`SFX "${sfx.label || sfx.filename}" added at ${formatTimecode(dropTime)}`, 'success');
                return;
            }

            // Find an existing empty SFX track (no file, no clips) to use
            let emptyFxTrack = EditorState.audioTracks.find(t =>
                isSfxTrackType(t.type) && !t.file && !t.path && (!t.clips || t.clips.length === 0)
            );

            if (emptyFxTrack) {
                addClipToFxTrack(emptyFxTrack, sfx, dropTime);
                selectAudioTrack(emptyFxTrack.id);
                renderAllAudioTracks();
                saveProjectEdits();
                showToast(`SFX "${sfx.label || sfx.filename}" added at ${formatTimecode(dropTime)}`, 'success');
                return;
            }

            // No existing SFX track — create a new multi-clip SFX track
            const fxTrack = createAudioTrack({
                label: 'SFX',
                type: 'sfx',
                volume: _getSavedVolume('sfx') ?? 1.0,
                color: AUDIO_TRACK_COLORS.sfx,
            });
            addClipToFxTrack(fxTrack, sfx, dropTime);
            EditorState.audioTracks.push(fxTrack);
            selectAudioTrack(fxTrack.id);
            renderAllAudioTracks();
            saveProjectEdits();
            showToast(`SFX "${sfx.label || sfx.filename}" added at ${formatTimecode(dropTime)}`, 'success');
        });
    }
}

// Also wire FX track lanes to accept SFX drops after render
function _wireFxTrackDropZones() {
    const container = document.getElementById('audio-tracks-container');
    if (!container) return;
    container.querySelectorAll('.fx-multi-clip-lane, .audio-track-empty-target').forEach(lane => {
        lane.addEventListener('dragover', (e) => {
            if (e.dataTransfer.types.includes('application/x-sfx')) {
                e.preventDefault();
                e.dataTransfer.dropEffect = 'copy';
            }
        });
    });
}

// Load SFX library on editor init
setTimeout(() => {
    loadSfxLibrary();
    _initSfxDropZone();
}, 500);

/**
 * Check if there are unsaved changes (edits since last save/load)
 */
function hasUnsavedChanges() {
    // Check if we have a project loaded
    if (!EditorState.project?.id) return false;

    // Check if there are any edits in history
    if (EditorState.editHistory.length > 0) return true;

    // Check if scenes have been modified from original
    if (EditorState.scenes.length !== EditorState.originalScenes.length) return true;

    // Compare current scenes with original
    for (let i = 0; i < EditorState.scenes.length; i++) {
        const current = EditorState.scenes[i];
        const original = EditorState.originalScenes[i];
        if (!original) return true;

        // Check key editable properties
        if (current.duration !== original.duration ||
            current.visual_fx !== original.visual_fx ||
            current.text_content !== original.text_content ||
            current.text_color !== original.text_color ||
            current.text_size !== original.text_size ||
            current.font_family !== original.font_family ||
            current.font_style !== original.font_style ||
            current.text_align !== original.text_align ||
            current.vertical_align !== original.vertical_align ||
            current.text_x !== original.text_x ||
            current.text_y !== original.text_y ||
            current.text_timeline_offset !== original.text_timeline_offset ||
            current.text_overlay_duration !== original.text_overlay_duration ||
            !!current.text_background_enabled !== !!original.text_background_enabled ||
            (current.text_background_color || '#000000') !== (original.text_background_color || '#000000')) {
            return true;
        }
    }

    return false;
}

/**
 * Setup beforeunload warning to prevent accidental window close
 */
function setupBeforeUnloadWarning() {
    window.addEventListener('beforeunload', (e) => {
        // Only warn if there's a project with potential changes
        if (EditorState.project?.id && hasUnsavedChanges()) {
            // Standard way to trigger browser's "Leave site?" dialog
            e.preventDefault();
            // Some browsers require returnValue to be set
            e.returnValue = '';
            return '';
        }
    });
}

function _closeExportJsonModal() {
    document.getElementById('export-modal')?.classList.remove('active');
    if (window._vueHideExportJsonModal) {
        window._vueHideExportJsonModal();
    }
}

function _bindExportJsonModalInner() {
    const modal = document.getElementById('export-modal');
    const closeBtn = document.getElementById('close-export-modal');
    const copyBtn = document.getElementById('copy-export-json');
    const downloadBtn = document.getElementById('download-export-json');
    const jsonPre = document.getElementById('export-json');

    closeBtn?.addEventListener('click', _closeExportJsonModal);

    modal?.addEventListener('click', (e) => {
        if (e.target === modal) _closeExportJsonModal();
    });

    copyBtn?.addEventListener('click', async () => {
        const json = jsonPre?.textContent || '';
        try {
            await navigator.clipboard.writeText(json);
            showToast('JSON copied to clipboard', 'success');
        } catch (err) {
            showToast('Failed to copy', 'error');
        }
    });

    downloadBtn?.addEventListener('click', () => {
        const json = jsonPre?.textContent || '';
        const blob = new Blob([json], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${EditorState.project?.id || 'export'}_timeline.json`;
        a.click();
        URL.revokeObjectURL(url);
        showToast('JSON downloaded', 'success');
    });

}

function setupExportModal() {
    // Inner listeners are now bound per-open via _bindExportJsonModalInner()
}

// ---- Effects Tab ----

function setupEffectsTab() {
    const grid = document.getElementById('fx-grid');
    if (!grid) return;

    // Click on effect cards — apply to selected scene, or all scenes if none selected
    const fxCardGrid = document.getElementById('fx-card-grid');
    grid.querySelectorAll('.fx-card[data-fx]').forEach(card => {
        card.addEventListener('click', (e) => {
            // Toggle pool membership if clicking the pool dot
            if (e.target.closest('.fx-pool-dot')) {
                card.classList.toggle('in-pool');
                return;
            }
            const newValue = card.dataset.fx;
            const scene = EditorState.selectedScene;
            if (scene && scene.type !== 'text' && scene.type !== 'cta') {
                // Apply to selected scene
                const oldValue = scene.visual_fx;
                scene.visual_fx = newValue;
                recordEdit(`Change effect (Scene ${scene.id})`, scene.id, 'visual_fx', oldValue, newValue);
            } else {
                // No scene selected — apply to ALL non-text scenes
                EditorState.scenes.forEach(s => {
                    if (s.type === 'text' || s.type === 'cta') return;
                    const old = s.visual_fx;
                    s.visual_fx = newValue;
                    if (old !== newValue) recordEdit(`Set effect (Scene ${s.id})`, s.id, 'visual_fx', old, newValue);
                });
                saveProjectEdits();
                showToast(`Applied "${newValue}" to all scenes`, 'success');
            }
            updateEffectsTab();
            renderSceneProperties();
        });
    });

    // Toggle pool-mode on randomize button click
    const fxRandomBtn = document.getElementById('fx-random-assign');
    let fxPoolMode = false;

    // Auto-assign all
    document.getElementById('fx-auto-assign')?.addEventListener('click', () => {
        if (!EditorState.scenes.length) return;

        const roleEffects = {
            hook: ['zoom_in', 'ken_burns'], buildup: ['pan_right', 'pan_left', 'pan_diagonal_br', 'zoom_in'],
            peak: ['shake', 'zoom_in', 'ken_burns'], transition: ['fade', 'zoom_out', 'pan_up'],
            final: ['zoom_out', 'pan_diagonal_tl'], final_statement: ['zoom_out'], cta: ['static'],
        };
        let lastEffect = '';

        EditorState.scenes.forEach(scene => {
            const old = scene.visual_fx;
            if (scene.type === 'text' || scene.type === 'cta') {
                scene.visual_fx = 'static';
            } else {
                const role = scene.narrative_role || scene.scene_type || scene.type || 'buildup';
                const candidates = roleEffects[role] || ['zoom_in', 'pan_right', 'zoom_out'];
                let fx = candidates[0];
                for (const c of candidates) { if (c !== lastEffect) { fx = c; break; } }
                lastEffect = fx;
                scene.visual_fx = fx;
            }
            if (old !== scene.visual_fx) {
                recordEdit(`Auto effect (Scene ${scene.id})`, scene.id, 'visual_fx', old, scene.visual_fx);
            }
        });

        updateEffectsTab();
        renderSceneProperties();
        saveProjectEdits();
        showToast('Effects auto-assigned', 'success');
    });

    // Random-assign toggle: first click enters pool selection, second click applies
    fxRandomBtn?.addEventListener('click', () => {
        if (!EditorState.scenes.length) return;

        if (!fxPoolMode) {
            // Enter pool selection mode — show dots, select all by default
            fxPoolMode = true;
            fxCardGrid.classList.add('pool-mode');
            fxRandomBtn.classList.add('pool-active');
            fxRandomBtn.querySelector('.fx-btn-label').textContent = 'Apply';
            // Select all non-static effects by default
            fxCardGrid.querySelectorAll('.fx-card[data-fx]').forEach(c => {
                if (c.dataset.fx !== 'static') c.classList.add('in-pool');
            });
        } else {
            // Apply randomization from pool, then exit
            const poolFx = Array.from(fxCardGrid.querySelectorAll('.fx-card.in-pool[data-fx]'))
                .map(c => c.dataset.fx);

            if (!poolFx.length) {
                showToast('No effects selected — click dots to pick effects', 'info');
                return;
            }

            let lastFx = '';
            EditorState.scenes.forEach(scene => {
                const old = scene.visual_fx;
                if (scene.type === 'text' || scene.type === 'cta') {
                    scene.visual_fx = 'static';
                } else {
                    let fx;
                    do { fx = poolFx[Math.floor(Math.random() * poolFx.length)]; } while (fx === lastFx && poolFx.length > 1);
                    lastFx = fx;
                    scene.visual_fx = fx;
                }
                if (old !== scene.visual_fx) {
                    recordEdit(`Random effect (Scene ${scene.id})`, scene.id, 'visual_fx', old, scene.visual_fx);
                }
            });

            // Exit pool mode
            fxPoolMode = false;
            fxCardGrid.classList.remove('pool-mode');
            fxRandomBtn.classList.remove('pool-active');
            fxRandomBtn.querySelector('.fx-btn-label').textContent = 'Randomize';
            fxCardGrid.querySelectorAll('.fx-card').forEach(c => c.classList.remove('in-pool'));

            updateEffectsTab();
            renderSceneProperties();
            saveProjectEdits();
            showToast(`Effects randomized (${poolFx.length} in pool)`, 'success');
        }
    });
}

function updateEffectsTab() {
    const noScene = document.getElementById('fx-no-scene');
    const grid = document.getElementById('fx-grid');
    if (!noScene || !grid) return;

    const scene = EditorState.selectedScene;
    const hasScene = scene && scene.type !== 'text' && scene.type !== 'cta';

    // Always show the grid so randomize/auto-assign are accessible
    noScene.style.display = 'none';
    grid.style.display = 'flex';

    // Highlight active effect only when a scene is selected
    const activeFx = hasScene ? (scene.visual_fx || 'static') : null;
    grid.querySelectorAll('.fx-card[data-fx]').forEach(card => {
        card.classList.toggle('active', activeFx !== null && card.dataset.fx === activeFx);
    });
}

// ---- Transitions Tab ----

function setupTransitionsTab() {
    const grid = document.getElementById('tr-grid');
    if (!grid) return;

    const durationRow = document.getElementById('tr-duration-row');
    const durationSlider = document.getElementById('tr-duration-slider');
    const durationValue = document.getElementById('tr-duration-value');

    // Click on transition cards — apply to selected scene, or toggle pool if clicking the dot
    const trCardGrid = document.getElementById('tr-card-grid');
    grid.querySelectorAll('.fx-card[data-tr]').forEach(card => {
        card.addEventListener('click', (e) => {
            if (e.target.closest('.fx-pool-dot')) {
                card.classList.toggle('in-pool');
                return;
            }
            const scene = EditorState.selectedScene;
            if (!scene) return;

            const type = card.dataset.tr;
            const oldTr = scene.transition ? JSON.stringify(scene.transition) : 'none';
            const TRANSITION_DURATIONS = { cut: 0, none: 0, crossfade: 0.3, fade_black: 0.4, fade_white: 0.4, slide_left: 0.4, slide_right: 0.4, slide_up: 0.4, slide_down: 0.4, wipe_left: 0.4, wipe_right: 0.4, zoom_in: 0.5, zoom_out: 0.5 };
            let duration = TRANSITION_DURATIONS[type] || 0;

            scene.transition = { type, duration };
            recordEdit(`Change transition (Scene ${scene.id})`, scene.id, 'transition', oldTr, JSON.stringify(scene.transition));
            updateTransitionsTab();
        });
    });

    // Toggle pool-mode on randomize button click
    const trRandomBtn = document.getElementById('tr-random-assign');
    let trPoolMode = false;

    // Duration slider
    durationSlider?.addEventListener('input', (e) => {
        const scene = EditorState.selectedScene;
        if (!scene || !scene.transition) return;

        const val = parseFloat(e.target.value);
        scene.transition.duration = val;
        if (durationValue) durationValue.textContent = val.toFixed(1) + 's';
    });

    // Auto-assign all
    document.getElementById('tr-auto-assign')?.addEventListener('click', () => {
        if (!EditorState.scenes.length) return;

        EditorState.scenes.forEach((scene, i) => {
            const old = scene.transition ? JSON.stringify(scene.transition) : 'none';
            if (i >= EditorState.scenes.length - 1) {
                scene.transition = { type: 'none', duration: 0 };
            } else {
                const role = scene.narrative_role || scene.scene_type || scene.type || 'buildup';
                switch (role) {
                    case 'hook': case 'peak':
                        scene.transition = { type: 'cut', duration: 0 }; break;
                    case 'text': case 'cta':
                        scene.transition = { type: 'fade_black', duration: 0.4 }; break;
                    case 'transition': case 'final': case 'final_statement':
                        scene.transition = { type: 'crossfade', duration: 0.5 }; break;
                    default:
                        scene.transition = { type: 'crossfade', duration: 0.3 }; break;
                }
            }
            if (old !== JSON.stringify(scene.transition)) {
                recordEdit(`Auto transition (Scene ${scene.id})`, scene.id, 'transition', old, JSON.stringify(scene.transition));
            }
        });

        updateTransitionsTab();
        showToast('Transitions auto-assigned', 'success');
    });

    // Random-assign toggle: first click enters pool selection, second click applies
    trRandomBtn?.addEventListener('click', () => {
        if (!EditorState.scenes.length) return;

        if (!trPoolMode) {
            // Enter pool selection mode
            trPoolMode = true;
            trCardGrid.classList.add('pool-mode');
            trRandomBtn.classList.add('pool-active');
            trRandomBtn.querySelector('.fx-btn-label').textContent = 'Apply';
            // Select all non-none transitions by default
            trCardGrid.querySelectorAll('.fx-card[data-tr]').forEach(c => {
                if (c.dataset.tr !== 'none') c.classList.add('in-pool');
            });
        } else {
            // Apply randomization from pool, then exit
            const poolTr = Array.from(trCardGrid.querySelectorAll('.fx-card.in-pool[data-tr]'))
                .map(c => c.dataset.tr);

            if (!poolTr.length) {
                showToast('No transitions selected — click dots to pick transitions', 'info');
                return;
            }

            const durations = { cut: 0, crossfade: 0.3, fade_black: 0.4, fade_white: 0.4, slide_left: 0.4, slide_right: 0.4, slide_up: 0.4, slide_down: 0.4, wipe_left: 0.4, wipe_right: 0.4, zoom_in: 0.5, zoom_out: 0.5 };
            let lastTr = '';

            EditorState.scenes.forEach((scene, i) => {
                const old = scene.transition ? JSON.stringify(scene.transition) : 'none';
                if (i >= EditorState.scenes.length - 1) {
                    scene.transition = { type: 'none', duration: 0 };
                } else {
                    let tr;
                    do { tr = poolTr[Math.floor(Math.random() * poolTr.length)]; } while (tr === lastTr && poolTr.length > 1);
                    lastTr = tr;
                    scene.transition = { type: tr, duration: durations[tr] || 0 };
                }
                if (old !== JSON.stringify(scene.transition)) {
                    recordEdit(`Random transition (Scene ${scene.id})`, scene.id, 'transition', old, JSON.stringify(scene.transition));
                }
            });

            // Exit pool mode
            trPoolMode = false;
            trCardGrid.classList.remove('pool-mode');
            trRandomBtn.classList.remove('pool-active');
            trRandomBtn.querySelector('.fx-btn-label').textContent = 'Randomize';
            trCardGrid.querySelectorAll('.fx-card').forEach(c => c.classList.remove('in-pool'));

            updateTransitionsTab();
            showToast(`Transitions randomized (${poolTr.length} in pool)`, 'success');
        }
    });
}

function updateTransitionsTab() {
    const noScene = document.getElementById('tr-no-scene');
    const grid = document.getElementById('tr-grid');
    if (!noScene || !grid) return;

    const scene = EditorState.selectedScene;

    // Always show the grid so randomize/auto-assign are accessible
    noScene.style.display = 'none';
    grid.style.display = 'flex';

    // Highlight active transition only when a scene is selected
    const tr = scene ? (scene.transition || { type: 'none', duration: 0 }) : null;
    grid.querySelectorAll('.fx-card[data-tr]').forEach(card => {
        card.classList.toggle('active', tr !== null && card.dataset.tr === tr.type);
    });

    // Show/hide duration slider
    const durationRow = document.getElementById('tr-duration-row');
    const durationSlider = document.getElementById('tr-duration-slider');
    const durationValue = document.getElementById('tr-duration-value');

    const hasDuration = tr && tr.type !== 'none' && tr.type !== 'cut';
    if (durationRow) durationRow.style.display = hasDuration ? 'flex' : 'none';
    if (hasDuration && durationSlider) {
        durationSlider.value = tr.duration || 0.3;
        if (durationValue) durationValue.textContent = (tr.duration || 0.3).toFixed(1) + 's';
    }
}

// ============================================================
// Overlays Tab (global — applies to entire timeline)
// ============================================================

let _overlaysList = null;

/**
 * Select an overlay from the stack for the detail panel
 */
function selectOverlay(idx) {
    const stack = EditorState.overlays || [];
    if (idx < 0 || idx >= stack.length) return;

    // Deselect everything else
    EditorState.selectedScene = null;
    EditorState.selectedTextOverlaySceneId = null;
    EditorState.selectedAudioTrack = null;
    EditorState.selectedCaptionIdx = null;
    document.querySelectorAll('.scene-clip.selected').forEach(el => el.classList.remove('selected'));
    document.querySelectorAll('.text-clip.selected').forEach(el => el.classList.remove('selected'));
    document.querySelectorAll('.audio-clip-universal.selected').forEach(el => el.classList.remove('selected'));
    document.querySelectorAll('.caption-clip.selected').forEach(el => el.classList.remove('selected'));

    EditorState.selectedOverlayIdx = idx;
    renderOverlayProperties();
}

/**
 * Render overlay properties in the detail panel
 */
function renderOverlayProperties() {
    if (!elements.sceneProperties) return;
    const idx = EditorState.selectedOverlayIdx;
    const stack = EditorState.overlays || [];
    if (idx == null || idx < 0 || idx >= stack.length) return;

    const ov = stack[idx];
    const getName = (url) => {
        const match = _overlaysList?.find(o => o.url === url);
        return match ? match.name : url.split('/').pop().replace(/\.\w+$/, '');
    };
    const esc = (s) => s.replace(/</g, '&lt;');
    const name = getName(ov.url);
    const opVal = Math.round(ov.opacity * 100);

    const blendOptions = OVERLAY_BLEND_MODES.map(m => {
        const label = m === 'soft-light' ? 'Soft Light' : m === 'hard-light' ? 'Hard Light'
            : m === 'color-dodge' ? 'Color Dodge' : m.charAt(0).toUpperCase() + m.slice(1);
        return `<option value="${m}"${m === (ov.blend || 'normal') ? ' selected' : ''}>${label}</option>`;
    }).join('');

    elements.sceneProperties.innerHTML = `
        <div class="caption-props-header">
            <span class="caption-props-icon" style="background:rgba(99,102,241,0.15);color:rgba(99,102,241,0.9)">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="2" width="20" height="20" rx="3"/><path d="M2 12h20M12 2v20" opacity="0.4"/></svg>
            </span>
            <span class="caption-props-title">Overlay ${idx + 1} / ${stack.length}</span>
        </div>
        <div class="property-group">
            <label>Name</label>
            <span class="property-value">${esc(name)}</span>
        </div>
        <div class="property-group">
            <label>Z-Order</label>
            <span class="property-value">${idx + 1} (${idx === 0 ? 'bottom' : idx === stack.length - 1 ? 'top' : 'middle'})</span>
        </div>
        <div class="property-group property-stack">
            <label>Opacity</label>
            <div class="ov-detail-slider-row">
                <input type="range" id="ov-detail-opacity" min="0" max="100" step="1" value="${opVal}" />
                <span id="ov-detail-opacity-val" class="ov-stack-val">${opVal}%</span>
            </div>
        </div>
        <div class="property-group property-stack">
            <label>Blend Mode</label>
            <select id="ov-detail-blend" class="ov-detail-select">${blendOptions}</select>
        </div>
        <div style="padding-top:8px">
            <button class="ov-detail-remove" id="ov-detail-remove">Remove Overlay</button>
        </div>
    `;

    // Bind opacity
    const opSlider = document.getElementById('ov-detail-opacity');
    const opValEl = document.getElementById('ov-detail-opacity-val');
    if (opSlider) {
        opSlider.addEventListener('input', () => {
            const v = parseInt(opSlider.value, 10);
            if (opValEl) opValEl.textContent = v + '%';
            stack[idx].opacity = v / 100;
            if (EditorState.preview) EditorState.preview.setOverlay(stack);
        });
        opSlider.addEventListener('change', () => saveProjectEdits());
    }

    // Bind blend
    const blendSel = document.getElementById('ov-detail-blend');
    if (blendSel) {
        blendSel.addEventListener('change', () => {
            stack[idx].blend = blendSel.value;
            if (EditorState.preview) EditorState.preview.setOverlay(stack);
            saveProjectEdits();
        });
    }

    // Bind remove
    const removeBtn = document.getElementById('ov-detail-remove');
    if (removeBtn) {
        removeBtn.addEventListener('click', () => {
            EditorState.overlays.splice(idx, 1);
            EditorState.selectedOverlayIdx = null;
            updateOverlaysTab();
            if (EditorState.preview) {
                EditorState.preview.setOverlay(EditorState.overlays.length ? EditorState.overlays : null);
            }
            saveProjectEdits();
            renderSceneProperties();
        });
    }
}

async function setupOverlaysTab() {
    const grid = document.getElementById('ov-grid');
    if (!grid) return;
    EditorState.grainOverlay = normalizeGrainOverlay(EditorState.grainOverlay);

    // Fetch available overlays from server
    try {
        const res = await fetch('/api/editor/overlays');
        if (res.ok) _overlaysList = await res.json();
    } catch { /* ignore */ }
    if (!_overlaysList) _overlaysList = [];

    // Build cards: "None" + each overlay with preview thumbnail
    const cardGrid = document.getElementById('ov-card-grid');
    if (!cardGrid) return;

    let html = `<button class="overlay-card" data-overlay="">
        <div class="overlay-card-preview">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                <path d="M18 6L6 18M6 6l12 12"/>
            </svg>
        </div>
        <span class="overlay-card-label">None</span>
    </button>`;

    for (const ov of _overlaysList) {
        const esc = (s) => s.replace(/"/g, '&quot;').replace(/</g, '&lt;');
        html += `<button class="overlay-card" data-overlay="${esc(ov.url)}" title="${esc(ov.name)}">
            <div class="overlay-card-preview">
                <img src="${esc(ov.url)}" alt="${esc(ov.name)}" loading="lazy">
                <span class="ov-eye-btn" data-bg="0" title="Preview on different backgrounds">
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                </span>
                <span class="ov-expand-btn" title="Preview larger">
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></svg>
                </span>
            </div>
            <span class="overlay-card-label">${esc(ov.name)}</span>
        </button>`;
    }
    cardGrid.innerHTML = html;

    // Eye icon — cycle preview background: dark → white → grey → dark
    const _ovBgColors = ['', '#ffffff', '#808080'];
    cardGrid.querySelectorAll('.ov-eye-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            let idx = (parseInt(btn.dataset.bg, 10) + 1) % _ovBgColors.length;
            btn.dataset.bg = idx;
            const preview = btn.closest('.overlay-card-preview');
            if (preview) preview.style.background = _ovBgColors[idx] || '';
        });
    });

    // Expand button — show overlay in a lightbox
    cardGrid.querySelectorAll('.ov-expand-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const card = btn.closest('.overlay-card');
            const url = card?.dataset.overlay;
            if (!url) return;
            const name = card?.getAttribute('title') || '';
            showOverlayLightbox(url, name);
        });
    });

    // Click handler — toggle overlay in/out of stack, or select for detail pane
    cardGrid.querySelectorAll('.overlay-card[data-overlay]').forEach(card => {
        card.addEventListener('click', () => {
            const url = card.dataset.overlay || null;
            const oldStack = [...EditorState.overlays];

            if (!url) {
                // "None" card — clear all
                EditorState.overlays = [];
                EditorState.selectedOverlayIdx = null;
            } else {
                const idx = findOverlayIdx(url);
                if (idx >= 0) {
                    // Already active — select it for the detail pane
                    selectOverlay(idx);
                    return;
                } else {
                    // Add to top of stack and select it
                    EditorState.overlays.push(normalizeOverlayEntry(url));
                    selectOverlay(EditorState.overlays.length - 1);
                }
            }

            recordEdit(
                EditorState.overlays.length ? `Set ${EditorState.overlays.length} overlay(s)` : 'Remove overlays',
                null, 'overlays', oldStack, [...EditorState.overlays]
            );
            updateOverlaysTab();

            // Update preview
            if (EditorState.preview) {
                EditorState.preview.setOverlay(EditorState.overlays.length ? EditorState.overlays : null);
            }
        });
    });

    // Show grid immediately (no scene selection needed)
    grid.style.display = '';
    const noScene = document.getElementById('ov-no-scene');
    if (noScene) noScene.style.display = 'none';

    setupGrainControls();
    updateOverlaysTab();
}

function updateOverlaysTab() {
    const grid = document.getElementById('ov-grid');
    if (!grid) return;

    const stack = EditorState.overlays || [];

    // Update stack count label
    const countEl = document.getElementById('ov-stack-count');
    if (countEl) countEl.textContent = stack.length ? `${stack.length} active` : '0 active';

    grid.querySelectorAll('.overlay-card[data-overlay]').forEach(card => {
        const url = card.dataset.overlay;
        const idx = url ? findOverlayIdx(url) : -1;
        card.classList.toggle('active', idx >= 0);

        // Remove old badge
        card.querySelector('.overlay-z-badge')?.remove();

        // Add z-order badge (1-based, 1 = bottom)
        if (idx >= 0) {
            const badge = document.createElement('span');
            badge.className = 'overlay-z-badge';
            badge.textContent = idx + 1;
            card.querySelector('.overlay-card-preview').appendChild(badge);
        }
    });

    syncGrainControlsUI();
}

function showOverlayLightbox(url, name) {
    let lb = document.getElementById('ov-lightbox');
    if (!lb) {
        lb = document.createElement('div');
        lb.id = 'ov-lightbox';
        lb.className = 'ov-lightbox';
        lb.innerHTML = `
            <div class="ov-lightbox-backdrop"></div>
            <div class="ov-lightbox-content">
                <img class="ov-lightbox-img" src="" alt="">
                <div class="ov-lightbox-footer">
                    <span class="ov-lightbox-name"></span>
                    <div class="ov-lightbox-bg-btns">
                        <button class="ov-lightbox-bg-btn active" data-bg="" title="Dark">
                            <span style="background:#0d0d14"></span>
                        </button>
                        <button class="ov-lightbox-bg-btn" data-bg="#ffffff" title="White">
                            <span style="background:#ffffff"></span>
                        </button>
                        <button class="ov-lightbox-bg-btn" data-bg="#808080" title="Grey">
                            <span style="background:#808080"></span>
                        </button>
                    </div>
                </div>
                <button class="ov-lightbox-close" title="Close">&times;</button>
            </div>`;
        document.body.appendChild(lb);
        lb.querySelector('.ov-lightbox-backdrop').addEventListener('click', () => lb.classList.remove('active'));
        lb.querySelector('.ov-lightbox-close').addEventListener('click', () => lb.classList.remove('active'));
        lb.querySelectorAll('.ov-lightbox-bg-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                lb.querySelectorAll('.ov-lightbox-bg-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                lb.querySelector('.ov-lightbox-img').style.background = btn.dataset.bg || '';
            });
        });
    }
    const img = lb.querySelector('.ov-lightbox-img');
    img.src = url;
    img.alt = name;
    img.style.background = '';
    lb.querySelector('.ov-lightbox-name').textContent = name;
    lb.querySelectorAll('.ov-lightbox-bg-btn').forEach(b => b.classList.toggle('active', !b.dataset.bg));
    lb.classList.add('active');
}

function setupGrainControls() {
    const enabled = document.getElementById('grain-enabled');
    const opacity = document.getElementById('grain-opacity');
    const fadeIn = document.getElementById('grain-fade-in');
    const hold = document.getElementById('grain-hold');
    const fadeOut = document.getElementById('grain-fade-out');
    if (!enabled || !opacity || !fadeIn || !hold || !fadeOut) return;

    if (enabled.dataset.bound === '1') return;
    enabled.dataset.bound = '1';

    const readCfg = () => normalizeGrainOverlay({
        enabled: enabled.checked,
        opacity: parseFloat(opacity.value),
        fade_in: parseFloat(fadeIn.value),
        hold: parseFloat(hold.value),
        fade_out: parseFloat(fadeOut.value)
    });
    const liveUpdate = () => {
        EditorState.grainOverlay = readCfg();
        syncGrainControlsUI();
    };
    const commitUpdate = () => {
        const oldCfg = normalizeGrainOverlay(EditorState.grainOverlay);
        const nextCfg = readCfg();
        EditorState.grainOverlay = nextCfg;
        syncGrainControlsUI();
        recordEdit('Update grain overlay', 'project', 'grain_overlay', oldCfg, nextCfg);
        saveProjectEdits();
    };

    enabled.addEventListener('change', commitUpdate);
    opacity.addEventListener('input', liveUpdate);
    fadeIn.addEventListener('input', liveUpdate);
    hold.addEventListener('input', liveUpdate);
    fadeOut.addEventListener('input', liveUpdate);
    opacity.addEventListener('change', commitUpdate);
    fadeIn.addEventListener('change', commitUpdate);
    hold.addEventListener('change', commitUpdate);
    fadeOut.addEventListener('change', commitUpdate);

    syncGrainControlsUI();
}

function syncGrainControlsUI() {
    const cfg = normalizeGrainOverlay(EditorState.grainOverlay);
    const enabled = document.getElementById('grain-enabled');
    const opacity = document.getElementById('grain-opacity');
    const fadeIn = document.getElementById('grain-fade-in');
    const hold = document.getElementById('grain-hold');
    const fadeOut = document.getElementById('grain-fade-out');
    const vOpacity = document.getElementById('grain-opacity-val');
    const vFadeIn = document.getElementById('grain-fade-in-val');
    const vHold = document.getElementById('grain-hold-val');
    const vFadeOut = document.getElementById('grain-fade-out-val');
    if (!enabled || !opacity || !fadeIn || !hold || !fadeOut) return;

    enabled.checked = !!cfg.enabled;
    opacity.value = cfg.opacity.toFixed(2);
    fadeIn.value = cfg.fade_in.toFixed(2);
    hold.value = cfg.hold.toFixed(2);
    fadeOut.value = cfg.fade_out.toFixed(2);

    if (vOpacity) vOpacity.textContent = cfg.opacity.toFixed(2);
    if (vFadeIn) vFadeIn.textContent = cfg.fade_in.toFixed(2);
    if (vHold) vHold.textContent = cfg.hold.toFixed(2);
    if (vFadeOut) vFadeOut.textContent = cfg.fade_out.toFixed(2);
}

/**
 * Handle keyboard shortcuts
 */
function handleKeyboard(e) {
    // Space - Play/Pause
    if (e.code === 'Space' && !e.target.matches('input, textarea, [contenteditable="true"]')) {
        e.preventDefault();
        togglePlayback();
    }

    // Shift+Left/Right - Frame step (1/30s)
    if (e.code === 'ArrowLeft' && e.shiftKey) {
        e.preventDefault();
        EditorState.playbackPosition = Math.max(0, EditorState.playbackPosition - 1 / 30);
        if (EditorState.preview) {
            EditorState.preview.seek(EditorState.playbackPosition);
        }
        seekAudio(EditorState.playbackPosition);
        updateTimeScrubber();
        updatePlayhead();
    }
    if (e.code === 'ArrowRight' && e.shiftKey) {
        e.preventDefault();
        EditorState.playbackPosition = Math.min(
            EditorState.project.totalDuration,
            EditorState.playbackPosition + 1 / 30
        );
        if (EditorState.preview) {
            EditorState.preview.seek(EditorState.playbackPosition);
        }
        seekAudio(EditorState.playbackPosition);
        updateTimeScrubber();
        updatePlayhead();
    }

    // Left/Right - Seek (1s, without Shift)
    if (e.code === 'ArrowLeft' && !e.shiftKey) {
        EditorState.playbackPosition = Math.max(0, EditorState.playbackPosition - 1);
        if (EditorState.preview) {
            EditorState.preview.seek(EditorState.playbackPosition);
        }
        seekAudio(EditorState.playbackPosition);
        updateTimeScrubber();
        updatePlayhead();
    }
    if (e.code === 'ArrowRight' && !e.shiftKey) {
        EditorState.playbackPosition = Math.min(
            EditorState.project.totalDuration,
            EditorState.playbackPosition + 1
        );
        if (EditorState.preview) {
            EditorState.preview.seek(EditorState.playbackPosition);
        }
        seekAudio(EditorState.playbackPosition);
        updateTimeScrubber();
        updatePlayhead();
    }

    // J - Step back 5s
    if (e.code === 'KeyJ' && !e.target.matches('input, textarea, [contenteditable="true"]')) {
        e.preventDefault();
        EditorState.playbackPosition = Math.max(0, EditorState.playbackPosition - 5);
        if (EditorState.preview) {
            EditorState.preview.seek(EditorState.playbackPosition);
        }
        seekAudio(EditorState.playbackPosition);
        updateTimeScrubber();
        updatePlayhead();
    }

    // K - Pause
    if (e.code === 'KeyK' && !e.target.matches('input, textarea, [contenteditable="true"]')) {
        e.preventDefault();
        if (EditorState.isPlaying) {
            togglePlayback();
        }
    }

    // L - Step forward 5s
    if (e.code === 'KeyL' && !e.target.matches('input, textarea, [contenteditable="true"]')) {
        e.preventDefault();
        EditorState.playbackPosition = Math.min(
            EditorState.project.totalDuration,
            EditorState.playbackPosition + 5
        );
        if (EditorState.preview) {
            EditorState.preview.seek(EditorState.playbackPosition);
        }
        seekAudio(EditorState.playbackPosition);
        updateTimeScrubber();
        updatePlayhead();
    }

    // Home - Go to start
    if (e.code === 'Home' && !e.target.matches('input, textarea, [contenteditable="true"]')) {
        e.preventDefault();
        EditorState.playbackPosition = 0;
        if (EditorState.preview) {
            EditorState.preview.seek(EditorState.playbackPosition);
        }
        seekAudio(EditorState.playbackPosition);
        updateTimeScrubber();
        updatePlayhead();
    }

    // End - Go to end
    if (e.code === 'End' && !e.target.matches('input, textarea, [contenteditable="true"]')) {
        e.preventDefault();
        EditorState.playbackPosition = EditorState.project.totalDuration;
        if (EditorState.preview) {
            EditorState.preview.seek(EditorState.playbackPosition);
        }
        seekAudio(EditorState.playbackPosition);
        updateTimeScrubber();
        updatePlayhead();
    }

    // +/= - Zoom in
    if ((e.key === '+' || e.key === '=') && !e.ctrlKey && !e.metaKey && !e.target.matches('input, textarea, [contenteditable="true"]')) {
        e.preventDefault();
        EditorState.zoomLevel = Math.min(4, EditorState.zoomLevel * 1.5);
        updateZoom();
    }

    // - (minus) - Zoom out
    if (e.key === '-' && !e.ctrlKey && !e.metaKey && !e.target.matches('input, textarea, [contenteditable="true"]')) {
        e.preventDefault();
        EditorState.zoomLevel = Math.max(0.25, EditorState.zoomLevel / 1.5);
        updateZoom();
    }

    // S - Split scene at playhead
    if (e.code === 'KeyS' && !e.ctrlKey && !e.metaKey && !e.target.matches('input, textarea, [contenteditable="true"]')) {
        const time = EditorState.playbackPosition;
        // Find which scene the playhead is over
        let cumulative = 0;
        let splitIndex = -1;
        let splitOffset = 0;
        for (let i = 0; i < EditorState.scenes.length; i++) {
            const dur = EditorState.scenes[i].duration || 0;
            if (time > cumulative && time < cumulative + dur) {
                splitIndex = i;
                splitOffset = time - cumulative;
                break;
            }
            cumulative += dur;
        }
        if (splitIndex < 0 || splitOffset <= 0.1) return; // nothing to split or too close to edge

        e.preventDefault();
        const original = EditorState.scenes[splitIndex];
        const originalDur = original.duration;

        // Create the second half as a clone
        const clone = JSON.parse(JSON.stringify(original));
        clone.id = Math.max(...EditorState.scenes.map(s => s.id)) + 1;
        clone.duration = originalDur - splitOffset;

        // Shorten the original
        original.duration = splitOffset;

        // Insert clone after original
        EditorState.scenes.splice(splitIndex + 1, 0, clone);

        recalculateDuration();
        renderTimeline();
        saveProjectEdits();
        recordEdit('Split scene', original.id, 'split', originalDur, splitOffset);
        showToast(`Split scene ${original.id} at ${formatTimestamp(time)}`, 'success');
    }

    // D or E - Delete selected element (audio track, scene, text overlay, SFX clip)
    if ((e.code === 'KeyD' || e.code === 'KeyE') && !e.target.matches('input, textarea, [contenteditable="true"]')) {
        // 1. Selected audio track (music, SFX — not voice)
        const selTrack = EditorState.selectedAudioTrack;
        if (selTrack && selTrack.type !== 'voice') {
            e.preventDefault();
            removeAudioTrack(selTrack.id);
            showToast(`Removed "${selTrack.label || selTrack.file || 'track'}"`, 'info');
            return;
        }

        // 2. Selected text overlay
        if (EditorState.selectedTextOverlaySceneId != null) {
            const scene = EditorState.scenes.find(s => s.id === EditorState.selectedTextOverlaySceneId);
            if (scene && scene.text_content) {
                e.preventDefault();
                const oldText = scene.text_content;
                clearSceneTextOverlay(scene);
                EditorState.selectedTextOverlaySceneId = null;
                renderAllTextOverlays();
                renderSceneProperties();
                saveProjectEdits();
                recordEdit('Remove text overlay', scene.id, 'text_content', oldText, null);
                showToast('Text overlay removed', 'info');
                return;
            }
        }

        // 3. Selected scene (remove from timeline)
        const selScene = EditorState.selectedScene;
        if (selScene && EditorState.scenes.length > 1) {
            e.preventDefault();
            const idx = EditorState.scenes.findIndex(s => s.id === selScene.id);
            if (idx !== -1) {
                const removed = EditorState.scenes.splice(idx, 1)[0];
                EditorState.selectedScene = null;
                recalculateDuration();
                renderTimeline();
                renderSceneProperties();
                saveProjectEdits();
                recordEdit('Remove scene', removed.id, 'removeScene', removed, null);
                showToast(`Removed scene ${removed.id}`, 'info');
            }
            return;
        }
    }

    // Escape - Deselect
    if (e.code === 'Escape') {
        EditorState.selectedScene = null;
        EditorState.selectedAudioTrack = null;
        elements.videoTrack.querySelectorAll('.scene-clip.selected').forEach(el => {
            el.classList.remove('selected');
        });
        document.querySelectorAll('.audio-clip-universal.selected').forEach(el => el.classList.remove('selected'));
        renderSceneProperties();
        updateEffectsTab();
        updateTransitionsTab();
        updateOverlaysTab();
    }
}

// Expose editor init for the main app to call when navigating to the editor page.
// Ensures init only runs once; subsequent calls are no-ops.
let _editorInitialized = false;
window.initEditor = async function () {
    if (_editorInitialized) return;
    _editorInitialized = true;
    await init();
};

/**
 * Load scenes data directly into the editor (replaces postMessage bridge).
 * Uses full bootstrap to load media, hide overlays, and validate.
 */
window.editorLoadScenes = function (data) {
    if (!data) return;
    _resetEditorForNewProject();
    bootstrapProjectIntoEditor(data, {
        initialMessage: 'Loading project...',
        readyMessage: 'Project loaded',
        failureMessage: 'Failed to load project',
        showNoDataOnError: true,
    }).catch(e => {
        if (e.message !== 'Editor load superseded by a newer request') {
            console.warn('editorLoadScenes bootstrap failed:', e);
        }
    });
};

/**
 * Load captions data directly into the editor (replaces postMessage bridge).
 */
window.editorLoadCaptions = function (captionData) {
    if (!captionData || !captionData.captions) return;
    EditorState.captionData = captionData;
    if (EditorState.preview) {
        EditorState.preview.setCaptions(captionData.captions, captionData.style || {});
    }
};

/**
 * Reset editor state so it can be re-initialized (e.g. after Vue route leave + return).
 * Called by useEditor.destroy() before the DOM is torn down.
 */
window.resetEditor = function () {
    _editorInitialized = false;
    _eventListenersReady = false;
    // Re-query all DOM elements on next init
    Object.keys(elements).forEach(k => { elements[k] = null; });
};

/**
 * Re-query all DOM element references. Called at the start of init() to
 * pick up fresh DOM nodes after Vue re-mounts the editor page.
 */
function refreshElements() {
    elements.projectName = document.getElementById('project-name');
    elements.noDataOverlay = document.getElementById('no-data-overlay');
    elements.timelineTracks = document.getElementById('timeline-tracks');
    elements.videoTrack = document.getElementById('video-track');
    elements.textTrack = document.getElementById('text-track');
    elements.captionTrack = document.getElementById('caption-track');
    elements.captionTrackRow = document.getElementById('caption-track-row');
    elements.audioTracksContainer = document.getElementById('audio-tracks-container');
    elements.previewCanvas = document.getElementById('preview-canvas');
    elements.previewPlaceholder = document.getElementById('preview-placeholder');
    elements.currentTime = document.getElementById('current-time');
    elements.totalTime = document.getElementById('total-time');
    elements.timeScrubber = document.getElementById('time-scrubber');
    elements.playBtn = document.getElementById('play-btn');
    elements.loopBtn = document.getElementById('loop-btn');
    elements.volumeBtn = document.getElementById('volume-btn');
    elements.fullscreenBtn = document.getElementById('fullscreen-btn');
    elements.previewPanel = document.getElementById('preview-panel');
    elements.selectFolderBtn = document.getElementById('select-folder');
    elements.randomizeMediaBtn = document.getElementById('randomize-media');
    elements.flipFillerBtn = document.getElementById('flip-filler-btn');
    elements.mediaStatus = document.getElementById('media-status');
    elements.zoomIn = document.getElementById('zoom-in');
    elements.zoomOut = document.getElementById('zoom-out');
    elements.zoomLevel = document.getElementById('zoom-level');
    elements.infoScenes = document.getElementById('info-scenes');
    elements.infoDuration = document.getElementById('info-duration');
    elements.sceneProperties = document.getElementById('scene-properties');
    elements.previewJsonBtn = document.getElementById('preview-json');
    elements.exportShareBtn = document.getElementById('export-share-btn');
    elements.timeRuler = document.getElementById('time-ruler');
    elements.timelineMinimap = document.getElementById('timeline-minimap');
    elements.timelineResizeHandle = document.getElementById('timeline-resize-handle');
    elements.timelineHeaderMarker = document.getElementById('timeline-header-marker');
    elements.headerMarkerIndicator = document.querySelector('.header-marker-indicator');
    elements.headerMarkerTrail = document.querySelector('.header-marker-trail');
    elements.editorLayout = document.querySelector('.editor-layout');
    elements.timelinePanel = document.querySelector('.timeline-panel');
    elements.exportProgressModal = document.getElementById('export-progress-modal');
    elements.exportProgressTitle = document.getElementById('export-progress-title');
    elements.exportProgressBar = document.getElementById('export-progress-bar');
    elements.exportProgressPercent = document.getElementById('export-progress-percent');
    elements.exportProgressMessage = document.getElementById('export-progress-message');
    elements.cancelExportBtn = document.getElementById('cancel-export');
    elements.previewExportBtn = document.getElementById('preview-export');
    elements.openExportFolderBtn = document.getElementById('open-export-folder');
    elements.downloadExportBtn = document.getElementById('download-export');
}
