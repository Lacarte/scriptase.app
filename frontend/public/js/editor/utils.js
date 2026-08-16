// Scene type colors
export const SCENE_COLORS = {
    hook: "#FF4444",
    buildup: "#FF8C00",
    text: "#AA44FF",
    peak: "#FFDD00",
    transition: "#4488FF",
    cta: "#44FF44",
    speaker: "#FF44AA",
    final_statement: "#44FFFF"
};

// Visual FX icons - flat outline SVG style
export const VFX_ICONS = {
    zoom_in: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4-4M8 11h6M11 8v6"/></svg>`,
    zoom_out: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4-4M8 11h6"/></svg>`,
    pan_left: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M19 12H5M12 5l-7 7 7 7"/></svg>`,
    pan_right: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M5 12h14M12 5l7 7-7 7"/></svg>`,
    fade: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="9" opacity="0.3"/><circle cx="12" cy="12" r="5"/></svg>`,
    static: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="4" y="4" width="16" height="16" rx="2"/></svg>`,
    shake: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M4 12h2M18 12h2M7 6l2 2M15 16l2 2M7 18l2-2M15 8l2-2M12 4v2M12 18v2"/></svg>`,
    slow_motion: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/></svg>`
};

// Scene type icons - flat outline SVG style
export const SCENE_TYPE_ICONS = {
    hook: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><path d="M14 2v6h6"/><path d="M9 13h6M9 17h4"/></svg>`,
    buildup: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="4" y="14" width="4" height="6" rx="1"/><rect x="10" y="10" width="4" height="10" rx="1"/><rect x="16" y="6" width="4" height="14" rx="1"/></svg>`,
    text: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M6 4h12M12 4v16M8 20h8"/></svg>`,
    peak: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 4l2.5 5h5.5l-4.5 3.5 1.7 5.5-5.2-3.5-5.2 3.5 1.7-5.5L4 9h5.5z"/></svg>`,
    transition: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M5 12h14"/><path d="M13 6l6 6-6 6"/></svg>`,
    cta: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="7" width="18" height="10" rx="2"/><path d="M9 12h6M12 9v6"/></svg>`,
    speaker: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="8" r="4"/><path d="M5 20c0-4 3.5-6 7-6s7 2 7 6"/></svg>`,
    final_statement: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M8 12l3 3 5-6"/></svg>`
};

// Allowed visual effects
export const ALLOWED_VFX = Object.keys(VFX_ICONS);

// Scene types
export const SCENE_TYPES = Object.keys(SCENE_COLORS);

// Status options
export const STATUS_OPTIONS = ["pending", "done", "error"];

// Format seconds to m:ss
export function formatTimestamp(seconds) {
    if (isNaN(seconds) || seconds == null) return '0:00';
    const totalSeconds = Math.floor(seconds);
    const m = Math.floor(totalSeconds / 60);
    const s = totalSeconds % 60;
    return `${m}:${s.toString().padStart(2, '0')}`;
}

// Parse m:ss to seconds
export function parseTimestamp(timestamp) {
    const [m, s] = timestamp.split(':').map(Number);
    return m * 60 + s;
}

// Calculate timestamps for all scenes based on durations
export function calculateTimestamps(scenes) {
    let cumulative = 0;
    return scenes.map(scene => {
        const timestamp = formatTimestamp(cumulative);
        cumulative += scene.duration;
        return { ...scene, timestamp };
    });
}

// Get total duration of scenes
export function getTotalDuration(scenes) {
    return scenes.reduce((sum, scene) => sum + (scene.duration || 0), 0);
}

// Generate unique ID
export function generateId() {
    return `pm_${Date.now()}_${Math.random().toString(36).substring(2, 8)}`;
}

// Deep clone object
export function deepClone(obj) {
    return JSON.parse(JSON.stringify(obj));
}

// Debounce function
export function debounce(fn, delay) {
    let timeoutId;
    return (...args) => {
        clearTimeout(timeoutId);
        timeoutId = setTimeout(() => fn(...args), delay);
    };
}

// Format relative time
export function formatRelativeTime(date) {
    const now = new Date();
    const diff = Math.floor((now - date) / 1000);

    if (diff < 60) return 'Just now';
    if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)} hours ago`;
    return date.toLocaleDateString();
}

// Local storage helpers
export const Storage = {
    save(key, data) {
        if (STS.get('sts-editor-storage') === 'false') return false;
        try {
            localStorage.setItem(key, JSON.stringify(data));
            return true;
        } catch (e) {
            console.error('Storage save error:', e);
            return false;
        }
    },

    load(key) {
        try {
            const data = localStorage.getItem(key);
            return data ? JSON.parse(data) : null;
        } catch (e) {
            console.error('Storage load error:', e);
            return null;
        }
    },

    remove(key) {
        localStorage.removeItem(key);
    }
};

// Toast container and queue management
let toastContainer = null;
let toastQueue = [];
let isProcessingQueue = false;

function getToastContainer() {
    if (!toastContainer) {
        toastContainer = document.createElement('div');
        toastContainer.className = 'toast-container';
        document.body.appendChild(toastContainer);
    }
    return toastContainer;
}

// Show toast notification with vertical stacking and delay
export function showToast(message, type = 'info', delay = 0) {
    const container = getToastContainer();

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    // Stagger the appearance based on existing toasts
    const existingToasts = container.querySelectorAll('.toast.show').length;
    const staggerDelay = delay || existingToasts * 150;

    setTimeout(() => toast.classList.add('show'), 10 + staggerDelay);
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 300);
    }, 3000 + staggerDelay);
}


// ---------------------------------------------------------------------------
// Backend log relay — sends frontend logs to /api/log for unified logging
// ---------------------------------------------------------------------------
const _logQueue = [];
let _logFlushTimer = null;

function _flushLogQueue() {
    if (!_logQueue.length) return;
    const batch = _logQueue.splice(0, 20);
    for (const entry of batch) {
        fetch('/api/log', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(entry)
        }).catch(() => { }); // fire-and-forget
    }
}

function _queueLog(level, source, message, context) {
    _logQueue.push({ level, source, message, context: context || '' });
    clearTimeout(_logFlushTimer);
    _logFlushTimer = setTimeout(_flushLogQueue, 300);
}

export const backendLog = {
    info: (msg, ctx) => { console.log(`[${msg}]`, ctx || ''); _queueLog('info', 'editor', msg, ctx); },
    warn: (msg, ctx) => { console.warn(`[${msg}]`, ctx || ''); _queueLog('warning', 'editor', msg, ctx); },
    error: (msg, ctx) => { console.error(`[${msg}]`, ctx || ''); _queueLog('error', 'editor', msg, ctx); },
    debug: (msg, ctx) => { console.debug(`[${msg}]`, ctx || ''); _queueLog('debug', 'editor', msg, ctx); },
};

// ---------------------------------------------------------------------------
// Global error handlers — catch all uncaught errors and relay to backend
// ---------------------------------------------------------------------------
window.addEventListener('error', (event) => {
    const loc = event.filename ? `${event.filename.split('/').pop()}:${event.lineno}:${event.colno}` : 'unknown';
    _queueLog('error', 'frontend', `Uncaught: ${event.message}`, loc);
});

window.addEventListener('unhandledrejection', (event) => {
    const reason = event.reason;
    const msg = reason instanceof Error ? `${reason.message}` : String(reason);
    const stack = reason?.stack ? reason.stack.split('\n').slice(0, 3).join(' | ') : '';
    _queueLog('error', 'frontend', `Unhandled rejection: ${msg}`, stack);
});
