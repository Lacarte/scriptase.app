/**
 * STS DevTools — Content Script
 *
 * Injected into localhost STS pages. Provides:
 *   - Live pipeline status overlay (floating badge)
 *   - Vue app state extraction (pipeline status, form data, logs)
 *   - Page health indicator
 *   - Keyboard shortcuts for common actions
 *   - DOM introspection helpers for the popup
 */

(() => {
  'use strict';
  if (window !== window.top) return;
  if (window.__stsDevToolsLoaded) return;
  window.__stsDevToolsLoaded = true;

  // ── Helpers ────────────────────────────────────────────────────────────

  function send(action, payload = {}) {
    return chrome.runtime.sendMessage({ channel: 'sts-devtools', action, payload });
  }

  function getPrimaryPromptText() {
    const fields = document.querySelectorAll(
      'textarea[class*="story"], textarea[class*="prompt"], textarea[class*="text"], textarea'
    );
    for (const field of fields) {
      if (!field || field.offsetParent === null) continue;
      const value = typeof field.value === 'string' ? field.value : field.textContent;
      if (typeof value === 'string' && value.trim()) return value;
    }
    return '';
  }

  function hasVisibleGeneratingIndicator() {
    const selector = [
      '.status-badge.generating',
      '.status--generating',
      '.status-generating',
      '[class*="generating"]',
      '[class*="processing"]',
      '[class*="loading"]',
      '.spinner',
      '.spinner-ring'
    ].join(', ');
    const visibleIndicator = Array.from(document.querySelectorAll(selector))
      .some((el) => el.offsetParent !== null);
    if (visibleIndicator) return true;

    const textIndicators = Array.from(document.querySelectorAll('button, span, div, p'))
      .filter((el) => el.offsetParent !== null)
      .some((el) => /\b(generating|processing|downloading)\b/i.test(el.textContent || ''));

    return textIndicators;
  }

  // ── Vue App State Extraction ───────────────────────────────────────────

  function getVueAppState() {
    // Try to read reactive state from Vue's internal store
    const state = {
      route: location.hash.replace('#', '') || '/',
      title: document.title,
      timestamp: Date.now(),
    };

    // Pipeline status from DOM
    const stepperEl = document.querySelector('[class*="stepper"], [class*="progress-step"]');
    if (stepperEl) {
      const steps = stepperEl.querySelectorAll('[class*="step"]');
      state.pipeline_steps = Array.from(steps).map(s => ({
        text: s.textContent?.trim().slice(0, 30),
        classes: s.className,
        done: /done|complete|success/.test(s.className),
        running: /running|active|current/.test(s.className),
        error: /error|fail/.test(s.className),
      }));
    }

    // Pipeline log entries
    const logEls = document.querySelectorAll('[class*="log-entry"], [class*="pipeline-log"] [class*="entry"]');
    if (logEls.length) {
      state.log_entries = Array.from(logEls).slice(-20).map(el => el.textContent?.trim().slice(0, 200));
    }

    // Active form values
    const promptText = getPrimaryPromptText();
    if (promptText) {
      state.story_text = promptText;
      state.story_text_length = promptText.length;
    }
    state.is_generating = hasVisibleGeneratingIndicator();

    // Toast/notification messages
    const toasts = document.querySelectorAll('[class*="toast"], [class*="notification"], [class*="snackbar"]');
    if (toasts.length) {
      state.toasts = Array.from(toasts).map(t => t.textContent?.trim().slice(0, 100));
    }

    // Error indicators — only match visible, non-history error elements
    const errors = document.querySelectorAll('.gen-error, .state-error, .error-text, .preview-error-text, .snackbar-bar--urgent');
    if (errors.length) {
      state.errors = Array.from(errors)
        .filter(e => e.offsetParent !== null && e.textContent?.trim().length > 0)
        .map(e => e.textContent?.trim().slice(0, 200));
    }

    // Running indicator
    const runBtn = document.querySelector('button[class*="run"], button[class*="start"]');
    if (runBtn) state.run_button_text = runBtn.textContent?.trim();

    return state;
  }

  // ── Floating Status Badge ──────────────────────────────────────────────

  function injectBadge() {
    if (document.getElementById('sts-dt-badge')) return;
    const badge = document.createElement('div');
    badge.id = 'sts-dt-badge';
    badge.innerHTML = `
      <style>
        #sts-dt-badge {
          position: fixed;
          bottom: 12px;
          left: 50%;
          transform: translateX(-50%);
          z-index: 999999;
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 4px 10px;
          background: rgba(15, 15, 20, 0.85);
          backdrop-filter: blur(8px);
          border: 1px solid rgba(100, 100, 120, 0.3);
          border-radius: 20px;
          font-family: 'JetBrains Mono', monospace;
          font-size: 11px;
          color: #aaa;
          cursor: grab;
          user-select: none;
          transition: opacity 0.2s, box-shadow 0.2s;
        }
        #sts-dt-badge:hover { opacity: 1; border-color: rgba(100, 200, 255, 0.5); }
        #sts-dt-badge.dragging { cursor: grabbing; box-shadow: 0 4px 16px rgba(0,0,0,0.4); }
        #sts-dt-badge .dot {
          width: 7px; height: 7px; border-radius: 50%;
          background: #555;
          transition: background 0.3s;
        }
        #sts-dt-badge .dot.ok { background: #4caf50; }
        #sts-dt-badge .dot.running { background: #ff9800; animation: sts-dt-pulse 1s infinite; }
        #sts-dt-badge .dot.error { background: #f44336; }
        @keyframes sts-dt-pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
      </style>
      <div class="dot" id="sts-dt-dot"></div>
      <span id="sts-dt-label">STS DevTools</span>
    `;
    document.body.appendChild(badge);

    // ── Drag support ──
    let isDragging = false, dragOffset = { x: 0, y: 0 }, didDrag = false;

    badge.addEventListener('mousedown', (e) => {
      isDragging = true;
      didDrag = false;
      const rect = badge.getBoundingClientRect();
      dragOffset.x = e.clientX - rect.left;
      dragOffset.y = e.clientY - rect.top;
      badge.classList.add('dragging');
      // Switch to left/top positioning for free movement. Clear the initial
      // bottom-middle centering transform so the drag tracks the cursor exactly.
      badge.style.right = 'auto';
      badge.style.bottom = 'auto';
      badge.style.transform = 'none';
      badge.style.left = rect.left + 'px';
      badge.style.top = rect.top + 'px';
      e.preventDefault();
    });

    document.addEventListener('mousemove', (e) => {
      if (!isDragging) return;
      didDrag = true;
      const x = Math.max(0, Math.min(e.clientX - dragOffset.x, window.innerWidth - badge.offsetWidth));
      const y = Math.max(0, Math.min(e.clientY - dragOffset.y, window.innerHeight - badge.offsetHeight));
      badge.style.left = x + 'px';
      badge.style.top = y + 'px';
    });

    document.addEventListener('mouseup', () => {
      if (!isDragging) return;
      isDragging = false;
      badge.classList.remove('dragging');
    });

    badge.addEventListener('click', (e) => {
      if (didDrag) return; // Don't trigger click after drag
      send('screenshot', { save: true });
    });

    // Update badge based on page state
    updateBadge();
    setInterval(updateBadge, 3000);
  }

  function updateBadge() {
    const dot = document.getElementById('sts-dt-dot');
    const label = document.getElementById('sts-dt-label');
    if (!dot || !label) return;

    const state = getVueAppState();

    // Check for running pipeline
    const isRunning = state.pipeline_steps?.some(s => s.running);
    const hasError = state.errors?.length > 0 || state.pipeline_steps?.some(s => s.error);

    if (isRunning) {
      dot.className = 'dot running';
      label.textContent = 'Pipeline running';
    } else if (hasError) {
      dot.className = 'dot error';
      label.textContent = 'Error detected';
    } else {
      dot.className = 'dot ok';
      const page = state.route.replace('/', '') || 'pipeline';
      label.textContent = `STS: ${page}`;
    }
  }

  // ── Keyboard Shortcuts ─────────────────────────────────────────────────

  document.addEventListener('keydown', (e) => {
    // Ctrl+Shift+S → Screenshot
    if (e.ctrlKey && e.shiftKey && e.key === 'S') {
      e.preventDefault();
      send('screenshot', { save: true });
    }
    // Ctrl+Shift+D → DOM diff
    if (e.ctrlKey && e.shiftKey && e.key === 'D') {
      e.preventDefault();
      send('observe_diff').then(r => console.log('[STS-DT] DOM diff:', r));
    }
    // Ctrl+Shift+H → Health check
    if (e.ctrlKey && e.shiftKey && e.key === 'H') {
      e.preventDefault();
      send('get_status').then(r => console.log('[STS-DT] Status:', r));
    }
  });

  // ── Message handler (popup asks for page state) ────────────────────────

  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg.channel !== 'sts-devtools-content') return;

    switch (msg.action) {
      case 'get_page_state':
        sendResponse(getVueAppState());
        break;

      case 'get_element_info': {
        const el = document.querySelector(msg.payload.selector);
        if (!el) { sendResponse({ error: 'Not found' }); break; }
        const rect = el.getBoundingClientRect();
        sendResponse({
          tag: el.tagName.toLowerCase(),
          text: el.textContent?.trim().slice(0, 200),
          classes: el.className,
          id: el.id,
          rect: { x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height) },
          visible: rect.width > 0 && rect.height > 0 && el.offsetParent !== null,
          html: el.outerHTML.slice(0, 500),
        });
        break;
      }

      case 'click_element': {
        const el = document.querySelector(msg.payload.selector);
        if (el) { el.click(); sendResponse({ ok: true }); }
        else sendResponse({ error: 'Not found' });
        break;
      }

      case 'list_interactive': {
        const els = document.querySelectorAll('a, button, input, select, textarea, [role="button"], [role="tab"], [onclick], [tabindex]');
        const results = [];
        els.forEach(el => {
          const r = el.getBoundingClientRect();
          if (r.width < 5 || r.height < 5) return;
          results.push({
            tag: el.tagName.toLowerCase(),
            text: (el.textContent || el.value || el.placeholder || '').trim().slice(0, 50),
            id: el.id || '',
            selector: el.id ? `#${el.id}` : '',
            rect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) },
          });
        });
        sendResponse(results);
        break;
      }
    }
    return true;
  });

  // ── Public API (for console/ai-web-auto) ───────────────────────────────

  window.__stsDevTools = {
    getState: getVueAppState,
    screenshot: () => send('screenshot', { save: true }),
    navigate: (page) => send('navigate', { page }),
    testModule: (mod) => send('test_module', { module: mod }),
    status: () => send('get_status'),
    runPipeline: (config) => send('pipeline_run', { config }),
    stopPipeline: (jobId) => send('pipeline_stop', { job_id: jobId }),
    api: (method, path, body) => send('api', { method, path, body }),
  };

  // ── Boot ───────────────────────────────────────────────────────────────

  if (document.readyState === 'complete') injectBadge();
  else window.addEventListener('load', injectBadge);

  console.log('[STS DevTools] Loaded — window.__stsDevTools available');
})();
