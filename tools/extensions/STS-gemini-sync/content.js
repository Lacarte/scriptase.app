(function() {
  // ═══════════════════════════════════════════════════════
  // STS Gemini Image Synchronizer — Content Script v1
  // Runs as native content script (bypasses Trusted Types)
  // ═══════════════════════════════════════════════════════
  if (window !== window.top) return; // Skip iframes

  console.log('[STS Gemini] Content script loaded');

  // Listen for start/stop from popup
  chrome.runtime.onMessage.addListener(function(request, sender, sendResponse) {
    if (request.action === 'STS_START') {
      console.log('[STS Gemini] START received, wsUrl:', request.wsUrl);
      if (request.wsUrl) {
        localStorage.setItem('sts-gemini-ws', request.wsUrl);
      }
      initSync(request.wsUrl);
      sendResponse({ ok: true });
    } else if (request.action === 'STS_STATUS') {
      var s = window.__stsGeminiState;
      sendResponse({
        connected: !!(s && s.wsConnected),
        projectId: s ? s.projectId : null,
        sceneCount: s ? Object.keys(s.scenes).length : 0,
      });
      return true;
    } else if (request.action === 'STS_DIAGNOSE') {
      var s = window.__stsGeminiState;
      var connBar = document.getElementById('sts-conn-bar');
      var connMsg = document.getElementById('sts-conn-msg');
      var headDot = document.getElementById('sts-head-dot');
      sendResponse({
        active: !!window.__stsGeminiActive,
        wsConnected: s ? s.wsConnected : null,
        connected: s ? s.connected : null,
        wsUrl: s ? s.wsUrl : null,
        projectId: s ? s.projectId : null,
        scenesCount: s ? Object.keys(s.scenes).length : 0,
        queueLength: s ? s.typing.queue.length : 0,
        typingActive: s ? s.typing.active : false,
        panelExists: !!document.getElementById('sts-sync'),
        connBarDisplay: connBar ? connBar.style.display : null,
        connBarClass: connBar ? connBar.className : null,
        connMsgText: connMsg ? connMsg.textContent : null,
        headDotClass: headDot ? headDot.className : null,
      });
      return true;
    } else if (request.action === 'STS_STOP') {
      console.log('[STS Gemini] STOP received');
      if (window.__stsGeminiState) {
        window.__stsGeminiState.typing.stopRequested = true;
      }
      var panel = document.getElementById('sts-sync');
      if (panel) panel.remove();
      window.__stsGeminiActive = false;
      chrome.storage.local.set({ stsRunning: false });
      sendResponse({ ok: true });
    }
  });

  // Always auto-start on Gemini — connect WS and show panel immediately
  console.log('[STS Gemini] Auto-starting on page load');
  initSync(null);

  function initSync(wsUrlOverride) {
    console.log('=== STS Gemini Image Synchronizer v1 ===');
    if (window.__stsGeminiActive) {
      console.log('Synchronizer already running');
      return;
    }
    window.__stsGeminiActive = true;

    var S = {
      // Cold-start guess only; the background overwrites it with the URL it
      // actually connected on the moment the socket comes up (STS_WS_STATUS).
      wsUrl: wsUrlOverride || localStorage.getItem('sts-gemini-ws')
        || ('ws://' + STS_ENDPOINT.host + ':' + STS_ENDPOINT.appPorts[0] + '/ws/storyboard-gemini-image-grabber'),
      connected: false,
      collapsed: localStorage.getItem('sts-gemini-collapsed') === 'true',
      showSettings: false,
      showTestButton: localStorage.getItem('sts-gemini-show-test') === 'true',
      activeTab: 'typing',
      projectId: null,
      aspectRatio: '',
      scenes: {},
      history: {
        items: [],
        activeId: null,
        expanded: {},
      },
      wsConnected: false,
      typing: {
        active: false, starting: false, queue: [], runId: 0,
        currentIndex: -1, typedCount: 0, stopRequested: false, toolsEnabled: false,
        countdown: 0, countdownType: '',
      },
    };
    window.__stsGeminiState = S;

    function sleep(ms) { return new Promise(function(r) { setTimeout(r, ms); }); }

    // ── State persistence (chrome.storage.local) ───────────
    // Survives tab discards, page reloads, and browser restarts.
    // Only cleared by the manual CLEAR button.
    var STORAGE_KEY = 'sts-gemini-state-v1';
    var HISTORY_KEY = 'sts-gemini-history-v1';
    var HISTORY_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;
    var _saveTimer = null;
    function saveState() {
      if (_saveTimer) return; // debounce
      _saveTimer = setTimeout(function() {
        _saveTimer = null;
        try {
          var snapshot = {
            projectId: S.projectId,
            aspectRatio: S.aspectRatio,
            scenes: S.scenes,
            historyActiveId: S.history.activeId,
            typing: {
              queue: S.typing.queue.map(function(q) {
                var copy = {};
                for (var k in q) copy[k] = q[k];
                // Reset transient statuses so they can resume after reload
                if (copy.status === 'typing' || copy.status === 'starting' || copy.status === 'generating') {
                  copy.status = 'queued';
                }
                return copy;
              }),
              typedCount: S.typing.typedCount,
            },
          };
          chrome.storage.local.set({ 'sts-gemini-state-v1': snapshot });
        } catch (e) { console.warn('[STS] saveState failed:', e); }
      }, 500);
    }
    function loadState() {
      return new Promise(function(resolve) {
        try {
          chrome.storage.local.get(STORAGE_KEY, function(result) {
            if (chrome.runtime.lastError || !result || !result[STORAGE_KEY]) { resolve(); return; }
            var snap = result[STORAGE_KEY];
            if (snap.projectId) S.projectId = snap.projectId;
            if (snap.aspectRatio) S.aspectRatio = snap.aspectRatio;
            if (snap.scenes) S.scenes = snap.scenes;
            if (snap.historyActiveId) S.history.activeId = snap.historyActiveId;
            if (snap.typing) {
              if (Array.isArray(snap.typing.queue)) S.typing.queue = snap.typing.queue;
              if (typeof snap.typing.typedCount === 'number') S.typing.typedCount = snap.typing.typedCount;
            }
            console.log('[STS] State restored from storage:', S.typing.queue.length, 'queue items,', Object.keys(S.scenes).length, 'scenes');
            resolve();
          });
        } catch (e) { console.warn('[STS] loadState failed:', e); resolve(); }
      });
    }
    function clearStoredState() {
      try { chrome.storage.local.remove(STORAGE_KEY); } catch (e) {}
    }

    function sortHistoryEntries(entries) {
      return (entries || []).sort(function(a, b) {
        return (b.updatedAt || b.endedAt || b.startedAt || b.createdAt || 0) -
          (a.updatedAt || a.endedAt || a.startedAt || a.createdAt || 0);
      });
    }

    function pruneHistoryEntries(entries) {
      var cutoff = Date.now() - HISTORY_MAX_AGE_MS;
      return sortHistoryEntries((entries || []).filter(function(entry) {
        if (!entry || typeof entry !== 'object') return false;
        var stamp = entry.updatedAt || entry.endedAt || entry.startedAt || entry.createdAt || 0;
        return stamp >= cutoff;
      }));
    }

    function loadHistoryEntries() {
      var entries = [];
      try {
        var raw = localStorage.getItem(HISTORY_KEY);
        entries = raw ? JSON.parse(raw) : [];
      } catch (e) {
        entries = [];
      }
      if (!Array.isArray(entries)) entries = [];
      entries = pruneHistoryEntries(entries);
      try { localStorage.setItem(HISTORY_KEY, JSON.stringify(entries)); } catch (_e) {}
      return entries;
    }

    function persistHistoryEntries() {
      S.history.items = pruneHistoryEntries(S.history.items);
      try { localStorage.setItem(HISTORY_KEY, JSON.stringify(S.history.items)); } catch (e) {}
      return S.history.items;
    }

    function isFinalHistoryStatus(status) {
      return status === 'completed' ||
        status === 'completed_with_errors' ||
        status === 'failed' ||
        status === 'stopped' ||
        status === 'cleared';
    }

    function getUniqueProjectIds(items) {
      var seen = {};
      var projectIds = [];
      (items || []).forEach(function(item) {
        var pid = item && item.projectId ? item.projectId : null;
        if (!pid || seen[pid]) return;
        seen[pid] = true;
        projectIds.push(pid);
      });
      return projectIds;
    }

    function getProjectQueueItems(projectId) {
      return (S.typing.queue || []).filter(function(item) {
        return (item.projectId || S.projectId || '') === projectId;
      });
    }

    function buildProjectHistoryPrompts(projectId) {
      var prompts = [];
      getProjectQueueItems(projectId).forEach(function(item) {
        var sceneState = S.scenes[item.queueKey] || {};
        prompts.push({
          scene: String(item.scene || ''),
          prompt: item.displayPrompt || item.fullPrompt || sceneState.prompt || '',
          status: item.status || sceneState.status || 'queued',
          syncStatus: sceneState.status || '',
          error: item.error || '',
          imageUrl: item.imageUrl || sceneState.imageUrl || '',
        });
      });

      if (!prompts.length) {
        Object.keys(S.scenes || {}).forEach(function(key) {
          var sc = S.scenes[key];
          var pid = sc && sc.projectId ? sc.projectId : (key.indexOf('|') > -1 ? key.split('|')[0] : '');
          if (pid !== projectId) return;
          prompts.push({
            scene: String(key.indexOf('|') > -1 ? key.split('|')[1] : key),
            prompt: sc.prompt || '',
            status: sc.status || 'pending',
            syncStatus: sc.status || '',
            error: sc.error || '',
            imageUrl: sc.imageUrl || '',
          });
        });
      }

      prompts.sort(function(a, b) {
        var na = parseInt(a.scene, 10);
        var nb = parseInt(b.scene, 10);
        if (isNaN(na) || isNaN(nb)) return String(a.scene).localeCompare(String(b.scene));
        return na - nb;
      });
      return prompts;
    }

    function summarizeProjectHistory(projectId) {
      var prompts = buildProjectHistoryPrompts(projectId);
      var completedCount = 0;
      var failedCount = 0;
      var runningCount = 0;
      var queuedCount = 0;

      prompts.forEach(function(prompt) {
        var status = prompt.status || prompt.syncStatus || 'queued';
        if (status === 'completed' || status === 'done' || status === 'saved' || status === 'downloaded') completedCount++;
        else if (status === 'error' || status === 'failed') failedCount++;
        else if (status === 'typing' || status === 'generating' || status === 'uploading') runningCount++;
        else queuedCount++;
      });

      return {
        prompts: prompts,
        sceneCount: prompts.length,
        completedCount: completedCount,
        failedCount: failedCount,
        runningCount: runningCount,
        queuedCount: queuedCount,
      };
    }

    function ensureHistoryEntry(projectId, options) {
      options = options || {};
      var entry = null;
      var now = Date.now();
      var i;

      if (options.id) {
        for (i = 0; i < S.history.items.length; i++) {
          if (S.history.items[i].id === options.id) {
            entry = S.history.items[i];
            break;
          }
        }
      }

      if (!entry && !options.forceNew && S.history.activeId) {
        for (i = 0; i < S.history.items.length; i++) {
          if (S.history.items[i].id === S.history.activeId && S.history.items[i].projectId === projectId) {
            entry = S.history.items[i];
            break;
          }
        }
      }

      if (!entry && !options.forceNew) {
        for (i = 0; i < S.history.items.length; i++) {
          if (S.history.items[i].projectId === projectId && !isFinalHistoryStatus(S.history.items[i].status)) {
            entry = S.history.items[i];
            break;
          }
        }
      }

      if (!entry) {
        entry = {
          id: (projectId || 'PROJECT') + '|' + now,
          projectId: projectId || 'Unknown',
          source: options.source || 'job',
          createdAt: now,
          startedAt: null,
          endedAt: null,
          updatedAt: now,
          status: 'queued',
          aspectRatio: '',
          prompts: [],
          sceneCount: 0,
          completedCount: 0,
          failedCount: 0,
          runningCount: 0,
          queuedCount: 0,
          durationMs: 0,
        };
        S.history.items.unshift(entry);
      }

      if (options.activate !== false) S.history.activeId = entry.id;
      return entry;
    }

    function deriveHistoryStatus(entry, summary) {
      if (summary.runningCount > 0) return 'running';
      if (summary.sceneCount > 0 && summary.completedCount + summary.failedCount >= summary.sceneCount) {
        if (summary.failedCount > 0 && summary.completedCount > 0) return 'completed_with_errors';
        if (summary.failedCount > 0) return 'failed';
        return 'completed';
      }
      if (summary.failedCount > 0) return 'error';
      if (isFinalHistoryStatus(entry.status)) return entry.status;
      return 'queued';
    }

    function updateHistoryEntry(projectId, options) {
      if (!projectId) return null;
      options = options || {};
      var now = Date.now();
      var entry = ensureHistoryEntry(projectId, options);
      var summary = summarizeProjectHistory(projectId);

      entry.projectId = projectId;
      entry.source = options.source || entry.source || 'job';
      entry.aspectRatio = options.aspectRatio !== undefined ? options.aspectRatio : (entry.aspectRatio || S.aspectRatio || '');
      entry.prompts = summary.prompts.length ? summary.prompts : (entry.prompts || []);
      entry.sceneCount = summary.sceneCount || entry.sceneCount || entry.prompts.length || 0;
      entry.completedCount = summary.completedCount;
      entry.failedCount = summary.failedCount;
      entry.runningCount = summary.runningCount;
      entry.queuedCount = summary.queuedCount;

      if (options.startedAt && !entry.startedAt) entry.startedAt = options.startedAt;
      if (!entry.startedAt && options.status === 'running') entry.startedAt = now;
      if (!entry.startedAt && summary.runningCount > 0) entry.startedAt = now;
      if (options.endedAt !== undefined) entry.endedAt = options.endedAt;

      entry.status = options.status || deriveHistoryStatus(entry, summary);
      entry.updatedAt = now;
      entry.durationMs = Math.max(0, (entry.endedAt || now) - (entry.startedAt || entry.createdAt || now));

      persistHistoryEntries();
      if (isFinalHistoryStatus(entry.status) && S.history.activeId === entry.id) S.history.activeId = null;
      return entry;
    }

    function updateHistoryForProjects(projectIds, options) {
      (projectIds || []).forEach(function(projectId) {
        updateHistoryEntry(projectId, options);
      });
    }

    function formatHistoryDuration(ms) {
      ms = Math.max(0, ms || 0);
      var totalSeconds = Math.floor(ms / 1000);
      var hours = Math.floor(totalSeconds / 3600);
      var minutes = Math.floor((totalSeconds % 3600) / 60);
      var seconds = totalSeconds % 60;
      if (hours > 0) return hours + 'h ' + minutes + 'm';
      if (minutes > 0) return minutes + 'm ' + seconds + 's';
      return seconds + 's';
    }

    function formatHistoryTimestamp(ts) {
      if (!ts) return '-';
      return new Date(ts).toLocaleString([], {
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
      });
    }

    function formatHistoryAge(ts) {
      if (!ts) return '';
      var diff = Math.max(0, Date.now() - ts);
      var minutes = Math.floor(diff / 60000);
      if (minutes < 1) return 'just now';
      if (minutes < 60) return minutes + 'm ago';
      var hours = Math.floor(minutes / 60);
      if (hours < 24) return hours + 'h ago';
      return Math.floor(hours / 24) + 'd ago';
    }

    function getHistoryBadge(entry) {
      if (!entry) return { cls: 'sts-badge-pending', text: 'queued' };
      if (entry.status === 'running') return { cls: 'sts-badge-generating', text: 'running' };
      if (entry.status === 'completed') return { cls: 'sts-badge-done', text: 'completed' };
      if (entry.status === 'completed_with_errors') return { cls: 'sts-badge-mixed', text: 'done with errors' };
      if (entry.status === 'failed') return { cls: 'sts-badge-error', text: 'failed' };
      if (entry.status === 'stopped') return { cls: 'sts-badge-stopped', text: 'stopped' };
      if (entry.status === 'cleared') return { cls: 'sts-badge-stopped', text: 'cleared' };
      return { cls: 'sts-badge-pending', text: entry.status || 'queued' };
    }

    function isHistoryExpanded(entryId) {
      return !!(entryId && S.history.expanded && S.history.expanded[entryId]);
    }

    S.history.items = loadHistoryEntries();

    function doCountdown(seconds, type) {
      return new Promise(function(resolve) {
        S.typing.countdown = seconds;
        S.typing.countdownType = type;
        render();
        var remaining = seconds;
        var iv = setInterval(function() {
          remaining--;
          if (remaining <= 0 || S.typing.stopRequested) {
            clearInterval(iv);
            S.typing.countdown = 0;
            S.typing.countdownType = '';
            render();
            resolve();
            return;
          }
          S.typing.countdown = remaining;
          render();
        }, 1000);
      });
    }

    function smartClick(el) {
      if (!el) return;
      var events = ['pointerover','mouseover','pointerdown','mousedown','pointerup','mouseup','click'];
      for (var i = 0; i < events.length; i++) {
        el.dispatchEvent(new MouseEvent(events[i], {
          bubbles: true, cancelable: true, composed: true, view: window, detail: 1
        }));
      }
    }

    // ── WebSocket (proxied via background service worker) ──
    // Port keeps the service worker alive. sendMessage handles all communication.

    // Keep service worker alive with a persistent port + receive WS messages
    (function keepAlive() {
      try {
        var port = chrome.runtime.connect({ name: 'sts-gemini-alive' });
        port.onMessage.addListener(function(msg) {
          if (msg.type === 'STS_WS_MESSAGE') {
            if (!S.wsConnected) { S.wsConnected = true; S.connected = true; render(); }
            try { handleWSMessage(msg.payload); } catch(e) { console.warn('[STS WS] Bad port msg:', e); }
          } else if (msg.type === 'STS_WS_STATUS') {
            S.wsConnected = msg.connected;
            S.connected = msg.connected;
            if (msg.wsUrl) S.wsUrl = msg.wsUrl;
            render();
          }
        });
        port.onDisconnect.addListener(function() { setTimeout(keepAlive, 1000); });
      } catch(e) { setTimeout(keepAlive, 2000); }
    })();

    // Receive WS messages + status pushed from background
    chrome.runtime.onMessage.addListener(function(msg, sender, sendResponse) {
      if (msg.action === 'STS_WS_MESSAGE') {
        if (!S.wsConnected) { S.wsConnected = true; S.connected = true; render(); }
        try { handleWSMessage(msg.payload); } catch(e) { console.warn('[STS WS] Bad msg:', e); }
      } else if (msg.action === 'STS_WS_STATUS') {
        S.wsConnected = msg.connected;
        S.connected = msg.connected;
        if (msg.wsUrl) S.wsUrl = msg.wsUrl;
        render();
      }
    });

    // Poll background for WS status every 2s
    setInterval(function() {
      try {
        chrome.runtime.sendMessage({ action: 'STS_WS_GET_STATUS' }, function(resp) {
          if (chrome.runtime.lastError || !resp) return;
          S.wsConnected = resp.connected;
          S.connected = resp.connected;
          if (resp.wsUrl) S.wsUrl = resp.wsUrl;
          render();
        });
      } catch(e) {}
    }, 2000);

    function connectWS() {
      var manualUrl = localStorage.getItem('sts-gemini-ws-manual') || null;
      try { chrome.runtime.sendMessage({ action: 'STS_WS_RECONNECT', manualUrl: manualUrl }); } catch(e) {}
    }

    function sendWS(msg) {
      try { chrome.runtime.sendMessage({ action: 'STS_WS_SEND', payload: msg }); } catch(e) {}
    }

    function handleWSMessage(msg) {
      switch (msg.type) {
        case 'IMAGE_JOB': {
          var prevProjectId = S.projectId;
          S.projectId = msg.projectId;
          S.aspectRatio = msg.aspectRatio || S.aspectRatio || '';
          var scenes = msg.scenes || [];
          var pid = msg.projectId;
          var isNewProject = prevProjectId && prevProjectId !== pid;
          console.log('[STS WS] IMAGE_JOB:', pid, '-', scenes.length, 'scenes', 'aspect:', S.aspectRatio, isNewProject ? '(NEW PROJECT)' : '');

          // Click "New chat" for each new project to get a fresh conversation
          var setupPromise = isNewProject
            ? clickNewChat().then(function() { S.typing.toolsEnabled = false; })
            : Promise.resolve();

          setupPromise.then(function() {
            for (var si = 0; si < scenes.length; si++) {
              var sc = scenes[si];
              var k = String(sc.scene);
              var queueKey = pid + '|' + k; // Unique key per project+scene
              var scAspect = sc.aspectRatio || S.aspectRatio || '';
              // Populate scenes for sync tab
              if (!S.scenes[queueKey]) {
                S.scenes[queueKey] = { prompt: sc.prompt, status: 'pending', imageUrl: null, projectId: pid };
              }
              var exists = false;
              for (var qi = 0; qi < S.typing.queue.length; qi++) {
                if (S.typing.queue[qi].queueKey === queueKey) { exists = true; break; }
              }
              if (!exists) {
                S.typing.queue.push({
                  scene: k, queueKey: queueKey, projectId: pid,
                  displayPrompt: sc.prompt,
                  aspectRatio: scAspect,
                  fullPrompt: decorateGeminiPrompt(sc.prompt),
                  selected: true, status: 'queued', error: null,
                });
              }
            }
            updateHistoryEntry(pid, { source: 'job', status: 'queued', aspectRatio: S.aspectRatio });
            render();
            sendWS({ type: 'JOB_RECEIVED', projectId: pid, scenes: scenes.length });
            chrome.runtime.sendMessage({ type: 'ACTIVATE_TAB' });
            if (msg.autoType && !S.typing.active && !S.typing.starting) {
              console.log('[STS WS] Auto-starting typing');
              setTimeout(function() { startTyping(); }, 2000);
            }
          });
          break;
        }
        case 'ACTIVATE_TAB':
          chrome.runtime.sendMessage({ type: 'ACTIVATE_TAB' });
          break;
        case 'FOCUS_STUDIO_TAB':
          try { chrome.runtime.sendMessage({ type: 'FOCUS_STUDIO_TAB' }); } catch (e) {}
          break;
        case 'STOP_TYPING':
          console.log('[STS WS] STOP_TYPING received from server');
          if (S.typing.active || S.typing.starting) stopTyping();
          break;
        case 'PONG': break;
      }
    }

    // ── Click "New chat" for a fresh conversation ────
    function clickNewChat() {
      return new Promise(function(resolve) {
        // Primary: the exact selector from the Gemini sidebar
        var newChatBtn = document.querySelector('side-nav-action-button a[data-test-id="expanded-button"][href="/app"]');
        // Fallback: any link with aria-label "New chat"
        if (!newChatBtn) newChatBtn = document.querySelector('a[aria-label="New chat"]');
        // Fallback: mat-icon with edit_square
        if (!newChatBtn) {
          var icon = document.querySelector('mat-icon[fonticon="edit_square"]');
          if (icon) newChatBtn = icon.closest('a') || icon.closest('button');
        }
        if (newChatBtn) {
          console.log('[STS Gemini] Clicking "New chat" for fresh conversation');
          smartClick(newChatBtn);
          // Wait for the new chat page to load
          setTimeout(resolve, 2000);
        } else {
          console.warn('[STS Gemini] "New chat" button not found — may already be on a fresh page');
          resolve();
        }
      });
    }

    // ── Enable Image Tool (once) ─────────────────────
    function enableImageTool() {
      return new Promise(function(resolve) {
        if (S.typing.toolsEnabled) { resolve(); return; }
        console.log('Enabling image generation tool...');
        var toolsBtn = document.querySelector('button.toolbox-drawer-button');
        if (!toolsBtn) {
          var icon = document.querySelector('button mat-icon[fonticon="page_info"]');
          if (icon) toolsBtn = icon.closest('button');
        }
        if (!toolsBtn) {
          console.warn('Tools button not found - may already be in image mode');
          S.typing.toolsEnabled = true; resolve(); return;
        }
        smartClick(toolsBtn);
        setTimeout(function() {
          var createImgBtn = document.querySelector('#toolbox-drawer-menu toolbox-drawer-item:first-child button');
          if (!createImgBtn) {
            var imgIcon = document.querySelector('mat-icon[fonticon="photo_prints"]');
            if (imgIcon) createImgBtn = imgIcon.closest('button');
          }
          if (createImgBtn) {
            var isChecked = createImgBtn.getAttribute('aria-checked');
            if (isChecked !== 'true') { smartClick(createImgBtn); console.log('Create Image tool enabled'); }
            else { console.log('Create Image tool already active'); }
          } else { console.warn('Create Image button not found'); }
          setTimeout(function() {
            var tbAgain = document.querySelector('button.toolbox-drawer-button');
            if (tbAgain && tbAgain.classList.contains('menu-open')) smartClick(tbAgain);
            S.typing.toolsEnabled = true; resolve();
          }, 300);
        }, 500);
      });
    }

    // ── Type into Gemini (execCommand pattern) ───────
    function findGeminiInput() {
      var selectors = [
        '.ql-editor.textarea',
        'div[aria-label="Enter a prompt here"]',
        'rich-textarea .ql-editor[contenteditable="true"]',
        '.ql-editor[contenteditable="true"]',
        'div[contenteditable="true"][role="textbox"]',
      ];
      for (var si = 0; si < selectors.length; si++) {
        var el = document.querySelector(selectors[si]);
        if (el) return el;
      }
      return null;
    }

    function typeIntoGemini(text) {
      return new Promise(function(resolve, reject) {
        var inputEl = findGeminiInput();
        if (!inputEl) { reject(new Error('Gemini text input not found')); return; }

        console.log('[TYPE] Focusing input...');
        inputEl.focus();
        setTimeout(function() {
          // Re-verify focus is on the input
          if (document.activeElement !== inputEl) {
            console.log('[TYPE] Focus drifted, re-focusing...');
            inputEl.focus();
          }

          console.log('[TYPE] Clearing content...');
          // Select all within the editor, then delete
          var range = document.createRange();
          range.selectNodeContents(inputEl);
          var sel = window.getSelection();
          sel.removeAllRanges();
          sel.addRange(range);
          document.execCommand('delete', false, null);

          setTimeout(function() {
            // Ensure focus is still on input before inserting
            if (document.activeElement !== inputEl) inputEl.focus();

            console.log('[TYPE] Inserting text (' + text.length + ' chars)...');
            var success = document.execCommand('insertText', false, text);
            console.log('[TYPE] execCommand insertText result:', success);
            if (!success) {
              console.log('[TYPE] Fallback: setting innerText');
              inputEl.innerText = text;
              inputEl.dispatchEvent(new Event('input', { bubbles: true }));
            }

            setTimeout(function() {
              var editorText = inputEl.textContent || '';
              var landed = editorText.trim().length;
              var expected = text.trim().length;
              console.log('[TYPE] Editor content: ' + landed + '/' + expected + ' chars');
              // Accept if at least 80% of text landed (minor whitespace diffs are ok)
              if (landed < Math.min(expected * 0.8, expected - 20)) {
                reject(new Error('Prompt partially landed (' + landed + '/' + expected + ' chars)'));
                return;
              }
              console.log('[TYPE] Done. Text in editor, NOT submitting yet.');
              resolve();
            }, 500);
          }, 200);
        }, 300);
      });
    }

    // ── Wait for Gemini to be idle before submitting ──
    function waitForGeminiIdle(timeoutMs) {
      timeoutMs = timeoutMs || 60000;
      return new Promise(function(resolve) {
        if (!isGeminiGenerating()) { resolve(); return; }
        console.log('[IDLE] Waiting for Gemini to finish current generation...');
        var start = Date.now();
        var poll = setInterval(function() {
          if (!isGeminiGenerating()) {
            clearInterval(poll);
            console.log('[IDLE] Gemini is idle after ' + ((Date.now() - start) / 1000).toFixed(1) + 's');
            resolve();
            return;
          }
          if (Date.now() - start > timeoutMs) {
            clearInterval(poll);
            console.warn('[IDLE] Timed out waiting for Gemini to be idle after ' + (timeoutMs / 1000) + 's');
            resolve();
          }
        }, 500);
      });
    }

    // ── Submit ────────────────────────────────────────
    function findSendButton() {
      // Find the send button, ensuring it's NOT in Stop state
      var btn = document.querySelector('button.send-button[aria-label="Send message"]');
      if (!btn) btn = document.querySelector('button.send-button[aria-label*="Send"]');
      if (!btn) btn = document.querySelector('button.send-button');
      if (!btn) return null;
      // Reject if button is in Stop state (same button toggles send/stop)
      var label = (btn.getAttribute('aria-label') || '').toLowerCase();
      var stopIcon = btn.querySelector('mat-icon[fonticon="stop"]');
      if (label.indexOf('stop') !== -1 || stopIcon) return null;
      return btn;
    }

    function submitPrompt() {
      return new Promise(function(resolve, reject) {
        console.log('[SUBMIT] Looking for Send button...');

        // Poll for an enabled Send button (Angular may be re-rendering)
        var attempts = 0;
        var maxAttempts = 20; // 20 x 250ms = 5s max wait
        var findPoll = setInterval(function() {
          attempts++;
          var sendBtn = findSendButton();

          if (sendBtn && !sendBtn.disabled && sendBtn.getAttribute('aria-disabled') !== 'true') {
            clearInterval(findPoll);
            console.log('[SUBMIT] Send button found (attempt ' + attempts + '): aria-label=' + sendBtn.getAttribute('aria-label'));
            smartClick(sendBtn);
            console.log('[SUBMIT] Clicked Send button');

            // Wait for Gemini to accept the prompt
            var start = Date.now();
            var checkInterval = setInterval(function() {
              var thinkingAvatar = document.querySelector('.bard-avatar.thinking');
              var processing = document.querySelector('.processing-state_container--processing');
              var stopBtn = document.querySelector('button[aria-label="Stop response"]');
              var stopIcon = document.querySelector('button.send-button mat-icon[fonticon="stop"]');

              if (thinkingAvatar || processing || stopBtn || stopIcon) {
                clearInterval(checkInterval);
                console.log('[SUBMIT] Gemini accepted prompt —',
                  thinkingAvatar ? 'avatar thinking' : '',
                  processing ? 'processing state' : '',
                  (stopBtn || stopIcon) ? 'stop button' : '');
                resolve();
                return;
              }

              if (Date.now() - start > 10000) {
                clearInterval(checkInterval);
                console.warn('[SUBMIT] No thinking state after 10s — proceeding anyway');
                resolve();
              }
            }, 300);
            return;
          }

          if (attempts >= maxAttempts) {
            clearInterval(findPoll);
            // Check if it's specifically in Stop state vs just missing
            var anyBtn = document.querySelector('button.send-button');
            var reason = anyBtn ? 'Send button is in Stop state (Gemini still generating)' : 'Send button not found or disabled';
            console.log('[SUBMIT] ' + reason + ' (after ' + attempts + ' attempts)');
            reject(new Error(reason));
          }
        }, 250);
      });
    }

    // ── Rate limit detection & countdown ──────────
    function checkRateLimit() {
      // Look for the quota disclaimer element
      var disclaimer = document.querySelector('image-generation-quota-disclaimer');
      if (!disclaimer) return null;

      // Check all text content inside disclaimer for rate limit messages
      var allText = disclaimer.textContent || '';
      if (allText.indexOf('reached your image generation limit') === -1) return null;

      // Extract reset time — supports both formats:
      //   "Your limit resets on Mar 24, 6:17 PM."
      //   "You've reached your image generation limit until Mar 30, 11:34 AM."
      var textEl = disclaimer.querySelector('.main-text span') || disclaimer.querySelector('.main-text');
      var rawText = textEl ? textEl.textContent.trim() : allText;
      var resetTime = null;

      // Try "until <date>" format first (newer Gemini)
      var match = rawText.match(/until\s+(.+?)\.?\s*$/);
      // Fallback to "resets on <date>" format
      if (!match) match = rawText.match(/resets on\s+(.+?)\./);

      if (match) {
        try {
          var dateStr = match[1].trim();
          var year = new Date().getFullYear();
          resetTime = new Date(dateStr + ' ' + year);
          // If parsed date is in the past, try next year
          if (resetTime < new Date()) resetTime = new Date(dateStr + ' ' + (year + 1));
          // Sanity: if still invalid, null it
          if (isNaN(resetTime.getTime())) resetTime = null;
        } catch(e) { /* parsing failed */ }
      }

      console.log('[RATE LIMIT] Detected! Reset:', resetTime ? resetTime.toLocaleString() : 'unknown', '| Raw:', rawText);
      return { resetTime: resetTime, text: rawText };
    }

    function waitForRateLimitReset(resetTime) {
      return new Promise(function(resolve) {
        console.log('[RATE LIMIT] Waiting until', resetTime ? resetTime.toLocaleString() : 'unknown');
        S.typing.rateLimited = true;
        render();

        var checkInterval = setInterval(function() {
          // Update countdown in panel
          render();

          // Check if rate limit is gone
          var stillLimited = checkRateLimit();
          if (!stillLimited) {
            clearInterval(checkInterval);
            console.log('[RATE LIMIT] Limit cleared!');
            S.typing.rateLimited = false;
            S.typing.rateLimitReset = null;
            render();
            resolve();
            return;
          }

          // Also resolve if we're past the reset time
          if (resetTime && new Date() > resetTime) {
            clearInterval(checkInterval);
            console.log('[RATE LIMIT] Past reset time, refreshing page...');
            S.typing.rateLimited = false;
            window.location.reload();
            resolve();
            return;
          }

          if (S.typing.stopRequested) {
            clearInterval(checkInterval);
            S.typing.rateLimited = false;
            resolve();
          }
        }, 5000); // Check every 5 seconds
      });
    }

    function formatCountdown(targetDate) {
      if (!targetDate) return '??:??:??';
      var diff = targetDate - new Date();
      if (diff <= 0) return '00:00:00';
      var h = Math.floor(diff / 3600000);
      var m = Math.floor((diff % 3600000) / 60000);
      var s = Math.floor((diff % 60000) / 1000);
      return (h < 10 ? '0' : '') + h + ':' + (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
    }

    // ── Generation detection (from Gemini Automator) ─
    function isGeminiGenerating() {
      // The MOST reliable indicators that Gemini is actively generating RIGHT NOW:
      //
      // 1. Stop button visible — Gemini swaps the Send button to a Stop button
      //    while generating. This is the strongest signal.
      var stopBtn = document.querySelector('button[aria-label="Stop response"]');
      if (stopBtn) return true;
      var stopIcon = document.querySelector('button.send-button mat-icon[fonticon="stop"]');
      if (stopIcon) return true;

      // 2. Active processing state — but only if it's the LAST one in the DOM
      //    (prior conversation containers may still have processing-state elements
      //    that never got cleaned up — those are false positives)
      var processingStates = document.querySelectorAll('processing-state:not([hidden])');
      if (processingStates.length > 0) {
        var lastPS = processingStates[processingStates.length - 1];
        // Only count if it's also marked as actively processing
        var container = lastPS.querySelector('.processing-state_container--processing');
        if (container) return true;
      }

      // NOTE: We deliberately do NOT check for:
      //   - response-element.pending/.animating (persists from prior scenes)
      //   - .attachment-container.generated-images.pending (stale)
      //   - generated-image .loader (image skeleton lingers after completion)
      // These cause false positives and stall the typing pipeline for 60s.

      return false;
    }

    function isValidImageSrc(src) {
      return src && (src.indexOf('http') === 0 || src.indexOf('blob:') === 0);
    }

    function findImageInContainer(container) {
      if (!container) return null;
      // Based on DOM activity analysis, the reliable lifecycle is:
      //   1. aria-busy="false" on markdown div (generation done)
      //   2. src gets blob: URL on <img> (image available)
      //   3. class "image" → "image loaded" (final render)
      // We accept ANY img with a blob: src — don't require .loaded class
      // because .loaded appears much later and causes timeouts.

      // Strategy 1: img with blob: src inside single-image (most reliable)
      var imgs = container.querySelectorAll('single-image img');
      for (var i = imgs.length - 1; i >= 0; i--) {
        if (imgs[i].src && imgs[i].src.indexOf('blob:') === 0) {
          console.log('[IMAGE] Found blob src in single-image img' + (imgs[i].classList.contains('loaded') ? ' (loaded)' : ' (not yet loaded)'));
          return imgs[i].src;
        }
      }
      // Strategy 2: img with blob: src inside generated-image
      var genImgs = container.querySelectorAll('generated-image img');
      for (var j = genImgs.length - 1; j >= 0; j--) {
        if (genImgs[j].src && genImgs[j].src.indexOf('blob:') === 0) {
          console.log('[IMAGE] Found blob src in generated-image img');
          return genImgs[j].src;
        }
      }
      // Strategy 3: any img with blob: or googleusercontent src
      var allImgs = container.querySelectorAll('img');
      for (var k = allImgs.length - 1; k >= 0; k--) {
        var s = allImgs[k].src;
        if (s && (s.indexOf('blob:') === 0 || s.indexOf('googleusercontent.com') !== -1)) {
          console.log('[IMAGE] Found img via fallback');
          return s;
        }
      }
      return null;
    }

    // Scene-to-container index mapping (set after each submit)
    var sceneContainerMap = {};

    var _capturedContainerIds = {};

    function captureContainerForScene(sceneKey) {
      var attempts = 0;
      var maxAttempts = 60; // 60 x 500ms = 30s max wait

      var poll = setInterval(function() {
        attempts++;
        // Only match REAL containers (div.conversation-container), NOT pending-request
        var containers = document.querySelectorAll('div.conversation-container');

        // Look for a container we haven't captured yet (by its id attribute)
        for (var i = containers.length - 1; i >= 0; i--) {
          var c = containers[i];
          var cId = c.id;
          if (!cId) continue; // Skip containers without a real id
          if (!_capturedContainerIds[cId]) {
            clearInterval(poll);
            _capturedContainerIds[cId] = sceneKey;
            sceneContainerMap[sceneKey] = c;
            console.log('[TRACK] Mapped scene ' + sceneKey + ' to container id=' + cId + ' (attempt ' + attempts + ')');
            injectSceneBadge(c, sceneKey);
            return;
          }
        }

        if (attempts >= maxAttempts) {
          clearInterval(poll);
          // Do NOT fallback to last container — it may belong to another scene.
          // waitForImageGeneration handles unmapped containers with a 30s timeout.
          console.error('[TRACK] Could not find new container for scene ' + sceneKey + ' after ' + (maxAttempts * 0.5) + 's');
        }
      }, 500);
    }

    function injectSceneBadge(container, sceneKey) {
      if (!container) return;
      var wrapperId = 'sts-badge-' + sceneKey;
      if (document.getElementById(wrapperId)) return;

      // Find the user-query element inside this conversation-container
      // Angular won't re-render user queries after submit, so this is stable
      var userQuery = container.querySelector('user-query');
      if (!userQuery) return;

      var badge = document.createElement('div');
      badge.id = wrapperId;
      badge.className = 'sts-scene-badge';
      badge.textContent = '[' + S.projectId + '|' + sceneKey + ']';
      badge.style.cssText = 'background:#00d4aa;color:#0d1117;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:700;font-family:monospace;display:inline-block;margin:4px 8px;';

      // Append inside user-query — each prompt gets its own badge
      userQuery.appendChild(badge);
    }

    // Known Gemini refusal phrases — text-only responses that won't produce an image.
    // Match must be confident (specific phrasing) to avoid false positives on captions/explanations.
    var REFUSAL_PATTERNS = [
      /i can[''']?t (?:create|generate|make|produce|depict|show|help)/i,
      /i (?:can ?not|cannot) (?:create|generate|make|produce|depict|show|help)/i,
      /i[''']?m (?:not able|unable) to (?:create|generate|make|produce|depict|show|help)/i,
      /i am (?:not able|unable) to (?:create|generate|make|produce|depict|show|help)/i,
      /i (?:won[''']?t|will not) (?:be able to )?(?:create|generate|depict)/i,
      /can[''']?t (?:create|generate) (?:images|an image|that image)/i,
      /but i (?:can[''']?t|cannot) depict (?:them|that|him|her|it) like that/i,
      /(?:against|violates?) (?:my|our|the) (?:guidelines|policies|policy)/i,
      /unable to (?:fulfill|complete) (?:this|that|your) request/i
    ];
    function isRefusalText(text) {
      for (var i = 0; i < REFUSAL_PATTERNS.length; i++) {
        if (REFUSAL_PATTERNS[i].test(text)) return true;
      }
      return false;
    }

    function waitForImageGeneration(timeoutMs, projectId, sceneNum) {
      timeoutMs = timeoutMs || 180000;
      return new Promise(function(resolve) {
        var start = Date.now();
        var label = projectId + '|' + sceneNum;
        var doneSignalSeen = 0; // timestamp when aria-busy=false first seen
        console.log('[IMAGE] Waiting for image for scene ' + label + ' (timeout: ' + (timeoutMs / 1000) + 's)');

        var checkInterval = setInterval(function() {
          // Only use the mapped container — never fall back to "last container"
          // which could belong to a different scene
          var container = sceneContainerMap[sceneNum];
          var elapsed = Date.now() - start;

          // If container not mapped yet, just wait (captureContainerForScene is polling)
          if (!container) {
            if (elapsed > 30000) {
              clearInterval(checkInterval);
              console.error('[IMAGE] Container never mapped for scene ' + label + ' after 30s');
              resolve(null);
              return;
            }
            return;
          }

          // ── Fast-fail checks ──
          // Detect stopped responses
          var stoppedDraft = container.querySelector('[data-test-draft-id*="stopped"]');
          if (stoppedDraft) {
            clearInterval(checkInterval);
            console.error('[IMAGE] Response was stopped for scene ' + label);
            resolve(null);
            return;
          }

          // Detect Gemini refusal (text response without any image/generated-image element)
          var modelResponse = container.querySelector('model-response');
          if (modelResponse) {
            // ── Check for image ──
            var img = findImageInContainer(modelResponse);
            if (img) {
              clearInterval(checkInterval);
              console.log('[IMAGE] Found for scene ' + label + ':', img.substring(0, 80) + '...');
              resolve(img);
              return;
            }

            // ── Fast refusal detection ──
            // Gemini sometimes responds text-only with a refusal (e.g. content-policy hit on minors).
            // If we see refusal phrasing in structured-content-container and there's no generated-image
            // element, fail immediately and pause the queue (retrying won't change a refusal).
            var hasGenImgYet = container.querySelector('generated-image');
            if (!hasGenImgYet) {
              var scc = modelResponse.querySelector('structured-content-container .markdown, structured-content-container message-content');
              var refusalText = scc ? (scc.innerText || scc.textContent || '').trim() : '';
              if (refusalText && refusalText.length > 10 && isRefusalText(refusalText)) {
                clearInterval(checkInterval);
                console.error('[IMAGE] Refusal detected for scene ' + label + ': ' + refusalText.slice(0, 200));
                resolve({ refused: true, reason: refusalText.slice(0, 300) });
                return;
              }
            }

            // ── Loader skeleton still visible — image rendering, keep waiting ──
            var loaderEl = container.querySelector('generated-image .loader');
            if (loaderEl) {
              if (elapsed > 10000 && elapsed % 10000 < 1100) {
                console.log('[IMAGE] Loader skeleton present for scene ' + label + ' — waiting... (' + (elapsed / 1000).toFixed(0) + 's)');
              }
              return; // Skip all timeout checks
            }

            // ── Check "done" signals ──
            var markdownDiv = container.querySelector('.markdown[aria-busy="false"]');
            var footerDone = container.querySelector('.response-footer.complete, .response-footer.gap.complete');
            if (markdownDiv || footerDone) {
              if (!doneSignalSeen) {
                doneSignalSeen = Date.now();
                console.log('[IMAGE] Done signal detected for scene ' + label + ' — waiting up to 15s for image to appear...');
              }
              // Give 15s after done signal for image to render (blob URL may arrive late)
              if (Date.now() - doneSignalSeen > 15000) {
                clearInterval(checkInterval);
                // Check if Gemini refused — look for text-only response
                var hasGeneratedImage = container.querySelector('generated-image');
                if (!hasGeneratedImage) {
                  console.error('[IMAGE] Gemini responded with text only (no image element) for scene ' + label);
                } else {
                  console.error('[IMAGE] Done but no image blob found for scene ' + label);
                }
                resolve(null);
                return;
              }
            }
          }

          // ── Timeouts ──
          // Soft timeout: past limit and Gemini not actively generating
          if (elapsed > timeoutMs && !isGeminiGenerating()) {
            clearInterval(checkInterval);
            console.error('[IMAGE] Timed out for scene ' + label + ' (soft, ' + (elapsed / 1000).toFixed(0) + 's)');
            resolve(null);
            return;
          }
          // Hard timeout: 2x — give up no matter what
          if (elapsed > timeoutMs * 2) {
            clearInterval(checkInterval);
            console.error('[IMAGE] Timed out for scene ' + label + ' (hard, ' + (elapsed / 1000).toFixed(0) + 's)');
            resolve(null);
            return;
          }
        }, 1000);
      });
    }

    // ── Get image as base64 ─────────────────────────
    function fetchImageAsBase64(imageUrl) {
      console.log('[FETCH] Getting image as base64...');

      // Strategy 1: XHR from content script (uses page cookies automatically)
      return new Promise(function(resolve) {
        var xhr = new XMLHttpRequest();
        xhr.open('GET', imageUrl, true);
        xhr.responseType = 'blob';
        xhr.withCredentials = true;
        xhr.onload = function() {
          if (xhr.status === 200) {
            var blob = xhr.response;
            var reader = new FileReader();
            reader.onload = function() {
              var sizeKB = Math.round(blob.size / 1024);
              console.log('[FETCH] XHR success (' + sizeKB + ' KB, ' + blob.type + ')');
              resolve(reader.result);
            };
            reader.onerror = function() {
              console.warn('[FETCH] FileReader failed, trying background...');
              fetchViaBackground(imageUrl, resolve);
            };
            reader.readAsDataURL(blob);
          } else {
            console.warn('[FETCH] XHR returned ' + xhr.status + ', trying background...');
            fetchViaBackground(imageUrl, resolve);
          }
        };
        xhr.onerror = function() {
          console.warn('[FETCH] XHR failed, trying background...');
          fetchViaBackground(imageUrl, resolve);
        };
        xhr.send();
      });
    }

    function fetchViaBackground(imageUrl, resolve) {
      chrome.runtime.sendMessage(
        { action: 'FETCH_IMAGE_BASE64', url: imageUrl },
        function(response) {
          if (response && response.success) {
            var sizeKB = Math.round(response.data.length * 3 / 4 / 1024);
            console.log('[FETCH] Background fetch success (' + sizeKB + ' KB)');
            resolve(response.data);
          } else {
            console.error('[FETCH] All fetch methods failed:', response ? response.error : 'no response');
            resolve(null);
          }
        }
      );
    }

    // ── Main Typing Loop ─────────────────────────────
    function startTyping() {
      if (S.typing.active || S.typing.starting) return;
      var tq = S.typing.queue;
      if (!tq.length) { console.log('No prompts'); return; }
      S.typing.starting = true; S.typing.stopRequested = false;
      var runItems = [];
      for (var ri = 0; ri < tq.length; ri++) {
        if (tq[ri].selected && tq[ri].status !== 'completed') runItems.push(tq[ri]);
      }
      if (!runItems.length) {
        for (var rri = 0; rri < tq.length; rri++) { if (tq[rri].status === 'completed') tq[rri].status = 'queued'; }
        for (var rr2 = 0; rr2 < tq.length; rr2++) {
          if (tq[rr2].selected && tq[rr2].status !== 'completed') runItems.push(tq[rr2]);
        }
      }
      if (!runItems.length) { S.typing.starting = false; render(); return; }
      S.typing.runId++; S.typing.active = true; S.typing.starting = false; S.typing.typedCount = 0;
      updateHistoryForProjects(getUniqueProjectIds(runItems), { status: 'running', startedAt: Date.now() });
      render();
      console.log('=== Starting: ' + runItems.length + ' prompts ===');

      var seenImageUrls = {};
      document.querySelectorAll('img').forEach(function(img) {
        if (isValidImageSrc(img.src)) seenImageUrls[img.src] = true;
      });

      var idx = 0;
      function processNext() {
        if (S.typing.stopRequested || idx >= tq.length) {
          S.typing.active = false; S.typing.currentIndex = -1; render();
          var completed = 0, failed = 0;
          tq.forEach(function(q) { if (q.status === 'completed') completed++; if (q.status === 'error') failed++; });
          updateHistoryForProjects(getUniqueProjectIds(tq), {
            status: S.typing.stopRequested ? 'stopped' : null,
            endedAt: Date.now()
          });
          console.log('=== Done: ' + completed + ' ok, ' + failed + ' failed ===');
          // Notify server when all scenes are resolved (either completed or exhausted retries)
          if (completed + failed === tq.length) {
            sendWS({ type: 'JOB_COMPLETE', projectId: S.projectId, completed: completed, failed: failed });
            try { chrome.runtime.sendMessage({ type: 'FOCUS_STUDIO_TAB' }); } catch(e) {}
          }
          return;
        }
        var item = tq[idx];
        if (!item.selected || item.status === 'completed') { idx++; processNext(); return; }

        if (!item.retryCount) item.retryCount = 0;

        S.typing.currentIndex = idx; item.status = 'typing'; render();
        updateHistoryEntry(item.projectId || S.projectId, { status: 'running' });
        sendWS({ type: 'STATUS_UPDATE', scene: parseInt(item.scene), status: 'typing' });

        document.querySelectorAll('generated-image img.image.loaded').forEach(function(img) {
          if (img.src) seenImageUrls[img.src] = true;
        });

        // Check rate limit before starting
        var rateCheck = checkRateLimit();
        if (rateCheck) {
          S.typing.rateLimitReset = rateCheck.resetTime;
          item.status = 'queued'; render();
          waitForRateLimitReset(rateCheck.resetTime).then(function() {
            if (!S.typing.stopRequested) processNext(); // Retry same idx
          });
          return;
        }

        function handleSceneFailure(reason) {
          item.retryCount++;
          if (item.retryCount < 4 && !S.typing.stopRequested) {
            var retrySec = Math.ceil((3000 + (item.retryCount * 2000)) / 1000); // 5s, 7s, 9s
            console.log('[RETRY] Scene ' + item.scene + ' failed (' + reason + '), attempt ' + item.retryCount + '/4 — retrying in ' + retrySec + 's...');
            item.status = 'queued';
            item.error = reason + ' (retry ' + item.retryCount + '/4)';
            if (S.scenes[item.queueKey]) S.scenes[item.queueKey].status = 'pending';
            // Clear stale container mapping so retry gets a fresh mapping
            delete sceneContainerMap[item.scene];
            render();
            updateHistoryEntry(item.projectId || S.projectId, { status: 'running' });
            doCountdown(retrySec, 'retry').then(processNext); // Same idx — retry same scene
          } else {
            console.error('[RETRY] Scene ' + item.scene + ' failed after ' + item.retryCount + ' attempts: ' + reason);
            item.status = 'error';
            item.error = reason + (item.retryCount > 1 ? ' (after ' + item.retryCount + ' attempts)' : '');
            if (S.scenes[item.queueKey]) S.scenes[item.queueKey].status = 'error';
            render();
            updateHistoryEntry(item.projectId || S.projectId);
            idx++;
            doCountdown(3, 'next').then(processNext);
          }
        }

        waitForGeminiIdle(60000)
          .then(function() { return enableImageTool(); })
          .then(function() { console.log('[FLOW] Step 1: Typing prompt...'); return typeIntoGemini(item.fullPrompt); })
          .then(function() { return sleep(300); })
          .then(function() { console.log('[FLOW] Step 2: Submitting...'); return submitPrompt(); })
          .then(function() {
            // Start polling for the new conversation container (async, non-blocking)
            captureContainerForScene(item.scene);
          })
          .then(function() {
            // Check rate limit after submit (it may appear after trying to generate)
            return sleep(2000).then(function() {
              var postSubmitLimit = checkRateLimit();
              if (postSubmitLimit) {
                console.log('[FLOW] Rate limit hit after submit!');
                S.typing.rateLimitReset = postSubmitLimit.resetTime;
                item.status = 'queued'; render();
                return waitForRateLimitReset(postSubmitLimit.resetTime).then(function() {
                  return 'RATE_LIMITED';
                });
              }
              return null;
            });
          })
          .then(function(signal) {
            if (signal === 'RATE_LIMITED') {
              if (!S.typing.stopRequested) processNext(); // Retry same idx
              return Promise.reject('RATE_LIMITED_SKIP');
            }
          })
          .then(function() {
            item.status = 'generating';
            if (S.scenes[item.queueKey]) S.scenes[item.queueKey].status = 'generating';
            render();
            updateHistoryEntry(item.projectId || S.projectId, { status: 'running' });
            sendWS({ type: 'STATUS_UPDATE', scene: parseInt(item.scene), status: 'generating' });
            // Start DOM monitor on the last model-response container
            var containers = document.querySelectorAll('div.conversation-container');
            if (containers.length > 0) {
              var lastIdx = containers.length;
              startDOMMonitor('(//div[contains(@class,"conversation-container")])[' + lastIdx + ']//model-response');
            }
            return waitForImageGeneration(180000, item.projectId || S.projectId, item.scene);
          })
          .then(function(imageUrl) {
            stopDOMMonitor();
            if (S.typing.stopRequested) { item.status = 'queued'; return null; }
            // ── Refusal signal: pause queue, mark as non-retryable error ──
            if (imageUrl && typeof imageUrl === 'object' && imageUrl.refused) {
              var rsn = imageUrl.reason || 'Gemini refused';
              console.error('[FLOW] Scene ' + item.scene + ' refused — pausing typing. Reason: ' + rsn);
              item.status = 'error';
              item.error = 'Refused: ' + rsn;
              item.retryCount = 99; // prevent any retry
              if (S.scenes[item.queueKey]) S.scenes[item.queueKey].status = 'error';
              S.typing.stopRequested = true;
              S.typing.active = false;
              S.typing.currentIndex = -1;
              sendWS({ type: 'STATUS_UPDATE', scene: parseInt(item.scene), status: 'error', error: 'Refused: ' + rsn });
              render();
              updateHistoryForProjects(getUniqueProjectIds(tq), { status: 'stopped', endedAt: Date.now() });
              return Promise.reject('REFUSED_PAUSE');
            }
            if (imageUrl) {
              seenImageUrls[imageUrl] = true;
              if (S.scenes[item.queueKey]) S.scenes[item.queueKey].status = 'uploading';
              render();
              console.log('[FLOW] Scene ' + item.scene + ' image found, fetching base64...');
              return fetchImageAsBase64(imageUrl).then(function(b64) {
                if (b64) {
                  sendWS({ type: 'IMAGE_UPLOAD', projectId: item.projectId || S.projectId, scene: parseInt(item.scene),
                    image: { data: b64, source_url: imageUrl } });
                  item.status = 'completed'; item.imageUrl = imageUrl; S.typing.typedCount++;
                  item.retryCount = 0; // Reset on success
                  if (S.scenes[item.queueKey]) { S.scenes[item.queueKey].status = 'done'; S.scenes[item.queueKey].imageUrl = imageUrl; }
                  updateHistoryEntry(item.projectId || S.projectId);
                  console.log('Scene ' + item.scene + ' completed');
                } else {
                  return Promise.reject({ autoRetry: true, reason: 'Fetch failed' });
                }
              });
            } else {
              return Promise.reject({ autoRetry: true, reason: 'No image generated' });
            }
          })
          .then(function() {
            render(); idx++;
            var hasMore = tq.slice(idx).some(function(q) { return q.selected && q.status !== 'completed'; });
            if (hasMore && !S.typing.stopRequested) {
              var delaySec = Math.ceil((2000 + Math.floor(Math.random() * 4000)) / 1000); // 2-6 seconds
              console.log('Next in ' + delaySec + 's...');
              doCountdown(delaySec, 'next').then(processNext);
            } else { processNext(); }
          })
          .catch(function(e) {
            stopDOMMonitor();
            if (e === 'RATE_LIMITED_SKIP') return; // Already handled
            if (e === 'REFUSED_PAUSE') {
              // Refusal already recorded above; halt the queue and notify.
              try { chrome.runtime.sendMessage({ type: 'FOCUS_STUDIO_TAB' }); } catch(_e) {}
              return;
            }
            // Auto-retry for recoverable failures
            if (e && e.autoRetry) {
              handleSceneFailure(e.reason);
              return;
            }
            var msg = e.message || String(e);
            handleSceneFailure(msg);
          });
      }
      processNext();
    }

    function stopTyping() {
      S.typing.stopRequested = true;
      updateHistoryForProjects(getUniqueProjectIds(S.typing.queue), {
        status: 'stopped',
        endedAt: Date.now(),
        activate: false
      });
      render();
    }

    // ── DOM Monitor stubs ──
    // DOM observation is now handled by ai-web-auto platform (observe_start/observe_diff).
    // These stubs keep call sites working without the removed dom-activity-recorder.
    function startDOMMonitor(xpath) { return false; }
    function stopDOMMonitor() {}

    // ── UI ───────────────────────────────────────────
    function $id(id) { return document.getElementById(id); }
    function escHtml(s) { var d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
    function encodeCopyText(s) { return encodeURIComponent(String(s || '')); }

    // Wrap raw scene prompt with image-generation guidance + target aspect ratio.
    // Applied to both the text typed into Gemini and the "Copy" button payload.
    var GEMINI_PROMPT_PREFIX = 'Create a cinematic, high-quality image based on the following scene description:\n\n';
    var GEMINI_PROMPT_SUFFIX = '\n\nAspect ratio: 9:16.';
    function decorateGeminiPrompt(raw) {
      var value = String(raw || '').trim();
      if (!value) return '';
      return GEMINI_PROMPT_PREFIX + value + GEMINI_PROMPT_SUFFIX;
    }

    function copyText(text) {
      var value = String(text || '');
      if (!value.trim()) return Promise.reject(new Error('No prompt to copy'));
      if (navigator.clipboard && navigator.clipboard.writeText) {
        return navigator.clipboard.writeText(value).catch(function() {
          return fallbackCopy(value);
        });
      }
      return fallbackCopy(value);
    }

    function fallbackCopy(value) {
      return new Promise(function(resolve, reject) {
        var input = document.createElement('textarea');
        input.value = value;
        input.setAttribute('readonly', '');
        input.style.position = 'fixed';
        input.style.left = '-9999px';
        input.style.opacity = '0';
        document.body.appendChild(input);
        input.select();
        input.setSelectionRange(0, input.value.length);
        var copied = document.execCommand('copy');
        input.remove();
        copied ? resolve() : reject(new Error('Copy failed'));
      });
    }

    function flashCopyButton(button, label, cls) {
      if (!button) return;
      var original = button.getAttribute('data-default-label') || button.textContent || 'Copy';
      button.setAttribute('data-default-label', original);
      if (button._copyTimer) clearTimeout(button._copyTimer);
      button.textContent = label || 'Copied';
      button.classList.remove('copied', 'failed');
      if (cls) button.classList.add(cls);
      button._copyTimer = setTimeout(function() {
        button.textContent = original;
        button.classList.remove('copied', 'failed');
      }, 1200);
    }

    function hideImagePreview() {
      var preview = document.getElementById('sts-img-overlay');
      if (preview) preview.remove();
    }

    function moveImagePreview(e) {
      var preview = document.getElementById('sts-img-overlay');
      if (!preview || !e) return;
      var margin = 18;
      var offset = 20;
      var rect = preview.getBoundingClientRect();
      var left = e.clientX + offset;
      var top = e.clientY + offset;

      if (left + rect.width + margin > window.innerWidth) {
        left = e.clientX - rect.width - offset;
      }
      if (top + rect.height + margin > window.innerHeight) {
        top = e.clientY - rect.height - offset;
      }

      left = Math.max(margin, Math.min(left, window.innerWidth - rect.width - margin));
      top = Math.max(margin, Math.min(top, window.innerHeight - rect.height - margin));

      preview.style.left = left + 'px';
      preview.style.top = top + 'px';
    }

    function showImagePreview(src, e) {
      if (!src) return;
      var preview = document.getElementById('sts-img-overlay');
      if (!preview) {
        preview = document.createElement('div');
        preview.id = 'sts-img-overlay';
        preview.innerHTML = '<img alt="Scene preview">';
        document.body.appendChild(preview);
      }
      var img = preview.querySelector('img');
      if (!img) return;
      if (img.src !== src) img.src = src;
      if (e) moveImagePreview(e);
      img.onload = function() {
        moveImagePreview(e || { clientX: window.innerWidth / 2, clientY: window.innerHeight / 2 });
      };
    }

    function injectUI() {
      if (document.getElementById('sts-sync')) return;
      var root = document.createElement('div');
      root.id = 'sts-sync';
      root.innerHTML =
        '<!-- Collapsed Pill -->' +
        '<div class="sts-pill" id="sts-pill">' +
          '<div class="sts-pill-dot" id="sts-pill-dot"></div>' +
          '<span class="sts-pill-label">STS Gemini</span>' +
          '<span class="sts-pill-proj" id="sts-pill-proj"></span>' +
          '<div class="sts-pill-counts">' +
            '<span class="sts-pill-count-label">Q</span><span class="sts-c-pend" id="sts-pill-p">0</span>' +
            '<span class="sts-pill-count-label">R</span><span class="sts-c-rdy" id="sts-pill-r">0</span>' +
          '</div>' +
        '</div>' +
        '<!-- Expanded Panel -->' +
        '<div class="sts-panel" id="sts-panel" style="display:none;">' +
          '<!-- Header -->' +
          '<div class="sts-head">' +
            '<div class="sts-head-left">' +
              '<div class="sts-head-dot" id="sts-head-dot"></div>' +
              '<h3>STS Gemini</h3>' +
              '<span class="sts-head-port" id="sts-head-port" style="display:none;"></span>' +
              '<span class="sts-head-ar" id="sts-head-ar" style="display:none;"></span>' +
            '</div>' +
            '<div class="sts-head-btns">' +
              '<button class="sts-hb" id="sts-settings-btn" title="Settings">&#x2699;</button>' +
              '<button class="sts-hb" id="sts-collapse-btn" title="Collapse">&#x2715;</button>' +
            '</div>' +
          '</div>' +
          '<!-- Connection bar -->' +
          '<div class="sts-conn-bar" id="sts-conn-bar" style="display:none;">' +
            '<span id="sts-conn-icon"></span>' +
            '<span id="sts-conn-msg">Disconnected</span>' +
          '</div>' +
          '<!-- Rate limit -->' +
          '<div class="sts-rate-limit" id="sts-rate-limit" style="display:none;">' +
            '<span class="sts-rate-icon">&#x26A0;</span>' +
            '<div class="sts-rate-info">' +
              '<div class="sts-rate-title">Rate Limited</div>' +
              '<div class="sts-rate-sub" id="sts-rate-sub">Resets at --</div>' +
            '</div>' +
            '<div class="sts-rate-countdown" id="sts-rate-countdown">??:??:??</div>' +
          '</div>' +
          '<!-- Settings -->' +
          '<div class="sts-settings" id="sts-settings">' +
            '<label>WS URL</label>' +
            '<input type="text" class="sts-url-input" id="sts-url-input" />' +
            '<button class="sts-url-save" id="sts-url-save">Save</button>' +
            '<label class="sts-settings-toggle" title="Show or hide the TEST button">' +
              '<input type="checkbox" id="sts-show-test-toggle">' +
              '<span>Show TEST button</span>' +
            '</label>' +
          '</div>' +
          '<!-- Stats -->' +
          '<div class="sts-stats">' +
            '<div class="sts-stat"><span class="sts-sv sts-c-pend" id="sts-n-queue">0</span><span class="sts-sl">Queue</span></div>' +
            '<div class="sts-stat"><span class="sts-sv sts-c-done" id="sts-n-typed">0</span><span class="sts-sl">Typed</span></div>' +
            '<div class="sts-stat"><span class="sts-sv sts-c-rdy" id="sts-n-done">0</span><span class="sts-sl">Done</span></div>' +
            '<div class="sts-stat"><span class="sts-sv sts-c-sent" id="sts-n-sent">0</span><span class="sts-sl">Synced</span></div>' +
          '</div>' +
          '<!-- Tabs -->' +
          '<div class="sts-tabs">' +
            '<button class="sts-tab active" data-tab="typing">Typing</button>' +
            '<button class="sts-tab" data-tab="sync">Sync</button>' +
            '<button class="sts-tab" data-tab="history">History <span class="sts-tab-count" id="sts-history-tab-count">0</span></button>' +
          '</div>' +
          '<!-- Progress -->' +
          '<div class="sts-progress">' +
            '<div class="sts-prog-track"><div class="sts-prog-fill" id="sts-prog-fill"></div></div>' +
            '<span class="sts-prog-label" id="sts-prog-label">No scenes loaded</span>' +
            '<span class="sts-cd" id="sts-prog-cd"></span>' +
          '</div>' +
          '<!-- List -->' +
          '<div class="sts-list" id="sts-list">' +
            '<div class="sts-empty"><div class="sts-empty-icon">&#x1F3A8;</div>No scenes loaded yet.</div>' +
          '</div>' +
          '<!-- Actions -->' +
          '<div class="sts-actions">' +
            '<button class="sts-btn sts-btn-primary" id="sts-action-btn">Start Typing</button>' +
            '<button class="sts-btn sts-btn-warn" id="sts-retry-btn" style="display:none;">Retry Failed</button>' +
            '<button class="sts-btn" id="sts-clear-btn" style="background:#374151;color:#9ca3af;font-size:11px;padding:6px 12px;">CLEAR</button>' +
            '<button class="sts-btn" id="sts-test-btn" style="background:#6366f1;color:#fff;font-size:11px;padding:6px 12px;" title="Test: submit one prompt + DOM monitor">TEST</button>' +
          '</div>' +
        '</div>';
      document.body.appendChild(root);

      // Event handlers — draggable pill
      (function() {
        var pill = $id('sts-pill');
        var dragging = false, hasMoved = false, ox, oy;
        pill.addEventListener('mousedown', function(e) {
          dragging = true; hasMoved = false;
          ox = e.clientX - pill.getBoundingClientRect().left;
          oy = e.clientY - pill.getBoundingClientRect().top;
          e.preventDefault();
        });
        document.addEventListener('mousemove', function(e) {
          if (!dragging) return;
          hasMoved = true;
          pill.style.left = (e.clientX - ox) + 'px';
          pill.style.top = (e.clientY - oy) + 'px';
          pill.style.right = 'auto';
          pill.style.bottom = 'auto';
        });
        document.addEventListener('mouseup', function() {
          if (dragging && !hasMoved) {
            S.collapsed = false;
            localStorage.setItem('sts-gemini-collapsed', 'false');
            $id('sts-pill').style.display = 'none';
            $id('sts-panel').style.display = '';
            render();
          }
          dragging = false;
        });
      })();
      $id('sts-collapse-btn').addEventListener('click', function() {
        S.collapsed = true;
        localStorage.setItem('sts-gemini-collapsed', 'true');
        $id('sts-panel').style.display = 'none';
        $id('sts-pill').style.display = '';
        render();
      });
      $id('sts-settings-btn').addEventListener('click', function() {
        S.showSettings = !S.showSettings;
        $id('sts-settings').classList.toggle('open', S.showSettings);
        $id('sts-settings-btn').classList.toggle('active', S.showSettings);
        if (S.showSettings) {
          $id('sts-url-input').value = S.wsUrl;
          $id('sts-show-test-toggle').checked = !!S.showTestButton;
        }
      });
      $id('sts-url-save').addEventListener('click', function() {
        var val = $id('sts-url-input').value.trim();
        if (val) {
          S.wsUrl = val;
          localStorage.setItem('sts-gemini-ws', val);
          localStorage.setItem('sts-gemini-ws-manual', val);
        } else {
          // Clear manual override → re-enable auto-discovery
          localStorage.removeItem('sts-gemini-ws-manual');
        }
        S.wsConnected = false;
        chrome.runtime.sendMessage({ action: 'STS_WS_RECONNECT', manualUrl: val || null });
        render();
      });
      $id('sts-show-test-toggle').checked = !!S.showTestButton;
      $id('sts-show-test-toggle').addEventListener('change', function() {
        S.showTestButton = !!this.checked;
        localStorage.setItem('sts-gemini-show-test', S.showTestButton ? 'true' : 'false');
        render();
      });
      // Tabs
      var tabs = root.querySelectorAll('.sts-tab');
      for (var ti = 0; ti < tabs.length; ti++) {
        tabs[ti].addEventListener('click', function() {
          root.querySelectorAll('.sts-tab').forEach(function(t) { t.classList.remove('active'); });
          this.classList.add('active');
          S.activeTab = this.dataset.tab;
          render();
        });
      }

      $id('sts-action-btn').addEventListener('click', function() {
        if (S.typing.active) { stopTyping(); } else { startTyping(); }
      });
      $id('sts-clear-btn').addEventListener('click', function() {
        var clearedProjects = getUniqueProjectIds(S.typing.queue);
        if (!clearedProjects.length && S.projectId) clearedProjects = [S.projectId];
        updateHistoryForProjects(clearedProjects, {
          status: S.typing.active ? 'stopped' : 'cleared',
          endedAt: Date.now(),
          activate: false
        });
        if (S.typing.active) { stopTyping(); }
        S.typing.queue = [];
        S.scenes = {};
        S.projectId = null;
        S.typing.typedCount = 0;
        S.typing.currentIndex = -1;
        _capturedContainerIds = {};
        sceneContainerMap = {};
        // Remove all badges from DOM
        document.querySelectorAll('.sts-scene-badge').forEach(function(b) { b.remove(); });
        clearStoredState(); // wipe persistence too
        console.log('[STS] Cleared all jobs');
        render();
      });
      $id('sts-retry-btn').addEventListener('click', function() {
        // Reset all error/timed-out items to queued
        var retried = 0;
        S.typing.queue.forEach(function(q) {
          if (q.status === 'error') {
            q.status = 'queued';
            q.error = null;
            if (S.scenes[q.scene]) S.scenes[q.scene].status = 'pending';
            retried++;
          }
        });
        console.log('[STS] Retrying ' + retried + ' failed scenes');
        render();
        if (retried > 0 && !S.typing.active) startTyping();
      });

      // ── TEST button — simulate a single prompt + DOM monitor ──
      $id('sts-test-btn').addEventListener('click', function() {
        if (S.typing.active) { console.log('[TEST] Already running'); return; }
        var testPrompt = 'generate an image wide shot, a solitary figure standing in a vast empty white room, soft diffused lighting, cinematic mood 9:16';
        console.log('[TEST] Starting test job with DOM monitor...');

        // Inject into queue
        var testKey = 'TEST|0';
        S.projectId = 'TEST';
        S.scenes[testKey] = { prompt: testPrompt, status: 'pending', imageUrl: null, projectId: 'TEST' };
        S.typing.queue = [{
          scene: '0', queueKey: testKey, projectId: 'TEST',
          displayPrompt: testPrompt, aspectRatio: '',
          fullPrompt: testPrompt,
          selected: true, status: 'queued', error: null, retryCount: 0
        }];
        updateHistoryEntry('TEST', {
          forceNew: true,
          source: 'test',
          status: 'running',
          startedAt: Date.now(),
          aspectRatio: '9:16'
        });
        render();

        // Run the flow manually with DOM monitor
        waitForGeminiIdle(10000)
          .then(function() { return enableImageTool(); })
          .then(function() {
            console.log('[TEST] Typing prompt...');
            return typeIntoGemini(testPrompt);
          })
          .then(function() { return sleep(1000); })
          .then(function() {
            console.log('[TEST] Submitting...');
            return submitPrompt();
          })
          .then(function() {
            console.log('[TEST] Submitted! Starting DOM monitor on last model-response...');
            captureContainerForScene('0');
            // Wait a moment for container to appear, then start DOM monitor
            return sleep(2000);
          })
          .then(function() {
            var containers = document.querySelectorAll('div.conversation-container');
            var xpath = '(//div[contains(@class,"conversation-container")])[' + containers.length + ']//model-response';
            console.log('[TEST] Monitoring XPath: ' + xpath);
            startDOMMonitor(xpath);
            S.typing.queue[0].status = 'generating';
            S.scenes[testKey].status = 'generating';
            render();
            return waitForImageGeneration(180000, 'TEST', '0');
          })
          .then(function(imageUrl) {
            stopDOMMonitor();
            if (imageUrl) {
              console.log('[TEST] SUCCESS — Image found: ' + imageUrl.substring(0, 80));
              S.typing.queue[0].status = 'completed';
              S.typing.queue[0].imageUrl = imageUrl;
              S.scenes[testKey].status = 'done';
              updateHistoryEntry('TEST', { source: 'test', endedAt: Date.now() });
            } else {
              console.error('[TEST] FAILED — No image generated (timed out)');
              S.typing.queue[0].status = 'error';
              S.typing.queue[0].error = 'No image generated';
              S.scenes[testKey].status = 'error';
              updateHistoryEntry('TEST', { source: 'test', status: 'failed', endedAt: Date.now() });
            }
            render();
            console.log('[TEST] Done. Check DOM recorder panel for the full lifecycle report.');
          })
          .catch(function(e) {
            stopDOMMonitor();
            console.error('[TEST] Error:', e.message || e);
            S.typing.queue[0].status = 'error';
            S.typing.queue[0].error = e.message || String(e);
            if (S.scenes[testKey]) S.scenes[testKey].status = 'error';
            updateHistoryEntry('TEST', { source: 'test', status: 'failed', endedAt: Date.now() });
            render();
          });
      });

      // Copy prompt buttons (delegated)
      $id('sts-list').addEventListener('click', function(e) {
        var copyBtn = e.target.closest('[data-role="copy-prompt"]');
        if (!copyBtn) return;
        e.preventDefault();
        e.stopPropagation();
        var encoded = copyBtn.getAttribute('data-copy-text') || '';
        var text = encoded ? decodeURIComponent(encoded) : '';
        copyText(text).then(function() {
          flashCopyButton(copyBtn, 'Copied', 'copied');
        }).catch(function() {
          flashCopyButton(copyBtn, 'Failed', 'failed');
        });
      });

      // Per-scene retry buttons (delegated)
      $id('sts-panel').addEventListener('click', function(e) {
        var historyToggle = e.target.closest('.sts-history-toggle');
        if (historyToggle) {
          var entryId = historyToggle.getAttribute('data-entry-id');
          if (entryId) {
            S.history.expanded[entryId] = !isHistoryExpanded(entryId);
            render();
          }
          return;
        }
        var btn = e.target.closest('.sts-retry-scene-btn');
        if (!btn) return;
        var sceneKey = btn.getAttribute('data-scene');
        var item = S.typing.queue.find(function(q) { return String(q.scene) === sceneKey; });
        if (item && item.status === 'error') {
          item.status = 'queued';
          item.error = null;
          if (S.scenes[sceneKey]) S.scenes[sceneKey].status = 'pending';
          console.log('[STS] Retrying scene ' + sceneKey);
          render();
          if (!S.typing.active) startTyping();
        }
      });
      // Delegate thumbnail hover for full-size image preview
      $id('sts-list').addEventListener('pointerover', function(e) {
        var thumb = e.target.closest('.sts-row-thumb');
        if (!thumb || thumb.tagName !== 'IMG' || !thumb.src) return;
        showImagePreview(thumb.src, e);
      });
      $id('sts-list').addEventListener('pointermove', function(e) {
        var thumb = e.target.closest('.sts-row-thumb');
        if (!thumb || thumb.tagName !== 'IMG' || !thumb.src) return;
        showImagePreview(thumb.src, e);
      });
      $id('sts-list').addEventListener('pointerout', function(e) {
        var thumb = e.target.closest('.sts-row-thumb');
        if (!thumb || thumb.tagName !== 'IMG') return;
        var next = e.relatedTarget && e.relatedTarget.closest ? e.relatedTarget.closest('.sts-row-thumb') : null;
        if (next === thumb) return;
        hideImagePreview();
      });

      // Initial state
      if (!S.collapsed) {
        $id('sts-pill').style.display = 'none';
        $id('sts-panel').style.display = '';
      }
    }

    function render() {
      if (!document.getElementById('sts-sync')) injectUI();
      saveState(); // persist on every state change (debounced)
      hideImagePreview();
      var historyItems = pruneHistoryEntries(S.history.items);
      S.history.items = historyItems;
      var historyCount = historyItems.length;
      var tq = S.typing.queue;
      var total = tq.length, completed = 0, failed = 0;
      tq.forEach(function(q) { if (q.status === 'completed') completed++; if (q.status === 'error') failed++; });
      var pct = total > 0 ? Math.round(completed / total * 100) : 0;
      var wsOn = S.wsConnected;

      // Pill
      var pillDot = $id('sts-pill-dot');
      if (pillDot) pillDot.classList.toggle('on', wsOn);
      var pillProj = $id('sts-pill-proj');
      if (pillProj) pillProj.textContent = S.projectId || '';
      var queued = tq.filter(function(q) { return q.status === 'queued'; }).length;
      var pillP = $id('sts-pill-p');
      if (pillP) pillP.textContent = queued;
      var pillR = $id('sts-pill-r');
      if (pillR) pillR.textContent = completed;

      // Header
      var headDot = $id('sts-head-dot');
      if (headDot) headDot.classList.toggle('on', wsOn);
      try {
        var portMatch = S.wsUrl.match(/:(\d+)/);
        var headPort = $id('sts-head-port');
        if (headPort) { headPort.textContent = portMatch ? ':' + portMatch[1] : ''; headPort.style.display = portMatch ? '' : 'none'; }
      } catch(e) {}
      var headAr = $id('sts-head-ar');
      if (headAr) { headAr.textContent = S.aspectRatio || ''; headAr.style.display = S.aspectRatio ? '' : 'none'; }

      // Connection bar — always visible, reflects real-time WS state
      var connBar = $id('sts-conn-bar');
      if (connBar) {
        connBar.style.display = 'flex';
        var connIcon = $id('sts-conn-icon');
        var connMsg = $id('sts-conn-msg');
        if (wsOn) {
          connBar.classList.add('ok');
          if (connIcon) connIcon.textContent = '\u2713';
          if (connMsg) connMsg.textContent = 'Connected';
        } else {
          connBar.classList.remove('ok');
          if (connIcon) connIcon.textContent = '\u26A0';
          if (connMsg) connMsg.textContent = 'Disconnected';
        }
      }

      // Rate limit
      var rlEl = $id('sts-rate-limit');
      if (rlEl) {
        if (S.typing.rateLimited) {
          rlEl.style.display = 'flex';
          var rlSub = $id('sts-rate-sub');
          if (rlSub) rlSub.textContent = S.typing.rateLimitReset ? 'Resets at ' + S.typing.rateLimitReset.toLocaleTimeString() : 'Resets at unknown';
          var rlCd = $id('sts-rate-countdown');
          if (rlCd) rlCd.textContent = S.typing.rateLimitReset ? formatCountdown(S.typing.rateLimitReset) : '??:??:??';
        } else {
          rlEl.style.display = 'none';
        }
      }

      // Stats
      var queued = tq.filter(function(q) { return q.status === 'queued'; }).length;
      var typed = tq.filter(function(q) { return q.status === 'completed' || q.status === 'generating'; }).length;
      // Count scenes that have been saved (status 'done' or 'saved')
      var sceneList = Object.values(S.scenes || {});
      var synced = sceneList.filter(function(s) {
          return s.status === 'done' || s.status === 'saved' || s.status === 'downloaded';
      }).length;
      var totalScenes = sceneList.length || tq.length;
      var nQueue = $id('sts-n-queue'); if (nQueue) nQueue.textContent = queued;
      var nTyped = $id('sts-n-typed'); if (nTyped) nTyped.textContent = typed;
      var nDone = $id('sts-n-done'); if (nDone) nDone.textContent = completed;
      var nSent = $id('sts-n-sent'); if (nSent) nSent.textContent = synced + '/' + totalScenes;
      var historyTabCount = $id('sts-history-tab-count'); if (historyTabCount) historyTabCount.textContent = String(historyCount);

      // Progress
      var fill = $id('sts-prog-fill'); if (fill) fill.style.width = pct + '%';
      var label = $id('sts-prog-label');
      if (label) {
        if (S.activeTab === 'history') {
          label.textContent = S.history.items.length ? S.history.items.length + ' runs in last 7 days' : 'No history yet';
        } else if (S.typing.active) {
          var ci = S.typing.currentIndex;
          label.textContent = ci >= 0 ? 'Typing ' + (ci + 1) + '/' + total : 'Typing...';
        } else if (total > 0) {
          label.textContent = completed === total ? 'All done' : completed + '/' + total + ' completed';
        } else {
          label.textContent = 'No scenes loaded';
        }
      }

      // Countdown timer
      var cd = $id('sts-prog-cd');
      if (cd) {
        if (S.activeTab === 'history') {
          cd.textContent = '';
          cd.className = 'sts-cd';
          if (fill) fill.style.width = '0%';
        } else if (S.typing.countdown > 0) {
          var cdLabels = { next: 'next in', retry: 'retry in' };
          cd.textContent = (cdLabels[S.typing.countdownType] || S.typing.countdownType) + ' ' + S.typing.countdown + 's';
          cd.className = 'sts-cd' + (S.typing.countdownType === 'next' || S.typing.countdownType === 'retry' ? ' cool' : '');
        } else {
          cd.textContent = '';
        }
      }

      // Action button
      var btn = $id('sts-action-btn');
      if (btn) {
        if (S.typing.active) {
          btn.textContent = 'Stop'; btn.className = 'sts-btn sts-btn-danger';
        } else if (S.typing.starting) {
          btn.textContent = 'Starting...'; btn.className = 'sts-btn sts-btn-primary'; btn.disabled = true;
        } else {
          btn.textContent = total > 0 ? 'Start Typing' : 'Waiting for Job'; btn.className = 'sts-btn sts-btn-primary'; btn.disabled = false;
        }
      }

      // Retry button — show when there are errors and not currently typing
      var retryBtn = $id('sts-retry-btn');
      if (retryBtn) {
        var hasErrors = tq.some(function(q) { return q.status === 'error'; });
        retryBtn.style.display = (hasErrors && !S.typing.active) ? '' : 'none';
      }
      var testBtn = $id('sts-test-btn');
      if (testBtn) testBtn.style.display = S.showTestButton ? '' : 'none';

      // List
      var list = $id('sts-list');
      if (!list) return;

      if (S.activeTab === 'typing') {
        // ── Typing tab ──
        if (!tq.length) {
          list.innerHTML = '<div class="sts-empty"><div class="sts-empty-icon">&#x1F3A8;</div>No scenes loaded yet.</div>';
          return;
        }
        // Group items by projectId
        var html = '';
        var lastPid = null;
        tq.forEach(function(item, si) {
          var pid = item.projectId || '';
          if (pid !== lastPid) {
            html += '<div class="sts-group-label">' + escHtml(pid || 'Unknown') + '</div>';
            lastPid = pid;
          }
          var displayText = item.displayPrompt || item.prompt || item.fullPrompt || '';
          var copyPayload = item.fullPrompt || decorateGeminiPrompt(displayText);
          var pr = displayText.length > 46 ? displayText.substring(0, 46) + '...' : displayText;
          var sHTML = '', meta = '';
          var isCurrent = S.typing.active && si === S.typing.currentIndex;
          if (item.status === 'queued') { sHTML = '<div class="sts-d-q"></div>'; meta = 'queued'; }
          else if (item.status === 'typing') { sHTML = '<div class="sts-d-typing"></div>'; meta = 'typing...'; }
          else if (item.status === 'generating') { sHTML = '<div class="sts-d-gen"></div>'; meta = 'generating...'; }
          else if (item.status === 'completed') { sHTML = '<span class="sts-d-done">&#x2714;</span>'; meta = 'done'; }
          else if (item.status === 'error') { sHTML = '<span class="sts-d-err">&#x2718;</span>'; meta = 'error'; }
          var rowCls = 'sts-row' + (isCurrent ? ' highlight' : '') + (item.status === 'error' ? ' error-row' : '');
          var thumbHtml = item.imageUrl
            ? '<img class="sts-row-thumb" src="' + item.imageUrl + '" alt="">'
            : '';
          var errHtml = item.error ? '<div class="sts-row-error">' + escHtml(item.error) + '</div>' : '';
          var retryHtml = item.status === 'error'
            ? '<button class="sts-retry-scene-btn" data-scene="' + item.scene + '" style="background:#f39c12;color:#0d1117;border:none;padding:2px 8px;border-radius:3px;font-size:10px;font-weight:700;cursor:pointer;margin-top:2px;">RETRY</button>'
            : '';
          var copyBtnHtml = copyPayload ? '<button class="sts-copy-btn" type="button" data-role="copy-prompt" data-copy-text="' + encodeCopyText(copyPayload) + '" title="Copy full prompt">Copy</button>' : '';
          html += '<div class="' + rowCls + '">' +
            thumbHtml +
            '<div class="sts-row-num">' + item.scene + '</div>' +
            '<div class="sts-row-info">' +
              '<div class="sts-row-prompt">' + escHtml(pr) + '</div>' +
              '<div class="sts-row-meta">' + meta + '</div>' +
              errHtml + retryHtml +
            '</div>' +
            '<div class="sts-row-status">' + copyBtnHtml + sHTML + '</div>' +
          '</div>';
        });
        list.innerHTML = html;
        // Auto-scroll the active (highlighted) row into view so the user can
        // always see what's currently being typed without manual scrolling.
        if (S.typing.active) {
          var activeRow = list.querySelector('.sts-row.highlight');
          if (activeRow && typeof activeRow.scrollIntoView === 'function') {
            try { activeRow.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch (e) {
              try { activeRow.scrollIntoView(); } catch (e2) {}
            }
          }
        }
      } else if (S.activeTab === 'sync') {
        // ── Sync tab — shows image upload/save status per scene ──
        var sceneKeys = Object.keys(S.scenes).sort(function(a, b) {
          var na = parseInt(a.split('|').pop()); var nb = parseInt(b.split('|').pop());
          return (isNaN(na) ? 0 : na) - (isNaN(nb) ? 0 : nb);
        });
        if (!sceneKeys.length) {
          list.innerHTML = '<div class="sts-empty"><div class="sts-empty-icon">&#x1F4E1;</div>Waiting for generations...</div>';
          return;
        }
        // Group sync scenes by projectId
        var syncHtml = '';
        var lastSyncPid = null;
        sceneKeys.forEach(function(key) {
          var sc = S.scenes[key];
          var parts = key.split('|');
          var sceneNum = parts.length > 1 ? parts[1] : parts[0];
          var pid = sc.projectId || (parts.length > 1 ? parts[0] : '');
          if (pid !== lastSyncPid) {
            syncHtml += '<div class="sts-group-label">' + escHtml(pid || 'Unknown') + '</div>';
            lastSyncPid = pid;
          }
          var fullPrompt = sc.prompt || '';
          var pr = fullPrompt.length > 46 ? fullPrompt.substring(0, 46) + '...' : fullPrompt;
          var badgeMap = {
            pending: ['pending', 'pending'],
            generating: ['generating', 'generating...'],
            uploading: ['uploading', 'uploading...'],
            done: ['done', 'saved'],
            error: ['error', 'error']
          };
          var badge = badgeMap[sc.status] || ['pending', sc.status];
          var thumbHtml = sc.imageUrl
            ? '<img class="sts-row-thumb" src="' + sc.imageUrl + '" alt="">'
            : '<div class="sts-row-thumb sts-row-thumb-empty">' + sceneNum + '</div>';
          var copyBtnHtml = fullPrompt ? '<button class="sts-copy-btn" type="button" data-role="copy-prompt" data-copy-text="' + encodeCopyText(decorateGeminiPrompt(fullPrompt)) + '" title="Copy full prompt">Copy</button>' : '';
          syncHtml += '<div class="sts-row">' +
            thumbHtml +
            '<div class="sts-row-num">' + sceneNum + '</div>' +
            '<div class="sts-row-info">' +
              '<div class="sts-row-prompt">' + escHtml(pr) + '</div>' +
              '<div class="sts-row-meta">' + badge[1] + '</div>' +
            '</div>' +
            copyBtnHtml +
            '<span class="sts-card-badge sts-badge-' + badge[0] + '">' + badge[1] + '</span>' +
          '</div>';
        });
        list.innerHTML = syncHtml;
      } else {
        var history = historyItems;
        if (!history.length) {
          list.innerHTML = '<div class="sts-empty"><div class="sts-empty-icon">&#x1F4DA;</div>No history yet.<br>Completed and stopped runs stay here for 7 days.</div>';
          return;
        }
        list.innerHTML = history.map(function(entry) {
          var badge = getHistoryBadge(entry);
          var startedAt = entry.startedAt || entry.createdAt;
          var durationMs = entry.durationMs;
          var expanded = isHistoryExpanded(entry.id);
          if (!entry.endedAt && startedAt) durationMs = Date.now() - startedAt;
          var promptHtml = (entry.prompts || []).map(function(prompt) {
            var fullPrompt = prompt.prompt || '';
            var meta = prompt.status || prompt.syncStatus || 'queued';
            if (prompt.error) meta += ' - ' + prompt.error;
            return '<div class="sts-history-prompt">' +
              '<div class="sts-history-prompt-num">' + escHtml(String(prompt.scene || '?')) + '</div>' +
              '<div class="sts-history-prompt-body">' +
                '<div class="sts-history-prompt-text">' + escHtml(fullPrompt) + '</div>' +
                '<div class="sts-history-prompt-meta">' + escHtml(meta) + '</div>' +
              '</div>' +
              (fullPrompt ? '<button class="sts-copy-btn sts-copy-btn-sm" type="button" data-role="copy-prompt" data-copy-text="' + encodeCopyText(decorateGeminiPrompt(fullPrompt)) + '" title="Copy full prompt">Copy</button>' : '') +
            '</div>';
          }).join('');
          return '<div class="sts-history-card' + (expanded ? ' open' : ' collapsed') + '">' +
            '<div class="sts-history-head">' +
              '<div class="sts-history-title">' + escHtml(entry.projectId || 'Unknown project') + '</div>' +
              (entry.source === 'test' ? '<span class="sts-card-badge sts-badge-test">test</span>' : '') +
              '<span class="sts-card-badge ' + badge.cls + '">' + escHtml(badge.text) + '</span>' +
              '<button class="sts-history-toggle" type="button" data-entry-id="' + escHtml(entry.id || '') + '" aria-expanded="' + (expanded ? 'true' : 'false') + '" title="' + (expanded ? 'Collapse prompts' : 'Expand prompts') + '">' + (expanded ? '&#x25BE;' : '&#x25B8;') + '</button>' +
            '</div>' +
            '<div class="sts-history-sub">' + escHtml(formatHistoryTimestamp(startedAt)) + ' - ' + escHtml(formatHistoryAge(entry.updatedAt || startedAt)) + '</div>' +
            '<div class="sts-history-meta">' +
              '<span class="sts-history-chip sts-history-chip-time">duration ' + escHtml(formatHistoryDuration(durationMs)) + '</span>' +
              '<span class="sts-history-chip sts-history-chip-count">' + escHtml(String(entry.sceneCount || 0)) + ' prompts</span>' +
              '<span class="sts-history-chip sts-history-chip-done">' + escHtml(String(entry.completedCount || 0)) + ' done</span>' +
              '<span class="sts-history-chip sts-history-chip-failed">' + escHtml(String(entry.failedCount || 0)) + ' failed</span>' +
              (entry.aspectRatio ? '<span class="sts-history-chip sts-history-chip-setting">' + escHtml(entry.aspectRatio) + '</span>' : '') +
            '</div>' +
            (expanded ? '<div class="sts-history-prompts">' + promptHtml + '</div>' : '') +
          '</div>';
        }).join('');
      }
    }

    // ── Boot ─────────────────────────────────────────
    injectUI();
    loadState().then(function() {
      render();
      console.log('STS Gemini Synchronizer initialized');
    });
  }
})();
