// STS Gemini — Background Service Worker
// Owns the WebSocket connection (bypasses page CSP) and relays to content script.
// Content script holds a persistent port to keep the service worker alive (MV3).

// Defines STS_ENDPOINT. The launcher rewrites that file with the port the
// backend actually bound, so nothing below hardcodes one.
importScripts(chrome.runtime.getURL('sts-endpoint.js'));

var _ws = null;
var _wsConnected = false;
var _wsUrl = '';
var _wsReconnectTimer = null;
var _wsReconnectAttempts = 0;
var _WS_PATH = '/ws/storyboard-gemini-image-grabber';

// ── Persistent Port (keeps service worker alive) ────
// Content scripts connect via chrome.runtime.connect().
// As long as at least one port is open, the worker stays alive.

var _ports = [];       // { port, tabId }
var _portTabIds = {};  // tabId → true — tracks tabs with an active port

chrome.runtime.onConnect.addListener(function(port) {
  if (port.name !== 'sts-gemini-alive') return;
  var tabId = (port.sender && port.sender.tab) ? port.sender.tab.id : null;
  _ports.push({ port: port, tabId: tabId });
  if (tabId) _portTabIds[tabId] = true;
  console.log('[STS BG] Port connected (' + _ports.length + ' active)');

  // Send current status immediately to the newly connected port
  port.postMessage({ type: 'STS_WS_STATUS', connected: _wsConnected, wsUrl: _wsUrl });

  port.onDisconnect.addListener(function() {
    _ports = _ports.filter(function(p) { return p.port !== port; });
    if (tabId) delete _portTabIds[tabId];
    console.log('[STS BG] Port disconnected (' + _ports.length + ' active)');
  });

  port.onMessage.addListener(function(msg) {
    if (msg.action === 'STS_WS_SEND') {
      sendWS(msg.payload);
    } else if (msg.action === 'STS_WS_GET_STATUS') {
      port.postMessage({ type: 'STS_WS_STATUS', connected: _wsConnected, wsUrl: _wsUrl });
    } else if (msg.action === 'STS_PONG') {
      // Content script responded to ping — tab is alive (no-op, just prevents timeout)
    } else if (msg.action === 'STS_WS_RECONNECT') {
      if (_ws) { try { _ws.close(); } catch(e) {} }
      _ws = null; _wsConnected = false; _wsReconnectAttempts = 0;
      connectWS(msg.manualUrl || null);
    }
  });
});

function _broadcastToAllPorts(msg) {
  for (var i = _ports.length - 1; i >= 0; i--) {
    try { _ports[i].port.postMessage(msg); }
    catch(e) { if (_ports[i].tabId) delete _portTabIds[_ports[i].tabId]; _ports.splice(i, 1); }
  }
}

// Send message to tabs that DON'T have an active port and ARE fully loaded
function _sendToOrphanTabs(tabQuery, msg) {
  chrome.tabs.query(tabQuery, function(tabs) {
    if (!tabs) return;
    for (var i = 0; i < tabs.length; i++) {
      if (_portTabIds[tabs[i].id]) continue;       // already has a port — skip
      if (tabs[i].status !== 'complete') continue;  // not loaded yet — skip
      try {
        chrome.tabs.sendMessage(tabs[i].id, msg, function() { void chrome.runtime.lastError; });
      } catch(e) {}
    }
  });
}

function _broadcastStatus() {
  var msg = { type: 'STS_WS_STATUS', connected: _wsConnected, wsUrl: _wsUrl };
  _broadcastToAllPorts(msg);
  _sendToOrphanTabs({ url: 'https://gemini.google.com/*' }, { action: 'STS_WS_STATUS', connected: _wsConnected, wsUrl: _wsUrl });
}

// ── WebSocket Management ────────────────────────────

function _tryPort(port) {
  return new Promise(function(resolve) {
    var url = 'ws://' + STS_ENDPOINT.host + ':' + port + _WS_PATH;
    var ws;
    try { ws = new WebSocket(url); } catch(e) { resolve(null); return; }
    var timer = setTimeout(function() { try { ws.close(); } catch(e) {} resolve(null); }, 1500);
    ws.onopen = function() { clearTimeout(timer); resolve({ ws: ws, url: url, port: port }); };
    ws.onerror = function() { clearTimeout(timer); resolve(null); };
  });
}

function _discoverPort() {
  var promises = STS_ENDPOINT.appPorts.map(_tryPort);
  return Promise.all(promises).then(function(results) {
    var winner = null;
    for (var i = 0; i < results.length; i++) {
      if (results[i]) {
        if (!winner) { winner = results[i]; }
        else { try { results[i].ws.close(); } catch(e) {} }
      }
    }
    return winner;
  });
}

function _relayToContent(msg) {
  // Primary: via persistent ports (faster, more reliable)
  _broadcastToAllPorts({ type: 'STS_WS_MESSAGE', payload: msg });
  // Fallback: only for tabs without an active port
  _sendToOrphanTabs({ url: 'https://gemini.google.com/*' }, { action: 'STS_WS_MESSAGE', payload: msg });
}

function _attachWS(ws, wsUrl) {
  _ws = ws;
  _wsUrl = wsUrl;

  function _onOpen() {
    if (_ws !== ws) return;
    console.log('[STS BG] Connected to', wsUrl);
    _wsConnected = true;
    _wsReconnectAttempts = 0;
    try { ws.send(JSON.stringify({ type: 'EXTENSION_READY', source: 'sts-gemini-ext' })); } catch(e) {}
    _broadcastStatus();
  }

  // If WS is already open (from port discovery), run open logic now
  if (ws.readyState === WebSocket.OPEN) {
    _onOpen();
  }
  ws.onopen = _onOpen;

  ws.onmessage = function(evt) {
    if (_ws !== ws) return;
    try {
      var msg = JSON.parse(evt.data);
      if (msg.type === 'PING') {
        try { ws.send(JSON.stringify({ type: 'PONG' })); } catch(e) {}
        return;
      }
      if (msg.type === 'PONG') return;
      if (msg.type === 'DIAGNOSE') { _handleDiagnose(_ws); return; }
      if (msg.type === 'SCREENSHOT') { _handleScreenshot(_ws, msg); return; }
      if (msg.type === 'FORCE_DISCONNECT') {
        console.log('[STS BG] FORCE_DISCONNECT received — closing WS');
        if (_ws) { try { _ws.close(); } catch(e) {} }
        return;
      }
      _relayToContent(msg);
    } catch(e) {
      console.warn('[STS BG] Bad message:', e);
    }
  };

  ws.onclose = function() {
    if (_ws === ws) { _ws = null; }
    console.log('[STS BG] Disconnected');
    _wsConnected = false;
    _broadcastStatus();
    _scheduleReconnect();
  };

  ws.onerror = function() {
    if (_ws === ws) _wsConnected = false;
  };
}

function connectWS(manualUrl) {
  if (_ws && (_ws.readyState === WebSocket.OPEN || _ws.readyState === WebSocket.CONNECTING)) return;

  if (manualUrl) {
    var ws;
    try { ws = new WebSocket(manualUrl); } catch(e) {
      _wsConnected = false; _scheduleReconnect(); return;
    }
    _attachWS(ws, manualUrl);
    return;
  }

  _discoverPort().then(function(result) {
    if (result) {
      console.log('[STS BG] Found server on port ' + result.port);
      _attachWS(result.ws, result.url);
    } else {
      _wsConnected = false;
      _broadcastStatus();
      _scheduleReconnect();
    }
  });
}

function _scheduleReconnect() {
  if (_wsReconnectTimer) return;
  _wsReconnectAttempts++;
  var delay = Math.min(_wsReconnectAttempts * 2000, 10000);
  _wsReconnectTimer = setTimeout(function() {
    _wsReconnectTimer = null;
    connectWS(null);
  }, delay);
}

function sendWS(msg) {
  if (_ws && _ws.readyState === WebSocket.OPEN) {
    try {
      _ws.send(typeof msg === 'string' ? msg : JSON.stringify(msg));
      return true;
    } catch(e) {}
  }
  return false;
}

// ── Diagnostics (triggered via WS DIAGNOSE command) ─

function _handleDiagnose(ws) {
  var report = {
    type: 'DIAGNOSE_REPORT',
    ts: new Date().toISOString(),
    bg: {
      wsConnected: _wsConnected,
      wsUrl: _wsUrl,
      wsReadyState: _ws ? _ws.readyState : -1,
      portsActive: _ports.length,
      reconnectAttempts: _wsReconnectAttempts,
    },
    contentStates: [],
    screenshot: null,
    errors: [],
  };

  // 1. Query content script state from all Gemini tabs
  chrome.tabs.query({ url: 'https://gemini.google.com/*' }, function(tabs) {
    if (!tabs || !tabs.length) {
      report.errors.push('No Gemini tabs open');
      _finishDiagnose(ws, report, tabs);
      return;
    }
    var pending = tabs.length;
    for (var i = 0; i < tabs.length; i++) {
      (function(tab) {
        chrome.tabs.sendMessage(tab.id, { action: 'STS_DIAGNOSE' }, function(resp) {
          if (chrome.runtime.lastError) {
            report.contentStates.push({ tabId: tab.id, error: chrome.runtime.lastError.message });
          } else if (resp) {
            report.contentStates.push({ tabId: tab.id, state: resp });
          }
          pending--;
          if (pending <= 0) _finishDiagnose(ws, report, tabs);
        });
      })(tabs[i]);
    }
  });
}

function _finishDiagnose(ws, report, tabs) {
  // 2. Take screenshot of the active Gemini tab
  if (tabs && tabs.length > 0) {
    var targetTab = tabs[0];
    // Make sure the tab is active first
    chrome.tabs.update(targetTab.id, { active: true }, function() {
      chrome.windows.update(targetTab.windowId, { focused: true }, function() {
        setTimeout(function() {
          try { chrome.tabs.captureVisibleTab(targetTab.windowId, { format: 'png' }, function(dataUrl) {
            if (chrome.runtime.lastError) {
              report.errors.push('Screenshot failed: ' + chrome.runtime.lastError.message);
            } else {
              report.screenshot = dataUrl;
            }
            _sendDiagnoseReport(ws, report);
          });
          } catch(e) { report.errors.push('Screenshot error: ' + e.message); _sendDiagnoseReport(ws, report); }
        }, 500);
      });
    });
  } else {
    _sendDiagnoseReport(ws, report);
  }
}

function _sendDiagnoseReport(ws, report) {
  try {
    // Send report back over the WS that requested it
    ws.send(JSON.stringify(report));
    console.log('[STS BG] Diagnose report sent');
  } catch(e) {
    console.warn('[STS BG] Failed to send diagnose report:', e);
  }
}

// ── Screenshot on demand (triggered via WS SCREENSHOT command) ─
// msg.label = optional label for the screenshot (e.g. "before-submit", "after-error")

function _handleScreenshot(ws, msg) {
  var label = msg.label || 'screenshot';
  chrome.tabs.query({ url: 'https://gemini.google.com/*' }, function(tabs) {
    if (!tabs || !tabs.length) {
      ws.send(JSON.stringify({ type: 'SCREENSHOT_RESULT', label: label, error: 'No Gemini tabs open', screenshot: null }));
      return;
    }
    var targetTab = tabs[0];
    chrome.tabs.update(targetTab.id, { active: true }, function() {
      chrome.windows.update(targetTab.windowId, { focused: true }, function() {
        setTimeout(function() {
          try {
            chrome.tabs.captureVisibleTab(targetTab.windowId, { format: 'png' }, function(dataUrl) {
              if (chrome.runtime.lastError) {
                ws.send(JSON.stringify({ type: 'SCREENSHOT_RESULT', label: label, error: chrome.runtime.lastError.message, screenshot: null }));
              } else {
                ws.send(JSON.stringify({ type: 'SCREENSHOT_RESULT', label: label, error: null, screenshot: dataUrl }));
                console.log('[STS BG] Screenshot captured: ' + label);
              }
            });
          } catch(e) {
            ws.send(JSON.stringify({ type: 'SCREENSHOT_RESULT', label: label, error: e.message, screenshot: null }));
          }
        }, 300);
      });
    });
  });
}

// Auto-connect on service worker start
connectWS(null);

// ── Legacy Message Handler (for popup, tab activation, image fetch) ──

chrome.runtime.onMessage.addListener(function(request, sender, sendResponse) {
  if (request.type === 'ACTIVATE_TAB') {
    if (sender.tab && sender.tab.id) {
      chrome.tabs.update(sender.tab.id, { active: true });
      chrome.windows.update(sender.tab.windowId, { focused: true });
    }
    sendResponse({ ok: true });
    return false;
  }

  if (request.type === 'FOCUS_STUDIO_TAB') {
    chrome.tabs.query({}, function(tabs) {
      var studio = tabs.find(function(t) {
        return (t.url && STS_ENDPOINT.uiPorts.some(function(p) { return t.url.indexOf(STS_ENDPOINT.host + ':' + p) !== -1; }))
          || (t.title && t.title.indexOf('Scriptase') !== -1);
      });
      if (studio) {
        chrome.tabs.update(studio.id, { active: true });
        chrome.windows.update(studio.windowId, { focused: true });
        console.log('[STS BG] Focused studio tab:', studio.id, studio.title || studio.url);
      } else {
        console.warn('[STS BG] No ScriptToScene Studio tab found');
      }
    });
    sendResponse({ ok: true });
    return false;
  }

  // Fallback for content scripts not using port yet
  if (request.action === 'STS_WS_SEND') {
    sendWS(request.payload);
    sendResponse({ ok: true, connected: _wsConnected });
    return false;
  }
  if (request.action === 'STS_WS_GET_STATUS') {
    sendResponse({ connected: _wsConnected, wsUrl: _wsUrl });
    return false;
  }
  if (request.action === 'STS_WS_RECONNECT') {
    if (_ws) { try { _ws.close(); } catch(e) {} }
    _ws = null; _wsConnected = false; _wsReconnectAttempts = 0;
    connectWS(request.manualUrl || null);
    sendResponse({ ok: true });
    return false;
  }

  if (request.action === 'FETCH_IMAGE_BASE64') {
    var url = request.url;
    var strategies = [
      { credentials: 'omit', mode: 'cors', redirect: 'follow' },
      { credentials: 'omit', redirect: 'follow' },
      { credentials: 'include', redirect: 'follow' },
      {},
    ];
    var attempt = 0;
    function tryNext() {
      if (attempt >= strategies.length) {
        sendResponse({ success: false, error: 'All fetch strategies failed' });
        return;
      }
      var opts = strategies[attempt++];
      fetch(url, opts)
        .then(function(r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.blob(); })
        .then(function(blob) {
          var reader = new FileReader();
          reader.onload = function() { sendResponse({ success: true, data: reader.result }); };
          reader.onerror = function() { tryNext(); };
          reader.readAsDataURL(blob);
        })
        .catch(function() { tryNext(); });
    }
    tryNext();
    return true;
  }
});
