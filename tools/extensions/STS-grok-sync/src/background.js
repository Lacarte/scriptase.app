// STS Grok Sync — Service Worker
// Owns the WebSocket connection (bypasses page CSP) and relays to content script.
// Content script holds a persistent port to keep the service worker alive (MV3).

// Defines STS_ENDPOINT. The launcher rewrites that file with the port the
// backend actually bound, so nothing below hardcodes one.
importScripts(chrome.runtime.getURL("src/sts-endpoint.js"));

let _ws = null;
let _wsConnected = false;
let _wsReconnectTimer = null;
let _wsReconnectAttempts = 0;
const _WS_PATH = "/ws/animator-grok-video-grabber";

// ── Persistent Port (keeps service worker alive) ────

let _ports = [];       // { port, tabId }
let _portTabIds = {};  // tabId → true — tracks tabs with an active port

chrome.runtime.onConnect.addListener((port) => {
  if (port.name !== "sts-grok-alive") return;
  const tabId = (port.sender && port.sender.tab) ? port.sender.tab.id : null;
  _ports.push({ port, tabId });
  if (tabId) _portTabIds[tabId] = true;
  console.log("[STS BG] Port connected (" + _ports.length + " active)");

  port.postMessage({ type: "STS_WS_STATUS", connected: _wsConnected });

  port.onDisconnect.addListener(() => {
    _ports = _ports.filter(p => p.port !== port);
    if (tabId) delete _portTabIds[tabId];
    console.log("[STS BG] Port disconnected (" + _ports.length + " active)");
  });

  port.onMessage.addListener((msg) => {
    if (msg.action === "STS_WS_SEND") {
      sendWS(msg.payload);
    } else if (msg.action === "STS_WS_GET_STATUS") {
      port.postMessage({ type: "STS_WS_STATUS", connected: _wsConnected });
    } else if (msg.action === "STS_WS_RECONNECT") {
      if (_ws) { try { _ws.close(); } catch(e) {} }
      _ws = null; _wsConnected = false; _wsReconnectAttempts = 0;
      connectWS(msg.manualWsUrl || null);
    }
  });
});

function _broadcastToAllPorts(msg) {
  for (let i = _ports.length - 1; i >= 0; i--) {
    try { _ports[i].port.postMessage(msg); }
    catch(e) { if (_ports[i].tabId) delete _portTabIds[_ports[i].tabId]; _ports.splice(i, 1); }
  }
}

// Send message to tabs that DON'T have an active port and ARE fully loaded
function _sendToOrphanTabs(tabQuery, msg) {
  chrome.tabs.query(tabQuery, (tabs) => {
    if (!tabs) return;
    for (const tab of tabs) {
      if (_portTabIds[tab.id]) continue;       // already has a port — skip
      if (tab.status !== "complete") continue;  // not loaded yet — skip
      try {
        chrome.tabs.sendMessage(tab.id, msg, () => { void chrome.runtime.lastError; });
      } catch(e) {}
    }
  });
}

function _broadcastStatus(port) {
  const msg = { type: "STS_WS_STATUS", connected: _wsConnected, port: port || 0 };
  _broadcastToAllPorts(msg);
  _sendToOrphanTabs({ url: "*://grok.com/*" }, { action: "STS_WS_STATUS", connected: _wsConnected, port: port || 0 });
}

// ── WebSocket Management ────────────────────────────

function _tryPort(p) {
  return new Promise((resolve) => {
    const url = "ws://" + STS_ENDPOINT.host + ":" + p + _WS_PATH;
    let ws;
    try { ws = new WebSocket(url); } catch(e) { resolve(null); return; }
    const timer = setTimeout(() => { try { ws.close(); } catch(e) {} resolve(null); }, 1500);
    ws.onopen = () => { clearTimeout(timer); resolve({ ws, url, port: p }); };
    ws.onerror = () => { clearTimeout(timer); resolve(null); };
  });
}

function _discoverPort() {
  const promises = STS_ENDPOINT.appPorts.map(_tryPort);
  return Promise.all(promises).then((results) => {
    let winner = null;
    for (const r of results) {
      if (r) {
        if (!winner) { winner = r; }
        else { try { r.ws.close(); } catch(e) {} }
      }
    }
    return winner;
  });
}

function _relayToContent(msg) {
  _broadcastToAllPorts({ type: "STS_WS_MESSAGE", payload: msg });
  _sendToOrphanTabs({ url: "*://grok.com/*" }, { action: "STS_WS_MESSAGE", payload: msg });
}

function _attachWS(ws, wsUrl, port) {
  _ws = ws;
  const _onOpen = () => {
    if (_ws !== ws) return;
    console.log("[STS BG] Connected to", wsUrl);
    _wsConnected = true;
    _wsReconnectAttempts = 0;
    try { ws.send(JSON.stringify({ type: "EXTENSION_READY", source: "sts-grok-sync" })); } catch(e) {}
    _broadcastStatus(port);
  };
  if (ws.readyState === WebSocket.OPEN) { _onOpen(); }
  ws.onopen = _onOpen;
  ws.onmessage = (evt) => {
    if (_ws !== ws) return;
    try {
      const msg = JSON.parse(evt.data);
      if (msg.type === "PING") { try { ws.send(JSON.stringify({ type: "PONG" })); } catch(e) {} return; }
      if (msg.type === "PONG") return;
      if (msg.type === "DIAGNOSE") { _handleDiagnose(_ws); return; }
      if (msg.type === "SCREENSHOT") { _handleScreenshot(_ws, msg); return; }
      if (msg.type === "FORCE_DISCONNECT") {
        console.log("[STS BG] FORCE_DISCONNECT — closing WS");
        if (_ws) { try { _ws.close(); } catch(e) {} }
        return;
      }
      _relayToContent(msg);
    } catch(e) {
      console.warn("[STS BG] Bad message:", e);
    }
  };
  ws.onclose = () => {
    if (_ws === ws) { _ws = null; }
    console.log("[STS BG] Disconnected");
    _wsConnected = false;
    _broadcastStatus(0);
    _scheduleReconnect();
  };
  ws.onerror = () => {
    if (_ws === ws) _wsConnected = false;
  };
}

function connectWS(manualWsUrl) {
  if (_ws && (_ws.readyState === WebSocket.OPEN || _ws.readyState === WebSocket.CONNECTING)) return;

  if (manualWsUrl) {
    let ws;
    try { ws = new WebSocket(manualWsUrl); } catch(e) {
      _wsConnected = false; _scheduleReconnect(); return;
    }
    _attachWS(ws, manualWsUrl, 0);
    return;
  }

  _discoverPort().then((result) => {
    if (result) {
      console.log("[STS BG] Found server on port " + result.port);
      _attachWS(result.ws, result.url, result.port);
    } else {
      _wsConnected = false;
      _broadcastStatus(0);
      _scheduleReconnect();
    }
  });
}

function _scheduleReconnect() {
  if (_wsReconnectTimer) return;
  _wsReconnectAttempts++;
  const delay = Math.min(_wsReconnectAttempts * 2000, 10000);
  _wsReconnectTimer = setTimeout(() => { _wsReconnectTimer = null; connectWS(null); }, delay);
}

function sendWS(msg) {
  if (_ws && _ws.readyState === WebSocket.OPEN) {
    try {
      _ws.send(typeof msg === "string" ? msg : JSON.stringify(msg));
      return true;
    } catch(e) {}
  }
  return false;
}

connectWS(null);

// ── Diagnostics ─────────────────────────────────────

function _handleDiagnose(ws) {
  const report = {
    type: "DIAGNOSE_REPORT",
    ts: new Date().toISOString(),
    bg: {
      wsConnected: _wsConnected,
      wsReadyState: _ws ? _ws.readyState : -1,
      portsActive: _ports.length,
      reconnectAttempts: _wsReconnectAttempts,
    },
    contentStates: [],
  };

  chrome.tabs.query({ url: "*://grok.com/*" }, (tabs) => {
    if (!tabs || !tabs.length) {
      try { ws.send(JSON.stringify(report)); } catch(e) {}
      return;
    }
    let pending = tabs.length;
    for (const tab of tabs) {
      chrome.tabs.sendMessage(tab.id, { action: "STS_DIAGNOSE" }, (resp) => {
        if (chrome.runtime.lastError) {
          report.contentStates.push({ tabId: tab.id, error: chrome.runtime.lastError.message });
        } else if (resp) {
          report.contentStates.push({ tabId: tab.id, state: resp });
        }
        pending--;
        if (pending <= 0) {
          try { ws.send(JSON.stringify(report)); } catch(e) {}
        }
      });
    }
  });
}

// ── Screenshot on demand (triggered via WS SCREENSHOT command) ─

function _handleScreenshot(ws, msg) {
  const label = msg.label || "screenshot";
  chrome.tabs.query({ url: "*://grok.com/*" }, (tabs) => {
    if (!tabs || !tabs.length) {
      try { ws.send(JSON.stringify({ type: "SCREENSHOT_RESULT", label, error: "No Grok tabs open", screenshot: null })); } catch(e) {}
      return;
    }
    const targetTab = tabs[0];
    chrome.tabs.update(targetTab.id, { active: true }, () => {
      chrome.windows.update(targetTab.windowId, { focused: true }, () => {
        setTimeout(() => {
          try {
            chrome.tabs.captureVisibleTab(targetTab.windowId, { format: "png" }, (dataUrl) => {
              if (chrome.runtime.lastError) {
                try { ws.send(JSON.stringify({ type: "SCREENSHOT_RESULT", label, error: chrome.runtime.lastError.message, screenshot: null })); } catch(e) {}
              } else {
                try { ws.send(JSON.stringify({ type: "SCREENSHOT_RESULT", label, error: null, screenshot: dataUrl })); } catch(e) {}
                console.log("[STS BG] Screenshot captured: " + label);
              }
            });
          } catch(e) {
            try { ws.send(JSON.stringify({ type: "SCREENSHOT_RESULT", label, error: e.message, screenshot: null })); } catch(e2) {}
          }
        }, 300);
      });
    });
  });
}

// ── Legacy Message Handler ──────────────────────────

chrome.runtime.onInstalled.addListener(() => { console.log("[STS Grok Sync] Installed"); });

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === "PING") { sendResponse({ pong: true }); return false; }
  if (msg.type === "ACTIVATE_TAB") {
    if (sender.tab && sender.tab.id) {
      chrome.tabs.update(sender.tab.id, { active: true });
      chrome.windows.update(sender.tab.windowId, { focused: true });
    }
    sendResponse({ ok: true }); return false;
  }
  if (msg.type === "FOCUS_STUDIO_TAB") {
    // Find and activate the Scriptase tab
    chrome.tabs.query({}, (tabs) => {
      const studio = tabs.find(t =>
        (t.url && STS_ENDPOINT.uiPorts.some(p => t.url.includes(STS_ENDPOINT.host + ":" + p)))
        || (t.title && t.title.includes("Scriptase"))
      );
      if (studio) {
        chrome.tabs.update(studio.id, { active: true });
        chrome.windows.update(studio.windowId, { focused: true });
        console.log("[STS BG] Focused studio tab:", studio.id, studio.title || studio.url);
      } else {
        console.warn("[STS BG] No ScriptToScene Studio tab found");
      }
    });
    sendResponse({ ok: true }); return false;
  }
  if (msg.action === "STS_WS_SEND") { sendWS(msg.payload); sendResponse({ ok: true }); return false; }
  if (msg.action === "STS_WS_GET_STATUS") { sendResponse({ connected: _wsConnected }); return false; }
  if (msg.action === "STS_WS_RECONNECT") {
    if (_ws) { try { _ws.close(); } catch(e) {} }
    _ws = null; _wsConnected = false; _wsReconnectAttempts = 0;
    connectWS(msg.manualWsUrl || null);
    sendResponse({ ok: true }); return false;
  }
  return false;
});
