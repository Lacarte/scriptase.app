/**
 * STS DevTools — Service Worker
 *
 * Connects to the ai-web-auto WebSocket server for CDP automation,
 * AND directly to the STS Flask API for pipeline control/monitoring.
 *
 * Capabilities:
 *   - Pipeline: run, stop, monitor progress (SSE), get status
 *   - Health: check STS backend, extensions, TTS, alignment
 *   - API proxy: call any STS endpoint from popup/content
 *   - Screenshots: capture any page state via CDP
 *   - DOM observation: structured diff via ai-web-auto observe commands
 *   - Navigation: jump to any STS module page
 */

// ── Config ─────────────────────────────────────────────────────────────────

// Defines STS_ENDPOINT. The launcher rewrites that file with the ports the
// backend and the automation server actually bound, so nothing here hardcodes
// one; a saved sts_base_url override still wins over both.
importScripts(chrome.runtime.getURL('sts-endpoint.js'));

const DEFAULT_STS_BASE = 'http://' + STS_ENDPOINT.host + ':' + STS_ENDPOINT.appPorts[0];
const AWA_WS_URL = 'ws://' + STS_ENDPOINT.host + ':' + STS_ENDPOINT.automationPort;
const AWA_TOKEN = 'local-dev-token';

let stsBase = DEFAULT_STS_BASE;
let awaWs = null;
let awaConnected = false;
let pendingCommands = new Map();

// Load saved STS base URL
chrome.storage.local.get(['sts_base_url'], (r) => {
  if (r.sts_base_url) stsBase = r.sts_base_url;
});

chrome.storage.onChanged.addListener((changes, area) => {
  if (area === 'local' && changes.sts_base_url) {
    stsBase = changes.sts_base_url.newValue || DEFAULT_STS_BASE;
  }
});

// ── Keepalive ──────────────────────────────────────────────────────────────

chrome.alarms.create('keepalive', { periodInMinutes: 0.25 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === 'keepalive' && !awaConnected) connectAWA();
});

// ── ai-web-auto WebSocket (optional — for CDP automation) ──────────────────

function connectAWA() {
  if (awaWs && awaWs.readyState <= 1) return;
  try {
    awaWs = new WebSocket(AWA_WS_URL);
    awaWs.onopen = () => {
      awaWs.send(JSON.stringify({ type: 'auth', token: AWA_TOKEN }));
      awaConnected = true;
      console.log('[STS-DT] ai-web-auto connected');
    };
    awaWs.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);
        if (msg.type === 'response' && msg.correlation_id) {
          const resolve = pendingCommands.get(msg.correlation_id);
          if (resolve) {
            pendingCommands.delete(msg.correlation_id);
            resolve(msg);
          }
        }
      } catch {}
    };
    awaWs.onclose = () => { awaConnected = false; };
    awaWs.onerror = () => { awaConnected = false; };
  } catch { awaConnected = false; }
}

connectAWA();

function sendAWACommand(action, params = {}, target = {}) {
  return new Promise((resolve, reject) => {
    if (!awaConnected || !awaWs) {
      reject(new Error('ai-web-auto not connected'));
      return;
    }
    const id = crypto.randomUUID();
    const cmd = { type: 'command', id, action, target, params, timeout: 30000 };
    pendingCommands.set(id, resolve);
    awaWs.send(JSON.stringify(cmd));
    setTimeout(() => {
      if (pendingCommands.has(id)) {
        pendingCommands.delete(id);
        reject(new Error('Timeout'));
      }
    }, 30000);
  });
}

// ── STS API helpers ────────────────────────────────────────────────────────

async function stsAPI(method, path, body = null) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(`${stsBase}${path}`, opts);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  const ct = res.headers.get('content-type') || '';
  return ct.includes('json') ? res.json() : res.text();
}

// ── STS route map — all navigable pages ────────────────────────────────────

const STS_ROUTES = {
  pipeline:       '/#/pipeline',
  tts:            '/#/tts',
  alignment:      '/#/alignment',
  segmenter:      '/#/segmenter',
  scenes:         '/#/scenes',
  storyboard:     '/#/storyboard',
  assets:         '/#/assets',
  editor:         '/#/editor',
  export:         '/#/export-library',
  settings:       '/#/settings',
};

// ── Message router (popup/content → service worker) ────────────────────────

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.channel !== 'sts-devtools') return;
  handleMessage(msg).then(sendResponse).catch(e => sendResponse({ error: e.message }));
  return true;
});

async function handleMessage(msg) {
  const { action, payload = {} } = msg;

  switch (action) {

    // ── Status ──────────────────────────────────────────────────────────
    case 'get_status': {
      let health = null;
      try { health = await stsAPI('GET', '/api/health'); } catch {}
      return {
        sts_reachable: !!health,
        sts_health: health,
        awa_connected: awaConnected,
        sts_base: stsBase,
      };
    }

    // ── Navigation ──────────────────────────────────────────────────────
    case 'navigate': {
      const route = STS_ROUTES[payload.page] || payload.url;
      if (!route) return { error: 'Unknown page' };
      const url = route.startsWith('http') ? route : `${stsBase}${route}`;
      const [tab] = await chrome.tabs.query({ url: `${stsBase}/*`, active: true, currentWindow: true });
      if (tab) {
        await chrome.tabs.update(tab.id, { url, active: true });
      } else {
        await chrome.tabs.create({ url, active: true });
      }
      return { ok: true, url };
    }

    // ── Pipeline ────────────────────────────────────────────────────────
    case 'pipeline_run': {
      return await stsAPI('POST', '/api/pipeline/run', payload.config);
    }

    case 'pipeline_stop': {
      return await stsAPI('POST', `/api/pipeline/${payload.job_id}/stop`);
    }

    case 'pipeline_jobs': {
      return await stsAPI('GET', '/api/pipeline/jobs');
    }

    // ── API proxy (call any STS endpoint) ───────────────────────────────
    case 'api': {
      return await stsAPI(payload.method || 'GET', payload.path, payload.body);
    }

    // ── Screenshot via CDP ──────────────────────────────────────────────
    case 'screenshot': {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (!tab) return { error: 'No active tab' };
      const dataUrl = await chrome.tabs.captureVisibleTab(null, { format: 'png' });
      const b64 = dataUrl.replace(/^data:image\/png;base64,/, '');

      // Auto-save if requested
      if (payload.save) {
        const filename = `sts-screenshot-${Date.now()}.png`;
        await chrome.downloads.download({
          url: dataUrl,
          filename: `sts-devtools/${filename}`,
          conflictAction: 'uniquify',
        });
        return { ok: true, filename };
      }
      return { screenshot: b64 };
    }

    // ── DOM observation (via ai-web-auto) ───────────────────────────────
    case 'observe_start': {
      return await sendAWACommand('observe_start', { selector: payload.selector || 'body' });
    }

    case 'observe_diff': {
      return await sendAWACommand('observe_diff');
    }

    case 'observe_stop': {
      return await sendAWACommand('observe_stop');
    }

    // ── Module testing — run targeted checks ────────────────────────────
    case 'test_module': {
      return await testModule(payload.module);
    }

    // ── Get all projects ────────────────────────────────────────────────
    case 'list_projects': {
      return await stsAPI('GET', '/api/projects');
    }

    // ── Voice listing ───────────────────────────────────────────────────
    case 'list_voices': {
      const provider = payload.provider || 'kokoro';
      return await stsAPI('GET', `/api/tts/voices?provider=${provider}`);
    }

    // ── Niche presets ───────────────────────────────────────────────────
    case 'list_niches': {
      return await stsAPI('GET', '/api/niches');
    }

    // ── Scene templates ─────────────────────────────────────────────────
    case 'list_templates': {
      return await stsAPI('GET', '/api/scenes/templates');
    }

    default:
      return { error: `Unknown action: ${action}` };
  }
}

// ── Module testing ─────────────────────────────────────────────────────────

async function testModule(module) {
  const results = { module, tests: [], passed: 0, failed: 0 };

  function pass(name, data) { results.tests.push({ name, status: 'pass', data }); results.passed++; }
  function fail(name, error) { results.tests.push({ name, status: 'fail', error }); results.failed++; }

  try {
    switch (module) {

      case 'health': {
        try {
          const h = await stsAPI('GET', '/api/health');
          pass('API reachable', h);
          if (h.tts) pass('TTS engine loaded'); else fail('TTS engine', 'Not loaded');
          if (h.alignment) pass('Alignment engine loaded'); else fail('Alignment engine', 'Not loaded');
        } catch (e) { fail('API reachable', e.message); }
        break;
      }

      case 'tts': {
        try {
          const voices = await stsAPI('GET', '/api/tts/voices');
          pass(`Voices endpoint (${Array.isArray(voices) ? voices.length : '?'} voices)`, voices);
        } catch (e) { fail('Voices endpoint', e.message); }

        try {
          const iwVoices = await stsAPI('GET', '/api/tts/voices?provider=inworld');
          pass(`Inworld voices (${Array.isArray(iwVoices) ? iwVoices.length : '?'})`, iwVoices);
        } catch (e) { fail('Inworld voices', e.message); }

        try {
          const models = await stsAPI('GET', '/api/tts/models');
          pass('Models endpoint', models);
        } catch (e) { fail('Models endpoint', e.message); }
        break;
      }

      case 'scenes': {
        try {
          const templates = await stsAPI('GET', '/api/scenes/templates');
          pass(`Templates (${Array.isArray(templates) ? templates.length : '?'})`, templates);
        } catch (e) { fail('Templates endpoint', e.message); }

        try {
          const wh = await stsAPI('GET', '/api/scenes/webhook-url');
          if (wh) pass('Webhook URL configured', wh); else fail('Webhook URL', 'Not set');
        } catch (e) { fail('Webhook URL', e.message); }
        break;
      }

      case 'storyboard': {
        try {
          const models = await stsAPI('GET', '/api/storyboard/image-models');
          pass(`Image models (${Array.isArray(models) ? models.length : '?'})`, models);
        } catch (e) { fail('Image models', e.message); }

        try {
          const wh = await stsAPI('GET', '/api/storyboard/webhook-url');
          if (wh) pass('Webhook URL configured', wh); else fail('Webhook URL', 'Not set');
        } catch (e) { fail('Webhook URL', e.message); }
        break;
      }

      case 'pipeline': {
        try {
          const jobs = await stsAPI('GET', '/api/pipeline/jobs');
          pass(`Jobs endpoint (${Array.isArray(jobs) ? jobs.length : '?'} jobs)`, jobs);
        } catch (e) { fail('Jobs endpoint', e.message); }

        try {
          const pf = await stsAPI('POST', '/api/pipeline/preflight');
          pass('Preflight check', pf);
        } catch (e) { fail('Preflight check', e.message); }
        break;
      }

      case 'niches': {
        try {
          const n = await stsAPI('GET', '/api/niches');
          const count = n ? Object.keys(n).length : 0;
          pass(`Presets loaded (${count})`, n);
        } catch (e) { fail('Presets endpoint', e.message); }
        break;
      }

      case 'music': {
        try {
          const lib = await stsAPI('GET', '/api/music/library');
          pass(`Music library (${Array.isArray(lib) ? lib.length : '?'} tracks)`, lib);
        } catch (e) { fail('Music library', e.message); }
        break;
      }

      case 'story': {
        try {
          const cats = await stsAPI('GET', '/api/story/categories');
          pass(`Categories (${Array.isArray(cats) ? cats.length : '?'})`, cats);
        } catch (e) { fail('Categories endpoint', e.message); }

        try {
          const wh = await stsAPI('GET', '/api/story/webhook-url');
          if (wh) pass('Webhook URL configured', wh); else fail('Webhook URL', 'Not set');
        } catch (e) { fail('Webhook URL', e.message); }
        break;
      }

      default:
        fail('Unknown module', `"${module}" is not a testable module`);
    }
  } catch (e) {
    fail('Unexpected error', e.message);
  }

  return results;
}
