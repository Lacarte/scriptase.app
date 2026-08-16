// STS Grok Sync — Content Script
// Injected in-page panel for Grok asset synchronization
// Ported from Automa "Grok Assets Synchronizer" workflow

if (window.__stsSyncActive) {
  console.log("[STS Grok Sync] Already running");
} else {
  window.__stsSyncActive = true;
  initSync();
}

// Listen for messages from popup/background
chrome.runtime.onMessage.addListener(function(request, sender, sendResponse) {
  if (request.action === 'STS_STATUS') {
    var s = window.__stsGrokState;
    sendResponse({
      connected: !!(s && s.wsConnected),
      projectId: s ? s.projectId : null,
      sceneCount: s ? Object.keys(s.scenes).length : 0,
    });
    return true;
  } else if (request.action === 'STS_DIAGNOSE') {
    var s = window.__stsGrokState;
    var connBar = document.getElementById('sts-conn-bar');
    var connMsg = document.getElementById('sts-conn-msg');
    var headDot = document.getElementById('sts-head-dot');
    sendResponse({
      active: !!window.__stsSyncActive,
      wsConnected: s ? s.wsConnected : null,
      connected: s ? s.connected : null,
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
    if (window.__stsGrokState) {
      window.__stsGrokState.typing.stopRequested = true;
    }
    var panel = document.getElementById('sts-sync');
    if (panel) panel.remove();
    window.__stsSyncActive = false;
    sendResponse({ ok: true });
  }
});

function initSync() {
  "use strict";
  console.log("=== STS Grok Sync v1.0 ===");

  // ── State ──────────────────────────────────────────────
  window.__stsGrokState = null; // Exposed for STS_STATUS handler
  const S = {
    // Cold-start guess only; the background overwrites it with the port it
    // actually found the moment the socket comes up (STS_WS_STATUS below).
    studioUrl: localStorage.getItem("sts-url") || ("http://" + STS_ENDPOINT.host + ":" + STS_ENDPOINT.appPorts[0]),
    connected: false,
    autoType: localStorage.getItem("sts-auto-type") === "true",
    collapsed: false,
    showSettings: false,
    showTestButton: localStorage.getItem("sts-grok-show-test") === "true",
    activeTab: "typing",
    lastPoll: 0,
    projectId: null,
    arguments: "",
    aspectRatio: "9:16",
    grokMode: "video",
    grokQuality: "480p",
    grokDuration: "6s",
    scenes: {},
    history: {
      items: [],
      activeId: null,
      expanded: {},
    },
    sentScenes: {},
    pollInterval: 5000,
    jobComplete: false,
    _fetchErrors: 0,
    typing: {
      active: false,
      starting: false,
      queue: [],
      runId: 0,
      currentIndex: -1,
      typedCount: 0,
      batchCount: 0,
      countdown: 0,
      countdownType: "",
      stopRequested: false,
      autoPaused: false,
      nextAutoStartAt: 0,
      rateLimited: false,
      rateLimitEndAt: 0,
      rateLimitTimerInterval: null,
    },
    wsConnected: false,
  };

  // ── State persistence (chrome.storage.local) ───────────
  // Survives tab discards, page reloads, and browser restarts.
  // Only cleared by the manual CLEAR button.
  const STORAGE_KEY = "sts-grok-state-v1";
  const HISTORY_KEY = "sts-grok-history-v1";
  const HISTORY_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;
  let _saveTimer = null;
  function saveState() {
    if (_saveTimer) return; // debounce
    _saveTimer = setTimeout(() => {
      _saveTimer = null;
      try {
        const snapshot = {
          projectId: S.projectId,
          scenes: S.scenes,
          historyActiveId: S.history.activeId,
          sentScenes: S.sentScenes,
          jobComplete: S.jobComplete,
          aspectRatio: S.aspectRatio,
          grokMode: S.grokMode,
          grokQuality: S.grokQuality,
          grokDuration: S.grokDuration,
          typing: {
            queue: S.typing.queue.map(q => ({
              ...q,
              // Reset transient statuses so they can be retried after reload
              status: (q.status === "typing" || q.status === "starting") ? "queued" : q.status,
            })),
            typedCount: S.typing.typedCount,
            batchCount: S.typing.batchCount,
          },
        };
        chrome.storage.local.set({ [STORAGE_KEY]: snapshot });
      } catch (e) { console.warn("[STS] saveState failed:", e); }
    }, 500);
  }
  function loadState() {
    return new Promise(resolve => {
      try {
        chrome.storage.local.get(STORAGE_KEY, (result) => {
          if (chrome.runtime.lastError || !result || !result[STORAGE_KEY]) { resolve(); return; }
          const snap = result[STORAGE_KEY];
          if (snap.projectId) S.projectId = snap.projectId;
          if (snap.scenes) S.scenes = snap.scenes;
          if (snap.historyActiveId) S.history.activeId = snap.historyActiveId;
          if (snap.sentScenes) S.sentScenes = snap.sentScenes;
          if (snap.jobComplete) S.jobComplete = snap.jobComplete;
          if (snap.aspectRatio) S.aspectRatio = snap.aspectRatio;
          if (snap.grokMode) S.grokMode = snap.grokMode;
          if (snap.grokQuality) S.grokQuality = snap.grokQuality;
          if (snap.grokDuration) S.grokDuration = snap.grokDuration;
          if (snap.typing) {
            if (Array.isArray(snap.typing.queue)) S.typing.queue = snap.typing.queue;
            if (typeof snap.typing.typedCount === "number") S.typing.typedCount = snap.typing.typedCount;
            if (typeof snap.typing.batchCount === "number") S.typing.batchCount = snap.typing.batchCount;
          }
          console.log("[STS] State restored from storage:", S.typing.queue.length, "queue items,", Object.keys(S.scenes).length, "scenes");
          resolve();
        });
      } catch (e) { console.warn("[STS] loadState failed:", e); resolve(); }
    });
  }
  function clearStoredState() {
    try { chrome.storage.local.remove(STORAGE_KEY); } catch (e) {}
  }

  function sortHistoryEntries(entries) {
    return (entries || []).sort((a, b) =>
      (b.updatedAt || b.endedAt || b.startedAt || b.createdAt || 0) -
      (a.updatedAt || a.endedAt || a.startedAt || a.createdAt || 0)
    );
  }

  function pruneHistoryEntries(entries) {
    const cutoff = Date.now() - HISTORY_MAX_AGE_MS;
    return sortHistoryEntries((entries || []).filter((entry) => {
      if (!entry || typeof entry !== "object") return false;
      const stamp = entry.updatedAt || entry.endedAt || entry.startedAt || entry.createdAt || 0;
      return stamp >= cutoff;
    }));
  }

  function loadHistoryEntries() {
    let entries = [];
    try {
      const raw = localStorage.getItem(HISTORY_KEY);
      entries = raw ? JSON.parse(raw) : [];
    } catch {
      entries = [];
    }
    if (!Array.isArray(entries)) entries = [];
    entries = pruneHistoryEntries(entries);
    try { localStorage.setItem(HISTORY_KEY, JSON.stringify(entries)); } catch {}
    return entries;
  }

  function persistHistoryEntries() {
    S.history.items = pruneHistoryEntries(S.history.items);
    try { localStorage.setItem(HISTORY_KEY, JSON.stringify(S.history.items)); } catch {}
    return S.history.items;
  }

  function isFinalHistoryStatus(status) {
    return status === "completed" ||
      status === "completed_with_errors" ||
      status === "failed" ||
      status === "stopped" ||
      status === "cleared";
  }

  function getUniqueProjectIds(items) {
    const seen = new Set();
    const ids = [];
    for (const item of (items || [])) {
      const pid = item && item.projectId ? item.projectId : null;
      if (!pid || seen.has(pid)) continue;
      seen.add(pid);
      ids.push(pid);
    }
    return ids;
  }

  function getProjectQueueItems(projectId) {
    return (S.typing.queue || []).filter((item) => (item.projectId || S.projectId || "") === projectId);
  }

  function buildProjectHistoryPrompts(projectId) {
    const prompts = getProjectQueueItems(projectId).map((item) => {
      const sc = S.scenes[item.scene] || {};
      return {
        scene: String(item.scene || ""),
        prompt: item.displayPrompt || item.prompt || item.fullPrompt || sc.prompt || "",
        status: item.status || sc.status || "queued",
        syncStatus: sc.status || "",
        error: item.error || "",
        imageUrl: item.imageUrl || sc.imageUrl || "",
        videoUrl: item.videoUrl || sc.previewUrl || "",
      };
    });

    if (!prompts.length && projectId === S.projectId) {
      Object.keys(S.scenes || {}).forEach((sceneNum) => {
        const sc = S.scenes[sceneNum];
        prompts.push({
          scene: String(sceneNum),
          prompt: sc.prompt || "",
          status: sc.status || "pending",
          syncStatus: sc.status || "",
          error: sc.error || "",
          imageUrl: sc.imageUrl || "",
          videoUrl: sc.previewUrl || "",
        });
      });
    }

    prompts.sort((a, b) => {
      const na = parseInt(a.scene, 10);
      const nb = parseInt(b.scene, 10);
      if (Number.isNaN(na) || Number.isNaN(nb)) return String(a.scene).localeCompare(String(b.scene));
      return na - nb;
    });
    return prompts;
  }

  function summarizeProjectHistory(projectId) {
    const prompts = buildProjectHistoryPrompts(projectId);
    let completedCount = 0;
    let failedCount = 0;
    let runningCount = 0;
    let queuedCount = 0;

    for (const prompt of prompts) {
      const status = prompt.status || prompt.syncStatus || "queued";
      if (status === "typed" || status === "ready" || status === "sent" || status === "downloaded") completedCount++;
      else if (status === "error" || status === "failed") failedCount++;
      else if (status === "typing" || status === "generating" || status === "processing" || status === "uploading") runningCount++;
      else queuedCount++;
    }

    return {
      prompts,
      sceneCount: prompts.length,
      completedCount,
      failedCount,
      runningCount,
      queuedCount,
    };
  }

  function ensureHistoryEntry(projectId, options = {}) {
    let entry = null;
    const now = Date.now();

    if (options.id) entry = S.history.items.find((item) => item.id === options.id) || null;
    if (!entry && !options.forceNew && S.history.activeId) {
      entry = S.history.items.find((item) => item.id === S.history.activeId && item.projectId === projectId) || null;
    }
    if (!entry && !options.forceNew) {
      entry = S.history.items.find((item) => item.projectId === projectId && !isFinalHistoryStatus(item.status)) || null;
    }

    if (!entry) {
      entry = {
        id: `${projectId || "PROJECT"}|${now}`,
        projectId: projectId || "Unknown",
        source: options.source || "job",
        createdAt: now,
        startedAt: null,
        endedAt: null,
        updatedAt: now,
        status: "queued",
        aspectRatio: "",
        mode: "",
        duration: "",
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
    if (summary.runningCount > 0) return "running";
    if (summary.sceneCount > 0 && summary.completedCount + summary.failedCount >= summary.sceneCount) {
      if (summary.failedCount > 0 && summary.completedCount > 0) return "completed_with_errors";
      if (summary.failedCount > 0) return "failed";
      return "completed";
    }
    if (summary.failedCount > 0) return "error";
    if (isFinalHistoryStatus(entry.status)) return entry.status;
    return "queued";
  }

  function updateHistoryEntry(projectId, options = {}) {
    if (!projectId) return null;
    const now = Date.now();
    const entry = ensureHistoryEntry(projectId, options);
    const summary = summarizeProjectHistory(projectId);

    entry.projectId = projectId;
    entry.source = options.source || entry.source || "job";
    entry.aspectRatio = options.aspectRatio !== undefined ? options.aspectRatio : (entry.aspectRatio || S.aspectRatio || "");
    entry.mode = options.mode !== undefined ? options.mode : (entry.mode || S.grokMode || "");
    entry.duration = options.duration !== undefined ? options.duration : (entry.duration || S.grokDuration || "");
    entry.prompts = summary.prompts.length ? summary.prompts : (entry.prompts || []);
    entry.sceneCount = summary.sceneCount || entry.sceneCount || entry.prompts.length || 0;
    entry.completedCount = summary.completedCount;
    entry.failedCount = summary.failedCount;
    entry.runningCount = summary.runningCount;
    entry.queuedCount = summary.queuedCount;

    if (options.startedAt && !entry.startedAt) entry.startedAt = options.startedAt;
    if (!entry.startedAt && options.status === "running") entry.startedAt = now;
    if (!entry.startedAt && summary.runningCount > 0) entry.startedAt = now;
    if (options.endedAt !== undefined) entry.endedAt = options.endedAt;

    entry.status = options.status || deriveHistoryStatus(entry, summary);
    entry.updatedAt = now;
    entry.durationMs = Math.max(0, (entry.endedAt || now) - (entry.startedAt || entry.createdAt || now));

    persistHistoryEntries();
    if (isFinalHistoryStatus(entry.status) && S.history.activeId === entry.id) S.history.activeId = null;
    return entry;
  }

  function updateHistoryForProjects(projectIds, options = {}) {
    for (const projectId of (projectIds || [])) updateHistoryEntry(projectId, options);
  }

  function formatHistoryDuration(ms) {
    ms = Math.max(0, ms || 0);
    const totalSeconds = Math.floor(ms / 1000);
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    if (hours > 0) return `${hours}h ${minutes}m`;
    if (minutes > 0) return `${minutes}m ${seconds}s`;
    return `${seconds}s`;
  }

  function formatHistoryTimestamp(ts) {
    if (!ts) return "-";
    return new Date(ts).toLocaleString([], {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  }

  function formatHistoryAge(ts) {
    if (!ts) return "";
    const diff = Math.max(0, Date.now() - ts);
    const minutes = Math.floor(diff / 60000);
    if (minutes < 1) return "just now";
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    return `${Math.floor(hours / 24)}d ago`;
  }

  function getHistoryBadge(entry) {
    if (!entry) return { cls: "sts-badge-pending", text: "queued" };
    if (entry.status === "running") return { cls: "sts-badge-processing", text: "running" };
    if (entry.status === "completed") return { cls: "sts-badge-downloaded", text: "completed" };
    if (entry.status === "completed_with_errors") return { cls: "sts-badge-mixed", text: "done with errors" };
    if (entry.status === "failed") return { cls: "sts-badge-error", text: "failed" };
    if (entry.status === "stopped") return { cls: "sts-badge-stopped", text: "stopped" };
    if (entry.status === "cleared") return { cls: "sts-badge-stopped", text: "cleared" };
    return { cls: "sts-badge-pending", text: entry.status || "queued" };
  }

  function isHistoryExpanded(entryId) {
    return !!(entryId && S.history.expanded && S.history.expanded[entryId]);
  }

  S.history.items = loadHistoryEntries();

  // ── Helpers ────────────────────────────────────────────
  function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
  function $id(id) { return document.getElementById(id); }
  function normalizeText(v) { return String(v || "").replace(/\s+/g, " ").trim(); }

  function isElReady(el) {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return false;
    const style = window.getComputedStyle(el);
    return style.display !== "none" && style.visibility !== "hidden" && style.opacity !== "0";
  }

  async function waitForEl(selector, timeoutMs = 10000, pollMs = 300) {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      const el = document.querySelector(selector);
      if (el && isElReady(el)) return el;
      await sleep(pollMs);
    }
    return null;
  }

  async function waitForElGone(selector, timeoutMs = 30000, pollMs = 500) {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      const el = document.querySelector(selector);
      if (!el || !isElReady(el)) return true;
      await sleep(pollMs);
    }
    return false;
  }

  function simulateClick(el) {
    if (!el) return;
    const events = ["pointerover", "mouseover", "pointerdown", "mousedown", "pointerup", "mouseup", "click"];
    for (const name of events) {
      el.dispatchEvent(new MouseEvent(name, { bubbles: true, cancelable: true, composed: true, view: window, detail: 1 }));
    }
  }

  function parseSvgProgress() {
    const circles = document.querySelectorAll("svg circle[stroke-dasharray]");
    for (let i = 0; i < circles.length; i++) {
      const da = circles[i].getAttribute("stroke-dasharray") || "";
      const off = circles[i].getAttribute("stroke-dashoffset") || "";
      const circumference = parseFloat(da.split(" ")[0]);
      const offset = parseFloat(off);
      if (!isNaN(circumference) && !isNaN(offset) && circumference > 0) {
        return Math.max(0, Math.min(100, Math.round(100 * (1 - offset / circumference))));
      }
    }
    return -1;
  }

  // ── WebSocket (proxied via background service worker) ──
  // The background worker owns the WS connection to bypass page CSP.
  // Content script sends/receives via chrome.runtime messaging.

  // ── WebSocket (proxied via background service worker) ──
  // Port keeps worker alive. sendMessage handles all communication.

  (function keepAlive() {
    try {
      const port = chrome.runtime.connect({ name: "sts-grok-alive" });
      port.onMessage.addListener((msg) => {
        if (msg.type === "STS_WS_MESSAGE") {
          if (!S.wsConnected) { S.wsConnected = true; S.connected = true; S._fetchErrors = 0; render(); }
          try { handleWSMessage(msg.payload); } catch(e) { console.warn("[STS WS] Bad port msg:", e); }
        } else if (msg.type === "STS_WS_STATUS") {
          S.wsConnected = msg.connected;
          S.connected = msg.connected;
          if (msg.connected) S._fetchErrors = 0;
          if (msg.port) {
            S.studioUrl = "http://" + STS_ENDPOINT.host + ":" + msg.port;
            localStorage.setItem("sts-url", S.studioUrl);
          }
          render();
        }
      });
      port.onDisconnect.addListener(() => { setTimeout(keepAlive, 1000); });
    } catch(e) { setTimeout(keepAlive, 2000); }
  })();

  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg.action === "STS_WS_MESSAGE") {
      if (!S.wsConnected) { S.wsConnected = true; S.connected = true; S._fetchErrors = 0; render(); }
      try { handleWSMessage(msg.payload); } catch(e) { console.warn("[STS WS] Bad msg:", e); }
    } else if (msg.action === "STS_WS_STATUS") {
      S.wsConnected = msg.connected;
      S.connected = msg.connected;
      if (msg.connected) S._fetchErrors = 0;
      if (msg.port) {
        S.studioUrl = "http://" + STS_ENDPOINT.host + ":" + msg.port;
        localStorage.setItem("sts-url", S.studioUrl);
      }
      render();
    }
  });

  setInterval(() => {
    try {
      chrome.runtime.sendMessage({ action: "STS_WS_GET_STATUS" }, (resp) => {
        if (chrome.runtime.lastError || !resp) return;
        S.wsConnected = resp.connected;
        S.connected = resp.connected;
        render();
      });
    } catch(e) {}
  }, 2000);

  function connectWS() {
    const manualUrl = localStorage.getItem("sts-url-manual");
    const manualWsUrl = manualUrl ? manualUrl.replace(/^http/, "ws") + "/ws/animator-grok-video-grabber" : null;
    try { chrome.runtime.sendMessage({ action: "STS_WS_RECONNECT", manualWsUrl }); } catch(e) {}
  }

  function sendWS(msg) {
    try { chrome.runtime.sendMessage({ action: "STS_WS_SEND", payload: msg }); } catch(e) {}
  }

  function handleWSMessage(msg) {
    switch (msg.type) {
      case "ANIMATE_JOB": {
        const exists = S.typing.queue.find(q => q.jobId === msg.jobId);
        if (!exists) {
          S.projectId = msg.projectId;
          S.typing.queue.push({
            scene: String(msg.sceneIndex),
            displayPrompt: msg.prompt,
            fullPrompt: msg.prompt,
            prompt: msg.prompt,
            selected: true,
            status: "queued",
            jobId: msg.jobId,
            sceneIndex: msg.sceneIndex,
            projectId: msg.projectId,
            image: msg.image || null,
            imageUrl: msg.image || null,
            mode: msg.mode || S.grokMode,
            duration: msg.duration || S.grokDuration,
            aspectRatio: msg.aspectRatio || S.aspectRatio,
          });
        }
        updateHistoryEntry(msg.projectId, {
          source: "job",
          status: "queued",
          aspectRatio: msg.aspectRatio || S.aspectRatio,
          mode: msg.mode || S.grokMode,
          duration: msg.duration || S.grokDuration,
        });
        render();
        chrome.runtime.sendMessage({ type: "ACTIVATE_TAB" });
        console.log(`[STS WS] Job received: ${msg.projectId} scene ${msg.sceneIndex}`);
        break;
      }
      case "GRABBER_START": {
        S.projectId = msg.projectId;
        S.aspectRatio = msg.aspectRatio || S.aspectRatio;
        S.grokMode = msg.grokMode || S.grokMode;
        S.grokDuration = msg.grokDuration || S.grokDuration;
        if (msg.autoType !== undefined) S.autoType = !!msg.autoType;
        renderAutoType();

        const scenes = msg.scenes || [];
        console.log(`[STS WS] Grabber started: ${msg.projectId} - ${scenes.length} scenes`);

        for (const sc of scenes) {
          const k = String(sc.scene);
          const imgData = sc.image || (sc.image_url ? S.studioUrl + sc.image_url : null);
          if (!S.scenes[k]) {
            S.scenes[k] = { prompt: sc.prompt, status: "pending", urls: [], fileCount: 0, imageUrl: imgData, projectId: msg.projectId };
          } else if (imgData && !S.scenes[k].imageUrl) {
            S.scenes[k].imageUrl = imgData;
            if (!S.scenes[k].projectId) S.scenes[k].projectId = msg.projectId;
          }
          const existing = S.typing.queue.find(q => q.scene === k && q.projectId === msg.projectId);
          if (!existing) {
            S.typing.queue.push({
              scene: k,
              displayPrompt: sc.prompt,
              fullPrompt: sc.prompt,
              selected: true,
              status: "queued",
              imageUrl: imgData,
              projectId: msg.projectId,
            });
          } else if (imgData && !existing.imageUrl) {
            existing.imageUrl = imgData;
          }
        }

        updateHistoryEntry(msg.projectId, {
          source: "job",
          status: "queued",
          aspectRatio: S.aspectRatio,
          mode: S.grokMode,
          duration: S.grokDuration,
        });
        render();
        sendWS({ type: "JOB_RECEIVED", projectId: msg.projectId, scenes: scenes.length });
        chrome.runtime.sendMessage({ type: "ACTIVATE_TAB" });
        if (S.autoType && !S.typing.active && !S.typing.starting) {
          console.log("[STS WS] Auto-starting typing from grabber push");
          setTimeout(() => startTyping(), 1000);
        }
        break;
      }
      case "ACTIVATE_TAB":
        chrome.runtime.sendMessage({ type: "ACTIVATE_TAB" });
        break;
      case "FOCUS_STUDIO_TAB":
        try { chrome.runtime.sendMessage({ type: "FOCUS_STUDIO_TAB" }); } catch {}
        break;
      case "STOP_TYPING":
        console.log("[STS WS] STOP_TYPING received from server");
        if (S.typing.active || S.typing.starting) stopTyping();
        break;
      case "PING":
        sendWS({ type: "PONG" });
        break;
    }
  }

  // ── Rate Limit Detection ───────────────────────────────
  const RATE_LIMIT_INITIAL_MS = 2 * 60 * 60 * 1000;
  const RATE_LIMIT_RETRY_MS = 30 * 60 * 1000;

  function checkRateLimit() {
    const toasts = document.querySelectorAll('[data-sonner-toast][data-type="error"]');
    for (const t of toasts) {
      if (t.textContent && t.textContent.includes("Rate limit reached")) return true;
    }
    const items = document.querySelectorAll('li[data-type="error"], section ol li');
    for (const li of items) {
      if (li.textContent && li.textContent.includes("Rate limit reached")) return true;
    }
    return false;
  }

  let rateLimitOverlay = null;

  function showRateLimitOverlay(endAt) {
    if (rateLimitOverlay) rateLimitOverlay.remove();
    rateLimitOverlay = document.createElement("div");
    rateLimitOverlay.id = "sts-rate-limit-overlay";
    rateLimitOverlay.style.cssText = "position:fixed;top:0;left:0;right:0;z-index:99999;" +
      "background:rgba(255,60,60,0.15);backdrop-filter:blur(2px);" +
      "border-bottom:2px solid rgba(255,80,80,0.5);padding:12px 20px;" +
      "display:flex;align-items:center;justify-content:center;gap:12px;" +
      "font-family:Inter,system-ui,sans-serif;color:#ff6b6b;font-size:14px;font-weight:600;";
    rateLimitOverlay.innerHTML = '<span style="font-size:18px">&#x26A0;</span>' +
      "<span>Rate limit reached</span>" +
      '<span id="sts-rate-timer" style="font-family:monospace;font-size:16px;color:#fff;' +
      'background:rgba(255,60,60,0.3);padding:4px 10px;border-radius:6px;min-width:80px;text-align:center"></span>';
    document.body.appendChild(rateLimitOverlay);

    function updateTimer() {
      const el = document.getElementById("sts-rate-timer");
      if (!el) return;
      const rem = Math.max(0, endAt - Date.now());
      if (rem <= 0) { el.textContent = "Checking..."; return; }
      const h = Math.floor(rem / 3600000);
      const m = Math.floor((rem % 3600000) / 60000);
      const s = Math.floor((rem % 60000) / 1000);
      el.textContent = (h > 0 ? h + "h " : "") + m + "m " + s + "s";
    }
    updateTimer();
    S.typing.rateLimitTimerInterval = setInterval(updateTimer, 1000);
  }

  function hideRateLimitOverlay() {
    if (rateLimitOverlay) { rateLimitOverlay.remove(); rateLimitOverlay = null; }
    if (S.typing.rateLimitTimerInterval) {
      clearInterval(S.typing.rateLimitTimerInterval);
      S.typing.rateLimitTimerInterval = null;
    }
  }

  async function handleRateLimitCooldown() {
    console.warn("[STS] Rate limit detected! Waiting 2 hours...");
    S.typing.rateLimited = true;
    S.typing.rateLimitEndAt = Date.now() + RATE_LIMIT_INITIAL_MS;
    showRateLimitOverlay(S.typing.rateLimitEndAt);
    render();
    await sleep(RATE_LIMIT_INITIAL_MS);

    let retryCount = 0;
    while (checkRateLimit()) {
      retryCount++;
      console.warn(`[STS] Still rate limited, retry #${retryCount}. Waiting 30 min...`);
      S.typing.rateLimitEndAt = Date.now() + RATE_LIMIT_RETRY_MS;
      showRateLimitOverlay(S.typing.rateLimitEndAt);
      render();
      await sleep(RATE_LIMIT_RETRY_MS);
    }

    console.log("[STS] Rate limit cleared, resuming.");
    S.typing.rateLimited = false;
    S.typing.rateLimitEndAt = 0;
    hideRateLimitOverlay();
    render();
  }

  // ── Grok DOM Helpers ───────────────────────────────────

  function findGrokInputElement() {
    const selectors = [
      '.tiptap.ProseMirror[contenteditable="true"]',
      ".tiptap.ProseMirror",
      'div[role="textbox"][contenteditable="true"]',
      '[contenteditable="true"][data-lexical-editor="true"]',
      "textarea[placeholder]",
      "textarea",
      '[contenteditable="true"]',
    ];
    for (const sel of selectors) {
      const hits = document.querySelectorAll(sel);
      for (const el of hits) {
        if (!el || el.closest("#sts-sync") || !isElReady(el)) continue;
        return el;
      }
    }
    return null;
  }

  function getComposerText(inputEl) {
    if (!inputEl) return "";
    if (inputEl instanceof HTMLTextAreaElement || inputEl instanceof HTMLInputElement) return inputEl.value || "";
    return inputEl.textContent || "";
  }

  function setNativeFieldValue(inputEl, value) {
    if (!inputEl) return;
    const proto = inputEl instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const descriptor = Object.getOwnPropertyDescriptor(proto, "value");
    if (descriptor && descriptor.set) descriptor.set.call(inputEl, value);
    else inputEl.value = value;
  }

  function dispatchComposerInput(inputEl, text) {
    if (!inputEl) return;
    try {
      inputEl.dispatchEvent(new InputEvent("input", {
        bubbles: true, cancelable: true, data: text || "", inputType: text ? "insertText" : "deleteContentBackward",
      }));
    } catch {
      inputEl.dispatchEvent(new Event("input", { bubbles: true, cancelable: true }));
    }
    inputEl.dispatchEvent(new Event("change", { bubbles: true, cancelable: true }));
  }

  function selectComposerContents(inputEl) {
    if (!inputEl || inputEl instanceof HTMLTextAreaElement || inputEl instanceof HTMLInputElement) return;
    const selection = window.getSelection();
    if (!selection) return;
    const range = document.createRange();
    range.selectNodeContents(inputEl);
    selection.removeAllRanges();
    selection.addRange(range);
  }

  function clearComposer(inputEl) {
    if (!inputEl) return;
    if (inputEl instanceof HTMLTextAreaElement || inputEl instanceof HTMLInputElement) {
      setNativeFieldValue(inputEl, "");
      dispatchComposerInput(inputEl, "");
      return;
    }
    selectComposerContents(inputEl);
    try { document.execCommand("delete", false, null); } catch {}
    if (normalizeText(getComposerText(inputEl))) inputEl.textContent = "";
    dispatchComposerInput(inputEl, "");
  }

  function setComposerText(inputEl, text) {
    if (!inputEl) return;
    if (inputEl instanceof HTMLTextAreaElement || inputEl instanceof HTMLInputElement) {
      setNativeFieldValue(inputEl, text);
      if (typeof inputEl.selectionStart === "number") {
        inputEl.selectionStart = inputEl.value.length;
        inputEl.selectionEnd = inputEl.value.length;
      }
      dispatchComposerInput(inputEl, text);
      return;
    }

    selectComposerContents(inputEl);
    try {
      inputEl.dispatchEvent(new InputEvent("beforeinput", {
        bubbles: true, cancelable: true, data: text, inputType: "insertText",
      }));
    } catch {}
    try { document.execCommand("insertText", false, text); } catch {}

    if (!normalizeText(getComposerText(inputEl))) {
      let paragraph = inputEl.querySelector("p");
      if (!paragraph && inputEl.classList?.contains("ProseMirror")) {
        inputEl.innerHTML = "<p></p>";
        paragraph = inputEl.querySelector("p");
      }
      if (paragraph) paragraph.textContent = text;
      else inputEl.textContent = text;
    }
    dispatchComposerInput(inputEl, text);
  }

  function composerHasPrompt(inputEl, text) {
    const current = normalizeText(getComposerText(inputEl));
    const expected = normalizeText(text);
    if (!current || !expected) return false;
    if (current === expected) return true;
    const probe = expected.slice(0, Math.min(expected.length, 48));
    return !!probe && current.includes(probe);
  }

  function getComposerRoot(inputEl) {
    if (!inputEl) return null;
    return inputEl.closest("form") ||
      inputEl.closest('[data-testid*="composer"]') ||
      inputEl.closest('[class*="composer"]') ||
      inputEl.closest('[class*="input"]') ||
      inputEl.parentElement || inputEl;
  }

  function findGrokSubmitButton(inputEl) {
    const root = getComposerRoot(inputEl);
    const buttons = document.querySelectorAll("button");
    let best = null, bestScore = -1;

    for (const btn of buttons) {
      if (!btn || btn.closest("#sts-sync") || btn.disabled || !isElReady(btn)) continue;
      const label = normalizeText(btn.textContent);
      const aria = btn.getAttribute("aria-label") || "";
      const testId = btn.getAttribute("data-testid") || "";
      const combined = (label + " " + aria + " " + testId).toLowerCase();
      if (/stop|cancel|retry|regenerate|redownload|sync saved|start typing/.test(combined)) continue;

      let score = 0;
      if (/send|submit|generate|create/.test(combined)) score += 6;
      if ((btn.getAttribute("type") || "").toLowerCase() === "submit") score += 4;
      if (/send|submit/.test(testId.toLowerCase())) score += 4;
      if (root && root !== btn && root.contains(btn)) score += 4;
      if (inputEl && inputEl.form && btn.form === inputEl.form) score += 3;
      if (score > bestScore) { bestScore = score; best = btn; }
    }
    return bestScore > 0 ? best : null;
  }

  function dispatchEnterSubmit(inputEl) {
    if (!inputEl) return;
    for (const name of ["keydown", "keypress", "keyup"]) {
      inputEl.dispatchEvent(new KeyboardEvent(name, {
        key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true, cancelable: true,
      }));
    }
  }

  function hasSubmissionSignal(state) {
    if (!state) return false;
    if (window.location.href !== state.url) return true;
    if (document.querySelectorAll("article").length > state.articleCount) return true;
    if (state.hadVideo && !document.getElementById("sd-video")) return true;
    if (document.querySelector("canvas")) return true;
    if (document.querySelector(".animate-spin")) return true;
    if (parseSvgProgress() >= 0) return true;
    const genSpan = document.querySelector("span.animate-pulse");
    return !!(genSpan && /generating/i.test(genSpan.textContent || ""));
  }

  async function waitForSubmissionAccepted(inputEl, text, state, timeoutMs = 4000) {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      const currentInput = findGrokInputElement() || inputEl;
      if (!composerHasPrompt(currentInput, text)) return true;
      if (hasSubmissionSignal(state)) return true;
      await sleep(250);
    }
    return hasSubmissionSignal(state);
  }

  async function waitForPageReady(timeoutMs = 15000) {
    const maxAttempts = Math.ceil(timeoutMs / 500);
    for (let i = 0; i < maxAttempts; i++) {
      if (findGrokInputElement()) return true;
      await sleep(500);
    }
    return false;
  }

  // ── Grok Actions ───────────────────────────────────────

  function findComposerRoot() {
    const editor = findGrokInputElement();
    if (editor) {
      const editorForm = editor.closest("form");
      if (editorForm) return editorForm;
    }

    const fileInput = document.querySelector('input[type="file"]');
    if (fileInput) {
      const fileForm = fileInput.closest("form");
      if (fileForm) return fileForm;
    }

    return document.querySelector("form") || document.body;
  }

  function approximateDataUrlBytes(dataUrl) {
    const value = String(dataUrl || "");
    const raw = value.includes(",") ? value.split(",").pop() : value;
    const padding = raw.endsWith("==") ? 2 : raw.endsWith("=") ? 1 : 0;
    return Math.max(0, Math.floor((raw.length * 3) / 4) - padding);
  }

  function getComposerUploadState() {
    const root = findComposerRoot();
    const scope = root || document.body;
    const removeButtons = Array.from(scope.querySelectorAll('button[aria-label="Remove image"]'));
    const thumbImages = Array.from(scope.querySelectorAll('img[src^="blob:"], img[src^="data:image/"]'));
    const alertIcons = Array.from(scope.querySelectorAll('.lucide-triangle-alert, svg[class*="triangle-alert"]'));
    const scopeText = normalizeText((scope.innerText || scope.textContent || ""));
    const oversizePattern = /files?\s+(?:was|were)\s+too\s+large/i;
    const hasOversizeText = oversizePattern.test(scopeText);
    const hasPending = [
      '.animate-spin',
      '[class*="uploading"]',
      '[class*="loading"]',
      '[aria-busy="true"]',
      '[data-state="loading"]',
    ].some((selector) => !!scope.querySelector(selector));

    return {
      root: scope,
      removeButtons,
      thumbImages,
      alertIcons,
      hasAttachment: removeButtons.length > 0 || thumbImages.length > 0,
      hasAlertIcon: alertIcons.length > 0,
      hasOversizeText,
      hasOversize: hasOversizeText || alertIcons.length > 0,
      hasPending,
    };
  }

  async function removeComposerImages(maxPasses = 10) {
    let removedAny = false;
    for (let pass = 0; pass < maxPasses; pass++) {
      const { removeButtons } = getComposerUploadState();
      if (!removeButtons.length) break;
      for (const btn of removeButtons) {
        try {
          btn.style.opacity = "1";
          btn.style.pointerEvents = "auto";
          simulateClick(btn);
          removedAny = true;
        } catch {}
        await sleep(180);
      }
      await sleep(350);
    }

    const settleUntil = Date.now() + 4000;
    while (Date.now() < settleUntil) {
      if (!getComposerUploadState().hasAttachment) break;
      await sleep(200);
    }
    return removedAny;
  }

  function dataUrlToFile(dataUrl, fileName) {
    const raw = dataUrl.includes(",") ? dataUrl.split(",").pop() : dataUrl;
    const binaryString = atob(raw);
    const bytes = new Uint8Array(binaryString.length);
    for (let i = 0; i < binaryString.length; i++) bytes[i] = binaryString.charCodeAt(i);

    const mimeMatch = dataUrl.match(/data:([^;]+);/);
    const mimeType = mimeMatch ? mimeMatch[1] : "image/jpeg";
    const blob = new Blob([bytes], { type: mimeType });
    const ext = mimeType.split("/").pop() || "jpg";
    return new File([blob], fileName || ("sts-input-" + Date.now() + "." + ext), { type: mimeType });
  }

  function drawCanvasLabel(ctx, x, y, width, height, radius) {
    ctx.beginPath();
    ctx.moveTo(x + radius, y);
    ctx.lineTo(x + width - radius, y);
    ctx.quadraticCurveTo(x + width, y, x + width, y + radius);
    ctx.lineTo(x + width, y + height - radius);
    ctx.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
    ctx.lineTo(x + radius, y + height);
    ctx.quadraticCurveTo(x, y + height, x, y + height - radius);
    ctx.lineTo(x, y + radius);
    ctx.quadraticCurveTo(x, y, x + radius, y);
    ctx.closePath();
  }

  function paintResizedMarker(ctx, width, height) {
    const minSide = Math.max(1, Math.min(width, height));
    const fontSize = Math.max(14, Math.round(minSide * 0.07));
    const padX = Math.max(10, Math.round(fontSize * 0.55));
    const padY = Math.max(6, Math.round(fontSize * 0.35));
    const inset = Math.max(10, Math.round(minSide * 0.04));
    const radius = Math.max(8, Math.round(fontSize * 0.45));
    const label = "RESIZED";

    ctx.save();
    ctx.font = "700 " + fontSize + "px Arial";
    const textWidth = ctx.measureText(label).width;
    const boxWidth = Math.ceil(textWidth + padX * 2);
    const boxHeight = Math.ceil(fontSize + padY * 2);
    const x = Math.max(inset, width - boxWidth - inset);
    const y = Math.max(inset, height - boxHeight - inset);

    drawCanvasLabel(ctx, x, y, boxWidth, boxHeight, radius);
    ctx.fillStyle = "rgba(10, 24, 38, 0.82)";
    ctx.fill();
    ctx.lineWidth = Math.max(2, Math.round(fontSize * 0.12));
    ctx.strokeStyle = "rgba(255, 255, 255, 0.78)";
    ctx.stroke();

    ctx.fillStyle = "#ffffff";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(label, x + boxWidth / 2, y + boxHeight / 2 + 1);
    ctx.restore();
  }

  async function resizeImageDataUrl(dataUrl, scaleFactor = 0.75, quality = 0.86) {
    if (!dataUrl) throw new Error("Missing image data");

    const img = new Image();
    const loaded = new Promise((resolve, reject) => {
      img.onload = resolve;
      img.onerror = () => reject(new Error("Failed to decode image for resize"));
    });
    img.src = dataUrl;
    await loaded;

    const srcW = img.naturalWidth || img.width;
    const srcH = img.naturalHeight || img.height;
    if (!srcW || !srcH) throw new Error("Image size unavailable");

    const scale = Math.max(0.1, Math.min(1, scaleFactor));
    const width = Math.max(1, Math.round(srcW * scale));
    const height = Math.max(1, Math.round(srcH * scale));
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;

    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("Canvas resize unavailable");
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, width, height);
    ctx.drawImage(img, 0, 0, width, height);
    paintResizedMarker(ctx, width, height);

    return canvas.toDataURL("image/jpeg", quality);
  }

  async function findGrokFileInput(timeoutMs = 10000) {
    let fileInput = document.querySelector('input[type="file"]');
    if (fileInput) return fileInput;
    const maxAttempts = Math.ceil(timeoutMs / 250);
    for (let attempt = 0; attempt < maxAttempts; attempt++) {
      await sleep(250);
      fileInput = document.querySelector('input[type="file"]');
      if (fileInput) return fileInput;
    }
    return null;
  }

  async function injectImageFileToGrok(file) {
    const fileInput = await findGrokFileInput();
    if (!fileInput) throw new Error("File input not found");

    const dataTransfer = new DataTransfer();
    dataTransfer.items.add(file);
    try { fileInput.value = ""; } catch {}
    fileInput.files = dataTransfer.files;
    fileInput.dispatchEvent(new Event("change", { bubbles: true }));
  }

  async function waitForUploadOutcome(timeoutMs = 16000) {
    const start = Date.now();
    let stableAttachmentCount = 0;
    let lastSignature = "";

    while (Date.now() - start < timeoutMs) {
      const state = getComposerUploadState();
      const signature = state.removeButtons.length + "|" + state.thumbImages.length + "|" + state.alertIcons.length;
      const oversizeTriggered = state.hasOversize;

      if (oversizeTriggered) return { status: "oversize", state };

      if (state.hasAttachment) {
        stableAttachmentCount = (signature === lastSignature) ? stableAttachmentCount + 1 : 0;
        lastSignature = signature;

        if (!state.hasPending && stableAttachmentCount >= 2) return { status: "ready", state };
        if (stableAttachmentCount >= 4) return { status: "ready", state };
      } else {
        stableAttachmentCount = 0;
        lastSignature = "";
      }

      await sleep(350);
    }

    const finalState = getComposerUploadState();
    const finalOversize = finalState.hasOversize;
    if (finalOversize) return { status: "oversize", state: finalState };
    if (finalState.hasAttachment) return { status: "ready", state: finalState };
    return { status: "timeout", state: finalState };
  }

  async function resetGrokInput() {
    console.log("[STS] Resetting Grok input...");
    // Remove uploaded images
    await removeComposerImages();

    // Clear text input
    const editor = findGrokInputElement();
    if (editor) {
      if (editor.contentEditable === "true") { editor.innerHTML = ""; editor.textContent = ""; }
      else editor.value = "";
      editor.dispatchEvent(new Event("input", { bubbles: true }));
    }

    // Click Imagine nav link to reset page state
    let imagineLink = document.querySelector('a[href="/imagine"], a[href*="/imagine"]');
    if (!imagineLink) {
      try {
        const xr = document.evaluate('/html/body/div[2]/div/div[1]/div/div[1]/div[2]/div[4]/ul/li/a', document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
        if (xr.singleNodeValue) imagineLink = xr.singleNodeValue;
      } catch {}
    }
    if (imagineLink) {
      simulateClick(imagineLink);
      for (let i = 0; i < 20; i++) {
        await sleep(500);
        if (window.location.pathname.includes("/imagine") && findGrokInputElement()) break;
      }
      await sleep(500);
    }

    // Verify images cleared
    await removeComposerImages(4);
  }

  async function setupGrokMode() {
    console.log("[STS] Setting up Grok mode:", S.grokMode, S.grokQuality, S.grokDuration, "aspect=" + S.aspectRatio);

    // Detect UI version
    let uiVersion = 3;
    if (document.querySelector(".group\\/attach-button")) uiVersion = 1;
    else if (document.querySelector('div.inline-flex > div[role="radiogroup"]')) uiVersion = 3;
    else uiVersion = 2;

    // Select mode (Video / Image)
    const radioGroup = document.querySelector('div[role="radiogroup"]');
    if (radioGroup) {
      for (const r of radioGroup.querySelectorAll('[role="radio"]')) {
        if (r.textContent.trim().toLowerCase() === S.grokMode) {
          simulateClick(r);
          await sleep(800);
          break;
        }
      }
    }

    // Select aspect ratio
    const targetRatio = S.aspectRatio || "9:16";
    if (uiVersion === 3) {
      const closedDivs = document.querySelectorAll('div.inline-flex[data-state="closed"]');
      for (const cd of closedDivs) {
        if (!cd.querySelector('[role="radiogroup"]') && !cd.closest('[role="radiogroup"]')) {
          const arBtn = cd.querySelector("button");
          if (arBtn) { simulateClick(arBtn); await sleep(600); }
          break;
        }
      }
    } else {
      const configTrigger = document.querySelector('button[data-testid="mode-config-trigger"]');
      if (configTrigger) { simulateClick(configTrigger); await sleep(600); }
    }

    let ratioFound = false;
    for (let attempt = 0; attempt < 15 && !ratioFound; attempt++) {
      const ratioBtn = document.querySelector('button[data-aspect-ratio="' + targetRatio + '"]');
      if (ratioBtn) { simulateClick(ratioBtn); ratioFound = true; await sleep(400); break; }
      const menuItems = document.querySelectorAll('[role="menu"] [role="menuitem"]');
      for (const mi of menuItems) {
        const span = mi.querySelector("span");
        if (span && span.textContent.trim() === targetRatio) {
          simulateClick(mi); ratioFound = true; await sleep(400); break;
        }
      }
      if (!ratioFound) await sleep(200);
    }

    // Select duration
    if (uiVersion !== 3) {
      if (!document.querySelector('[data-testid="mode-selected-wrapper"]')) {
        const trigger = document.querySelector('button[data-testid="mode-config-trigger"]');
        if (trigger) { simulateClick(trigger); await sleep(600); }
      }
    }
    const targetDur = S.grokDuration.replace(/\s/g, "");
    for (const btn of document.querySelectorAll("button")) {
      const t = btn.textContent.trim();
      if (t === targetDur || t === targetDur.replace("s", " s")) {
        simulateClick(btn); await sleep(400); break;
      }
    }

    // Select quality
    for (const btn of document.querySelectorAll("button")) {
      if (btn.textContent.trim() === S.grokQuality) {
        simulateClick(btn); await sleep(400); break;
      }
    }

    // Close dropdown if needed
    if (uiVersion !== 3) {
      if (document.querySelector('[data-testid="mode-selected-wrapper"]')) {
        const closeTrigger = document.querySelector('button[data-testid="mode-config-trigger"]');
        if (closeTrigger) { simulateClick(closeTrigger); await sleep(300); }
      }
    }
  }

  async function uploadImageToGrok(base64Data) {
    if (!base64Data) return false;
    let currentDataUrl = base64Data;
    let resizeCount = 0;
    const maxAttempts = 8;

    for (let attemptIndex = 0; attemptIndex < maxAttempts; attemptIndex++) {
      const attemptLabel = resizeCount ? ("resized " + resizeCount + "x") : "original";
      const file = dataUrlToFile(currentDataUrl, "sts-input-" + Date.now() + "-" + attemptIndex + ".jpg");
      console.log("[STS] Uploading image attempt", attemptIndex + 1, "(" + attemptLabel + ", " + approximateDataUrlBytes(currentDataUrl) + " bytes)");

      await injectImageFileToGrok(file);
      const outcome = await waitForUploadOutcome();

      if (outcome.status === "ready") {
        const verifiedState = getComposerUploadState();
        if (verifiedState.hasOversize) {
          console.warn("[STS] Oversize warning still visible after upload; resizing again");
          await removeComposerImages();
          await sleep(500);
        } else {
          console.log("[STS] Image upload complete");
          return currentDataUrl;
        }
      } else if (outcome.status === "oversize") {
        console.warn("[STS] Grok rejected image as too large; removing thumbnail and retrying smaller size");
        await removeComposerImages();
        await sleep(500);
      } else {
        console.warn("[STS] Image upload did not settle cleanly; clearing thumbnail before retry");
        await removeComposerImages();
        await sleep(500);
      }

      if (attemptIndex >= maxAttempts - 1) break;
      currentDataUrl = await resizeImageDataUrl(currentDataUrl, 0.75, resizeCount ? 0.82 : 0.86);
      resizeCount++;
    }

    throw new Error("Image upload failed after resize retries");
  }

  async function typeIntoGrok(text) {
    let inputEl = findGrokInputElement();
    if (!inputEl) throw new Error("Grok input not found");
    const submitState = {
      url: window.location.href,
      articleCount: document.querySelectorAll("article").length,
      hadVideo: !!document.getElementById("sd-video"),
    };

    simulateClick(inputEl);
    inputEl.focus();
    await sleep(250);
    clearComposer(inputEl);
    await sleep(150);
    setComposerText(inputEl, text);
    await sleep(350);

    if (!composerHasPrompt(inputEl, text)) {
      inputEl = findGrokInputElement() || inputEl;
      setComposerText(inputEl, text);
      await sleep(350);
    }
    if (!composerHasPrompt(inputEl, text)) throw new Error("Prompt did not land in Grok composer");

    dispatchEnterSubmit(inputEl);
    let accepted = await waitForSubmissionAccepted(inputEl, text, submitState, 2500);
    if (accepted) { console.log("Prompt submitted via Enter"); return; }

    const submitBtn = findGrokSubmitButton(inputEl);
    if (submitBtn) {
      simulateClick(submitBtn);
      accepted = await waitForSubmissionAccepted(inputEl, text, submitState, 4000);
      if (accepted) { console.log("Prompt submitted via send button"); return; }
    }

    if (inputEl.form && typeof inputEl.form.requestSubmit === "function") {
      try {
        inputEl.form.requestSubmit();
        accepted = await waitForSubmissionAccepted(inputEl, text, submitState, 3000);
        if (accepted) return;
      } catch {}
    }
    throw new Error("Prompt did not submit to Grok");
  }

  async function tryRegenerate() {
    try {
      let regenBtn = document.querySelector('button[aria-label*="Regenerate"], button[aria-label*="regenerate"]');
      if (!regenBtn) {
        for (const b of document.querySelectorAll("button")) {
          if (/regenerate/i.test(b.textContent)) { regenBtn = b; break; }
        }
      }
      if (regenBtn && isElReady(regenBtn)) { simulateClick(regenBtn); await sleep(2000); }
    } catch {}
  }

  // ── Video Collection ───────────────────────────────────

  function isVideoModeJob() { return (S.grokMode || "").toLowerCase() === "video"; }

  function isVideoAssetUrl(url) {
    const clean = String(url || "").replace(/\?.*$/, "").toLowerCase();
    return clean.endsWith(".mp4") || clean.endsWith(".webm") || clean.endsWith(".mov") || clean.includes("/generated_video");
  }

  function collectAllVideoUrls(seenUrls) {
    const urls = [];
    const seen = new Set();
    const seenClean = new Set();
    if (seenUrls) seenUrls.forEach(u => seenClean.add(u.replace(/\?.*$/, "")));

    const articles = document.querySelectorAll("article");
    const scope = articles.length > 0 ? articles[articles.length - 1] : document;

    for (const img of scope.querySelectorAll('button img[alt^="Thumbnail"]')) {
      const src = img.src || img.getAttribute("src") || "";
      const uuidMatch = src.match(/generated\/([a-f0-9-]+)\//);
      const userMatch = src.match(/users\/([a-f0-9-]+)\//);
      if (uuidMatch && userMatch) {
        const mp4 = "https://assets.grok.com/users/" + userMatch[1] + "/generated/" + uuidMatch[1] + "/generated_video.mp4";
        if (!seen.has(mp4) && !seenClean.has(mp4)) { seen.add(mp4); urls.push(mp4); }
      }
    }

    const sdv = document.getElementById("sd-video");
    if (sdv) {
      const sdSrc = (sdv.src || sdv.getAttribute("src") || "").replace(/\?.*$/, "");
      if (sdSrc && sdSrc.includes(".mp4") && !seen.has(sdSrc) && !seenClean.has(sdSrc)) { seen.add(sdSrc); urls.push(sdSrc); }
    }
    return urls;
  }

  // Scene-to-container mapping (set after each submit)
  const sceneContainerMap = {};

  function captureContainerForScene(sceneKey) {
    const articles = document.querySelectorAll("article");
    if (articles.length > 0) {
      const last = articles[articles.length - 1];
      sceneContainerMap[sceneKey] = last;
      console.log("[TRACK] Mapped scene " + sceneKey + " to article index " + (articles.length - 1));
      injectSceneBadge(last, sceneKey);
    }
  }

  function injectSceneBadge(container, sceneKey) {
    if (!container) return;
    const _doInject = () => {
      if (container.querySelector(".sts-scene-badge")) return;
      const badge = document.createElement("div");
      badge.className = "sts-scene-badge";
      badge.textContent = "[" + (S.projectId || "") + "|" + sceneKey + "]";
      badge.style.cssText = "position:absolute;top:8px;right:8px;background:#00d4aa;color:#0d1117;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:700;font-family:monospace;z-index:999;pointer-events:none;";
      container.style.position = "relative";
      container.appendChild(badge);
    };
    _doInject();
    // Re-inject if React re-renders and removes our badge
    const observer = new MutationObserver(() => {
      if (!container.querySelector(".sts-scene-badge")) _doInject();
    });
    observer.observe(container, { childList: true, subtree: true });
  }

  async function waitForGeneration(sceneId, seenUrls, timeoutMs = 300000, runId) {
    const pollInterval = 2000;
    const maxPolls = Math.ceil(timeoutMs / pollInterval);

    // Phase 1: Wait for generation to START
    let started = false;
    for (let a = 0; a < 30; a++) {
      if (shouldStopTyping(runId)) return null;
      if (checkRateLimit()) { await handleRateLimitCooldown(); return null; }

      const videoGone = !document.getElementById("sd-video");
      const hasCanvas = !!document.querySelector("canvas");
      const hasSpin = !!document.querySelector(".animate-spin");
      const genSpan = document.querySelector("span.animate-pulse");
      const hasGen = genSpan && /generating/i.test(genSpan.textContent);
      const svgPct = parseSvgProgress();

      if (videoGone || hasCanvas || hasSpin || hasGen || svgPct >= 0) {
        started = true;
        break;
      }
      updateProgressLabel("Waiting to start...");
      await sleep(pollInterval);
    }

    // Phase 2: Wait for generation to FINISH
    for (let p = 0; p < maxPolls; p++) {
      if (shouldStopTyping(runId)) return null;
      if (checkRateLimit()) { await handleRateLimitCooldown(); return null; }

      let isActive = false;
      let pctText = "";

      const gs = document.querySelector("span.animate-pulse");
      if (gs && /generating/i.test(gs.textContent)) {
        isActive = true;
        const tabNums = gs.parentElement?.querySelector(".tabular-nums");
        pctText = tabNums ? tabNums.textContent.trim() : "";
      }

      const svgPct = parseSvgProgress();
      if (svgPct >= 0 && svgPct < 100) { isActive = true; pctText = svgPct + "%"; }
      if (document.querySelector(".animate-spin")) isActive = true;
      if (document.querySelector("canvas")) isActive = true;
      if (isActive) started = true;

      if (isActive) {
        updateProgressLabel(pctText ? "Generating... " + pctText : "Generating...");
        await sleep(pollInterval);
        continue;
      }

      // Generation indicators gone - check for completed video
      if (started) {
        const articles = document.querySelectorAll("article");
        const lastArticle = articles.length > 0 ? articles[articles.length - 1] : document;
        const videos = lastArticle.querySelectorAll('video[src*="assets.grok.com"]');
        const latestVideo = videos.length > 0 ? videos[videos.length - 1] : null;
        let vSrc = latestVideo ? (latestVideo.src || latestVideo.getAttribute("src") || "") : "";

        if (!vSrc) {
          const sdv = document.getElementById("sd-video");
          vSrc = sdv ? (sdv.src || sdv.getAttribute("src") || "") : "";
        }

        if (vSrc && !seenUrls.has(vSrc.replace(/\?.*$/, "")) && vSrc.includes(".mp4")) {
          const allUrls = collectAllVideoUrls(seenUrls);
          return { primary: vSrc, allUrls: allUrls.length ? allUrls : [vSrc] };
        }

        // Check for generated image
        const imgs = lastArticle.querySelectorAll('img[src*="assets.grok.com"][src*="/generated/"]');
        const latestImg = imgs.length > 0 ? imgs[imgs.length - 1] : null;
        const iSrc = latestImg ? (latestImg.src || latestImg.getAttribute("src") || "") : "";
        if (iSrc && !seenUrls.has(iSrc.replace(/\?.*$/, "")) && iSrc.includes("assets.grok.com")) {
          if (isVideoModeJob()) { await sleep(pollInterval); continue; }
          return { primary: iSrc, allUrls: [iSrc] };
        }
      }

      await sleep(pollInterval);
    }

    // Timeout - try regenerate
    if (!shouldStopTyping(runId)) {
      await tryRegenerate();
      await sleep(5000);
      if (!shouldStopTyping(runId)) {
        const articles = document.querySelectorAll("article");
        const lastArt = articles.length > 0 ? articles[articles.length - 1] : document;
        const lastVids = lastArt.querySelectorAll('video[src*="assets.grok.com"]');
        const lastV = lastVids.length > 0 ? lastVids[lastVids.length - 1] : null;
        const lastSrc = lastV ? (lastV.src || lastV.getAttribute("src") || "") : "";
        if (lastSrc && !seenUrls.has(lastSrc.replace(/\?.*$/, "")) && lastSrc.includes(".mp4")) {
          const regenUrls = collectAllVideoUrls(seenUrls);
          return { primary: lastSrc, allUrls: regenUrls.length ? regenUrls : [lastSrc] };
        }
      }
    }
    return null;
  }

  // ── Asset Upload ───────────────────────────────────────

  async function fetchBlob(url) {
    const strategies = [{ credentials: "include" }, { mode: "cors", credentials: "omit" }, {}];
    for (const opts of strategies) {
      try {
        const r = await fetch(url, opts);
        if (r.ok) return await r.blob();
      } catch {}
    }
    return null;
  }

  async function sendResults(num, urls) {
    const sc = S.scenes[num];
    if (sc) sc.status = "uploading";
    render();

    if (isVideoModeJob()) urls = (urls || []).filter(isVideoAssetUrl);
    if (!urls || !urls.length) {
      if (sc) sc.status = "error";
      render();
      return;
    }

    const images = [];
    const failedUrls = [];

    for (const url of urls) {
      try {
        let blob = null;
        for (let retry = 0; retry < 3 && !blob; retry++) {
          blob = await fetchBlob(url);
          if (!blob && retry < 2) await sleep(2000);
        }
        if (!blob) { failedUrls.push(url); continue; }

        const b64 = await new Promise((res, rej) => {
          const reader = new FileReader();
          reader.onload = () => res(reader.result);
          reader.onerror = rej;
          reader.readAsDataURL(blob);
        });

        const ct = blob.type || "";
        let ext = ".png";
        if (ct.includes("mp4") || url.includes(".mp4")) ext = ".mp4";
        else if (ct.includes("webm") || url.includes(".webm")) ext = ".webm";
        else if (ct.includes("quicktime") || url.includes(".mov")) ext = ".mov";
        else if (ct.includes("webp") || url.includes(".webp")) ext = ".webp";
        else if (ct.includes("jpeg") || ct.includes("jpg")) ext = ".jpg";

        if (isVideoModeJob() && ![".mp4", ".webm", ".mov"].includes(ext)) continue;

        const urlUuidMatch = url.match(/generated\/([a-f0-9-]+)\//);
        images.push({ data: b64, source_url: url, ext, filename: urlUuidMatch ? urlUuidMatch[1] : "" });
      } catch { failedUrls.push(url); }
    }

    // Server-side download for failed URLs
    if (failedUrls.length) {
      try {
        await fetch(S.studioUrl + "/api/animator/grabber/download-urls", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ projectId: S.projectId, scenes: [{ scene: parseInt(num), urls: failedUrls }] }),
        });
      } catch {}
    }

    if (!images.length && !failedUrls.length) {
      if (sc) sc.status = "error";
      render();
      return;
    }

    if (!images.length) {
      if (sc) sc.status = failedUrls.length ? "sent" : "error";
      S.sentScenes[num] = true;
      render();
      return;
    }

    // Send via WebSocket or HTTP
    if (S.wsConnected) {
      try {
        sendWS({ type: "ASSET_UPLOAD", projectId: S.projectId, scene: parseInt(num), images });
        if (sc) sc.status = "sent";
        S.sentScenes[num] = true;
        console.log("Scene", num, "- sent", images.length, "file(s) via WebSocket");
      } catch {
        S.wsConnected = false;
      }
    }

    if (!S.wsConnected) {
      try {
        const r = await fetch(S.studioUrl + "/api/animator/grabber/upload", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ projectId: S.projectId, scenes: [{ scene: parseInt(num), images }] }),
        });
        if (r.ok) { if (sc) sc.status = "sent"; S.sentScenes[num] = true; }
        else { if (sc) sc.status = "error"; }
      } catch { if (sc) sc.status = "error"; }
    }
    render();
  }

  // ── Typing Engine ──────────────────────────────────────

  function shouldStopTyping(runId) {
    if (typeof runId === "number") return !S.typing.active || S.typing.stopRequested || S.typing.runId !== runId;
    return !S.typing.active || S.typing.stopRequested;
  }

  function isTypingSelected(item) { return item && item.selected !== false; }
  function getSelectedTypingItems() { return S.typing.queue.filter(isTypingSelected); }

  function resetTypingItem(item) {
    if (!item) return false;
    item.status = "queued";
    item.error = null;
    item.errorCount = 0;
    item.videoUrl = null;
    item.allVideoUrls = null;
    return true;
  }

  async function doCountdown(seconds, type, runId) {
    S.typing.countdown = seconds;
    S.typing.countdownType = type;
    render();
    for (let i = seconds; i > 0; i--) {
      if (shouldStopTyping(runId)) break;
      S.typing.countdown = i;
      render();
      await sleep(1000);
    }
    S.typing.countdown = 0;
    S.typing.countdownType = "";
    render();
  }

  function addSeen(seenVideoUrls, url) {
    if (!url) return;
    const clean = url.replace(/\?.*$/, "");
    seenVideoUrls.add(clean);
    const um = clean.match(/\/users\/([a-f0-9-]+)\/generated\/([a-f0-9-]+)\//);
    if (um) seenVideoUrls.add("https://assets.grok.com/users/" + um[1] + "/generated/" + um[2] + "/generated_video.mp4");
  }

  async function startTyping() {
    if (S.typing.active || S.typing.starting) return;
    const tq = S.typing.queue;
    if (!tq.length || !getSelectedTypingItems().length) { render(); return; }

    S.typing.starting = true;
    S.typing.stopRequested = false;
    S.typing.autoPaused = false;

    // Re-queue errors
    for (const q of tq) {
      if (isTypingSelected(q) && (q.status === "error" || q.status === "failed") && (q.errorCount || 0) < 3) {
        q.status = "queued";
      }
    }

    let runItems = getSelectedTypingItems().filter(q => q.status !== "typed");
    if (!runItems.length) {
      // All typed - re-run all
      for (const q of getSelectedTypingItems()) {
        if (q.status === "typed") resetTypingItem(q);
      }
      runItems = getSelectedTypingItems().filter(q => q.status !== "typed");
    }
    if (!runItems.length) { S.typing.starting = false; render(); return; }

    const runId = S.typing.runId + 1;
    S.typing.runId = runId;
    S.typing.active = true;
    S.typing.starting = false;
    S.typing.typedCount = 0;
    S.typing.batchCount = 0;
    updateHistoryForProjects(getUniqueProjectIds(runItems), {
      status: "running",
      startedAt: Date.now(),
      aspectRatio: S.aspectRatio,
      mode: S.grokMode,
      duration: S.grokDuration,
    });
    render();
    console.log("=== TYPING", runItems.length, "prompts ===");

    try { await setupGrokMode(); } catch (e) { console.warn("Mode setup failed:", e.message); }

    // Collect existing video URLs to ignore
    const seenVideoUrls = new Set();
    document.querySelectorAll('video[src*="assets.grok.com"]').forEach(v => addSeen(seenVideoUrls, v.src || ""));
    document.querySelectorAll('img[src*="assets.grok.com"][src*="/generated/"]').forEach(img => addSeen(seenVideoUrls, img.src || ""));
    const sdv = document.getElementById("sd-video");
    if (sdv?.src) addSeen(seenVideoUrls, sdv.src);

    for (let i = 0; i < tq.length; i++) {
      if (shouldStopTyping(runId)) break;
      const item = tq[i];
      if (!isTypingSelected(item) || item.status === "typed") continue;
      if ((item.errorCount || 0) >= 3) { item.status = "failed"; continue; }

      S.typing.currentIndex = i;
      item.status = "typing";
      updateHistoryEntry(item.projectId || S.projectId, { status: "running" });
      sendWS({ type: "STATUS_UPDATE", projectId: S.projectId, scene: parseInt(item.scene), status: "typing" });
      render();

      try {
        document.querySelectorAll('video[src*="assets.grok.com"]').forEach(v => addSeen(seenVideoUrls, v.src || ""));
        await resetGrokInput();
        await sleep(500);
        try { await setupGrokMode(); } catch {}

        // Upload storyboard image if available
        if (item.imageUrl && item.imageUrl.startsWith("data:")) {
          item.imageUrl = await uploadImageToGrok(item.imageUrl);
          if (S.scenes[item.scene]) S.scenes[item.scene].imageUrl = item.imageUrl;
        }

        await typeIntoGrok(item.fullPrompt);
        console.log("Submitted scene", item.scene, "- waiting for generation...");

        // Capture the last article as this scene's response container + inject badge
        await sleep(500);
        captureContainerForScene(item.scene);

        await sleep(1500);
        if (checkRateLimit()) {
          item.status = "queued";
          render();
          await handleRateLimitCooldown();
          await typeIntoGrok(item.fullPrompt);
          await sleep(500);
          captureContainerForScene(item.scene);
          await sleep(1500);
          if (checkRateLimit()) {
            item.status = "error";
            item.errorCount = (item.errorCount || 0) + 1;
            item.error = "Rate limit persists after cooldown";
            updateHistoryEntry(item.projectId || S.projectId);
            render();
            continue;
          }
        }

        item.status = "generating";
        sendWS({ type: "STATUS_UPDATE", projectId: S.projectId, scene: parseInt(item.scene), status: "generating" });
        updateHistoryEntry(item.projectId || S.projectId, { status: "running" });
        render();

        const genResult = await waitForGeneration(item.scene, seenVideoUrls, undefined, runId);
        if (shouldStopTyping(runId)) { if (item.status === "generating") item.status = "queued"; break; }
        if (!genResult && S.typing.rateLimited) { item.status = "queued"; render(); i--; continue; }

        if (genResult) {
          addSeen(seenVideoUrls, genResult.primary);
          (genResult.allUrls || []).forEach(u => addSeen(seenVideoUrls, u));
          item.status = "typed";
          item.videoUrl = genResult.primary;
          item.allVideoUrls = genResult.allUrls || [genResult.primary];
          S.typing.typedCount++;
          S.typing.batchCount++;

          const sc = S.scenes[item.scene];
          if (sc) {
            sc.urls = item.allVideoUrls;
            sc.previewUrl = genResult.primary.replace(/generated_video\.mp4(\?.*)?$/, "preview_image.jpg");
            sc.fileCount = item.allVideoUrls.length;
            sc.status = "ready";
          }
          updateHistoryEntry(item.projectId || S.projectId);
          render();

          if (!shouldStopTyping(runId)) {
            try { await sendResults(item.scene, item.allVideoUrls); } catch (e) {
              console.error("Immediate send failed:", e.message);
            }
          }
        } else {
          item.errorCount = (item.errorCount || 0) + 1;
          item.status = "error";
          updateHistoryEntry(item.projectId || S.projectId);
        }
        render();

        // Wait before next
        const hasMore = tq.slice(i + 1).some(q => isTypingSelected(q) && q.status !== "typed" && q.status !== "failed");
        if (hasMore && !shouldStopTyping(runId)) {
          await doCountdown(5, "next", runId);
          await waitForPageReady();
        }
      } catch (e) {
        item.errorCount = (item.errorCount || 0) + 1;
        item.status = "error";
        updateHistoryEntry(item.projectId || S.projectId);
        console.error("Failed scene", item.scene, ":", e.message);
        render();
        await doCountdown(5, "retry", runId);
      }
    }

    if (shouldStopTyping(runId)) {
      S.typing.currentIndex = -1;
      updateHistoryForProjects(getUniqueProjectIds(tq), { status: "stopped", endedAt: Date.now() });
      render();
      return;
    }

    // Retry pass
    for (let retry = 0; retry < 2; retry++) {
      const failedItems = tq.filter(q => isTypingSelected(q) && q.status === "error" && (q.errorCount || 0) < 3);
      if (!failedItems.length || shouldStopTyping(runId)) break;
      await doCountdown(5, "retry", runId);
      await waitForPageReady();

      for (const item of failedItems) {
        if (shouldStopTyping(runId)) break;
        item.status = "typing";
        sendWS({ type: "STATUS_UPDATE", projectId: S.projectId, scene: parseInt(item.scene), status: "typing" });
        S.typing.currentIndex = tq.indexOf(item);
        updateHistoryEntry(item.projectId || S.projectId, { status: "running" });
        render();

        try {
          document.querySelectorAll('video[src*="assets.grok.com"]').forEach(v => addSeen(seenVideoUrls, v.src || ""));
          if (item.imageUrl && item.imageUrl.startsWith("data:")) {
            item.imageUrl = await uploadImageToGrok(item.imageUrl);
            if (S.scenes[item.scene]) S.scenes[item.scene].imageUrl = item.imageUrl;
          }
          await typeIntoGrok(item.fullPrompt);
          await sleep(500);
          captureContainerForScene(item.scene);
          item.status = "generating";
          sendWS({ type: "STATUS_UPDATE", projectId: S.projectId, scene: parseInt(item.scene), status: "generating" });
          updateHistoryEntry(item.projectId || S.projectId, { status: "running" });
          render();

          const genResult = await waitForGeneration(item.scene, seenVideoUrls, undefined, runId);
          if (shouldStopTyping(runId)) { if (item.status === "generating") item.status = "queued"; break; }
          if (genResult) {
            addSeen(seenVideoUrls, genResult.primary);
            (genResult.allUrls || []).forEach(u => addSeen(seenVideoUrls, u));
            item.status = "typed";
            item.videoUrl = genResult.primary;
            item.allVideoUrls = genResult.allUrls || [genResult.primary];
            S.typing.typedCount++;
            const sc = S.scenes[item.scene];
            if (sc) { sc.urls = item.allVideoUrls; sc.fileCount = item.allVideoUrls.length; sc.status = "ready"; }
            updateHistoryEntry(item.projectId || S.projectId);
            render();
            if (!shouldStopTyping(runId)) { try { await sendResults(item.scene, item.allVideoUrls); } catch {} }
          } else {
            item.errorCount = (item.errorCount || 0) + 1;
            item.status = item.errorCount >= 3 ? "failed" : "error";
            updateHistoryEntry(item.projectId || S.projectId);
          }
          render();
        } catch (e) {
          item.errorCount = (item.errorCount || 0) + 1;
          item.status = item.errorCount >= 3 ? "failed" : "error";
          updateHistoryEntry(item.projectId || S.projectId);
          render();
          await doCountdown(5, "retry", runId);
        }
      }
    }

    // Verify pass - re-send unsent
    await fetchStatus();
    for (const q of tq) {
      if (shouldStopTyping(runId)) break;
      if (q.status === "typed" && q.videoUrl && !S.sentScenes[q.scene]) {
        try { await sendResults(q.scene, q.allVideoUrls || [q.videoUrl]); } catch {}
      }
    }

    // Rescan thumbnails using scene-to-container map
    if (!shouldStopTyping(runId) && S.projectId) {
      for (const [sceneNum, container] of Object.entries(sceneContainerMap)) {
        if (shouldStopTyping(runId)) break;
        if (S.sentScenes[sceneNum]) continue;
        const thumbImg = container.querySelector('button img[alt^="Thumbnail"]');
        if (!thumbImg) continue;
        const thumbBtn = thumbImg.closest("button");
        if (!thumbBtn) continue;
        try {
          simulateClick(thumbBtn);
          await sleep(1200);
          let sdVideo = document.getElementById("sd-video");
          for (let a = 0; a < 6 && (!sdVideo || !sdVideo.src); a++) { await sleep(400); sdVideo = document.getElementById("sd-video"); }
          let videoUrl = sdVideo ? (sdVideo.src || "") : "";
          if (!videoUrl) {
            const src = thumbImg.src || "";
            const uuidMatch = src.match(/generated\/([a-f0-9-]+)\//);
            const userMatch = src.match(/users\/([a-f0-9-]+)\//);
            if (uuidMatch && userMatch) videoUrl = "https://assets.grok.com/users/" + userMatch[1] + "/generated/" + uuidMatch[1] + "/generated_video.mp4";
          }
          if (!videoUrl) continue;
          const sc = S.scenes[sceneNum];
          if (sc && !S.sentScenes[sceneNum]) {
            sc.urls = [videoUrl]; sc.fileCount = 1; sc.status = "ready";
            render();
            await sendResults(sceneNum, [videoUrl]);
          }
        } catch {}
      }
    }

    // Final status
    await fetchStatus();
    const finalScope = getSelectedTypingItems();
    const finalTyped = finalScope.filter(q => q.status === "typed").length;
    const finalFailed = finalScope.filter(q => q.status === "error" || q.status === "failed").length;
    updateHistoryForProjects(getUniqueProjectIds(finalScope), { endedAt: Date.now() });
    console.log("=== BATCH COMPLETE:", finalTyped, "/", finalScope.length, "succeeded,", finalFailed, "failed ===");
    sendWS({ type: "JOB_COMPLETE", projectId: S.projectId, typed: finalTyped, total: finalScope.length, failed: finalFailed });

    try {
      if (Notification.permission === "granted") {
        new Notification("STS Grok Sync", {
          body: finalTyped + "/" + finalScope.length + " scenes completed" + (finalFailed > 0 ? " (" + finalFailed + " failed)" : ""),
        });
      }
    } catch {}

    // Switch to ScriptToScene Studio tab after job completes
    try { chrome.runtime.sendMessage({ type: "FOCUS_STUDIO_TAB" }); } catch {}

    S.typing.active = false;
    S.typing.stopRequested = false;
    S.typing.currentIndex = -1;
    S.typing.countdown = 0;
    S.typing.countdownType = "";
    render();
  }

  function stopTyping() {
    S.typing.stopRequested = true;
    S.typing.autoPaused = true;
    S.typing.active = false;
    S.typing.starting = false;
    S.typing.countdown = 0;
    S.typing.countdownType = "";
    S.typing.nextAutoStartAt = Date.now() + 15000;

    // Try to stop Grok generation
    try {
      let stopBtn = document.querySelector('button[aria-label="Stop generation"], button[aria-label="Stop"]');
      if (!stopBtn) {
        for (const b of document.querySelectorAll("button")) {
          const t = (b.textContent || "").trim().toLowerCase();
          if ((t === "stop" || t === "stop generating") && isElReady(b) && !b.closest("#sts-sync")) { stopBtn = b; break; }
        }
      }
      if (stopBtn && isElReady(stopBtn)) simulateClick(stopBtn);
    } catch {}

    for (const q of S.typing.queue) {
      if (q.status === "typing" || q.status === "generating") q.status = "queued";
    }
    S.typing.currentIndex = -1;
    updateHistoryForProjects(getUniqueProjectIds(S.typing.queue), {
      status: "stopped",
      endedAt: Date.now(),
      activate: false,
    });
    console.log("Typing stopped");
    render();
  }

  async function runTestPrompt() {
    if (S.typing.active || S.typing.starting) {
      console.log("[TEST] Already running");
      return;
    }

    const testProjectId = "TEST";
    const testScene = "0";
    const testPrompt = "generate a cinematic 6 second video, medium shot, a solitary stick figure standing in a vast empty white room, soft diffused lighting, subtle camera push-in, clean minimal scene";
    const runId = S.typing.runId + 1;
    S.typing.runId = runId;
    S.typing.active = true;
    S.typing.starting = false;
    S.typing.stopRequested = false;
    S.typing.autoPaused = true;
    S.typing.currentIndex = 0;
    S.typing.typedCount = 0;
    S.typing.batchCount = 0;
    S.projectId = testProjectId;
    S.sentScenes = {};
    S.scenes = {
      [testScene]: {
        prompt: testPrompt,
        status: "pending",
        urls: [],
        fileCount: 0,
        imageUrl: null,
        projectId: testProjectId,
      },
    };
    S.typing.queue = [{
      scene: testScene,
      displayPrompt: testPrompt,
      fullPrompt: testPrompt,
      prompt: testPrompt,
      selected: true,
      status: "queued",
      projectId: testProjectId,
      imageUrl: null,
      mode: S.grokMode,
      duration: S.grokDuration,
      aspectRatio: S.aspectRatio,
      error: null,
      errorCount: 0,
    }];

    updateHistoryEntry(testProjectId, {
      forceNew: true,
      source: "test",
      status: "running",
      startedAt: Date.now(),
      aspectRatio: S.aspectRatio,
      mode: S.grokMode,
      duration: S.grokDuration,
    });
    render();

    const item = S.typing.queue[0];
    const seenVideoUrls = new Set();
    document.querySelectorAll('video[src*="assets.grok.com"]').forEach((v) => addSeen(seenVideoUrls, v.src || ""));
    document.querySelectorAll('img[src*="assets.grok.com"][src*="/generated/"]').forEach((img) => addSeen(seenVideoUrls, img.src || ""));
    const sdv = document.getElementById("sd-video");
    if (sdv?.src) addSeen(seenVideoUrls, sdv.src);

    try {
      await resetGrokInput();
      await sleep(500);
      try { await setupGrokMode(); } catch (e) { console.warn("[TEST] Mode setup failed:", e.message); }

      item.status = "typing";
      updateHistoryEntry(testProjectId, { source: "test", status: "running" });
      render();
      await typeIntoGrok(testPrompt);
      if (shouldStopTyping(runId)) throw new Error("Test stopped");

      await sleep(500);
      captureContainerForScene(testScene);

      item.status = "generating";
      updateHistoryEntry(testProjectId, { source: "test", status: "running" });
      render();

      const genResult = await waitForGeneration(testScene, seenVideoUrls, undefined, runId);
      if (shouldStopTyping(runId)) throw new Error("Test stopped");

      if (genResult) {
        addSeen(seenVideoUrls, genResult.primary);
        (genResult.allUrls || []).forEach((url) => addSeen(seenVideoUrls, url));
        item.status = "typed";
        item.videoUrl = genResult.primary;
        item.allVideoUrls = genResult.allUrls || [genResult.primary];
        S.typing.typedCount = 1;
        S.typing.batchCount = 1;
        if (S.scenes[testScene]) {
          S.scenes[testScene].urls = item.allVideoUrls;
          S.scenes[testScene].previewUrl = genResult.primary.replace(/generated_video\.mp4(\?.*)?$/, "preview_image.jpg");
          S.scenes[testScene].fileCount = item.allVideoUrls.length;
          S.scenes[testScene].status = "ready";
        }
        updateHistoryEntry(testProjectId, { source: "test", endedAt: Date.now() });
      } else {
        item.status = "error";
        item.error = "No video generated";
        if (S.scenes[testScene]) S.scenes[testScene].status = "error";
        updateHistoryEntry(testProjectId, { source: "test", status: "failed", endedAt: Date.now() });
      }
    } catch (e) {
      const msg = e?.message || String(e);
      if (!shouldStopTyping(runId)) {
        item.status = "error";
        item.error = msg;
        if (S.scenes[testScene]) S.scenes[testScene].status = "error";
      }
      updateHistoryEntry(testProjectId, {
        source: "test",
        status: shouldStopTyping(runId) ? "stopped" : "failed",
        endedAt: Date.now(),
      });
      console.error("[TEST] Failed:", msg);
    } finally {
      S.typing.active = false;
      S.typing.starting = false;
      S.typing.stopRequested = false;
      S.typing.currentIndex = -1;
      S.typing.countdown = 0;
      S.typing.countdownType = "";
      render();
    }
  }

  // ── API ────────────────────────────────────────────────

  function isJobComplete() {
    if (!S.projectId) return false;
    const scenes = Object.values(S.scenes);
    return scenes.length > 0 && scenes.every(sc => sc.status === "downloaded" || sc.status === "error");
  }

  async function fetchPending() {
    if (isJobComplete()) return;
    try {
      const r = await fetch(S.studioUrl + "/api/animator/grabber/pending");
      S.connected = true;
      S._fetchErrors = 0;
      if (!r.ok) { render(); return; }
      const d = await r.json();
      if (!d || !d.projectId || !d.scenes) { render(); return; }
      S.projectId = d.projectId;
      S.arguments = d.arguments || "";
      S.aspectRatio = d.aspect_ratio || "9:16";
      S.grokMode = d.grok_mode || "video";
      S.grokQuality = d.grok_quality || "480p";
      S.grokDuration = d.grok_duration || "6s";
      if ("auto_type" in d) S.autoType = !!d.auto_type;

      for (const sc of d.scenes) {
        const k = String(sc.scene);
        const imgData = sc.image || null;
        if (!S.scenes[k]) {
          S.scenes[k] = { prompt: sc.prompt, status: "pending", urls: [], fileCount: 0, imageUrl: imgData, projectId: d.projectId };
        } else if (!S.scenes[k].projectId) {
          S.scenes[k].projectId = d.projectId;
        }
        const existing = S.typing.queue.find(q => q.scene === k);
        if (!existing) {
          const args = S.arguments ? " " + S.arguments : "";
          S.typing.queue.push({
            scene: k, displayPrompt: sc.prompt,
            fullPrompt: sc.prompt + args,
            selected: true, status: "queued", imageUrl: imgData, projectId: d.projectId,
          });
        } else if (!existing.projectId) {
          existing.projectId = d.projectId;
        }
      }
      updateHistoryEntry(d.projectId, {
        source: "job",
        status: "queued",
        aspectRatio: S.aspectRatio,
        mode: S.grokMode,
        duration: S.grokDuration,
      });
    } catch { S.connected = false; S._fetchErrors++; }
  }

  async function fetchStatus() {
    if (!S.projectId) return;
    try {
      const r = await fetch(S.studioUrl + "/api/animator/grabber/status/" + encodeURIComponent(S.projectId));
      S.connected = true;
      if (!r.ok) return;
      const d = await r.json();
      for (const [num, info] of Object.entries(d.scene_statuses || {})) {
        const sc = S.scenes[num];
        if (!sc) continue;
        const serverFiles = (info.local_files || []).length;
        if (info.status === "ready" && serverFiles > 0) {
          if (sc.status !== "downloaded" || sc.fileCount !== serverFiles) {
            sc.status = "downloaded"; sc.fileCount = serverFiles;
          }
        } else if (info.status === "error") {
          sc.status = "error";
        }
      }
    } catch { S.connected = false; }
  }

  async function syncNow() {
    // Manual sync: re-fetch pending + status
    await fetchPending();
    await fetchStatus();
    render();
  }

  // ── Polling ────────────────────────────────────────────

  async function poll() {
    S.lastPoll = Date.now();
    await fetchPending();
    await fetchStatus();

    if (isJobComplete() && !S.jobComplete) {
      S.jobComplete = true;
      console.log("[STS] All scenes complete - slowing polling");
    }

    render();

    // Auto-start typing
    if (S.autoType && !S.typing.active && !S.typing.starting && !S.typing.autoPaused && Date.now() >= (S.typing.nextAutoStartAt || 0)) {
      const hasQueued = S.typing.queue.some(q => isTypingSelected(q) && q.status === "queued");
      if (hasQueued) { console.log("Auto-type: starting typing"); startTyping(); }
    }

    S.pollInterval = S.jobComplete ? 60000 : (S.connected ? 5000 : Math.min((S.pollInterval || 5000) * 2, 30000));
  }

  // ── UI ─────────────────────────────────────────────────

  function updateProgressLabel(text) {
    const el = $id("sts-prog-label");
    if (el) el.textContent = text;
  }

  function renderAutoType() {
    const el = $id("sts-head-autotype");
    if (!el) return;
    el.className = "sts-head-autotype " + (S.autoType ? "on" : "off");
    el.textContent = S.autoType ? "AUTO" : "MANUAL";
  }

  function getTypingCountdownLabel() {
    if (!S.typing.countdown) return "";
    const labels = { next: "next in", retry: "retry in", settle: "settle" };
    return (labels[S.typing.countdownType] || S.typing.countdownType) + " " + S.typing.countdown + "s";
  }

  function escHtml(s) { const d = document.createElement("div"); d.textContent = s; return d.innerHTML; }
  function encodeCopyText(s) { return encodeURIComponent(String(s || "")); }

  async function copyText(text) {
    const value = String(text || "");
    if (!value.trim()) throw new Error("No prompt to copy");

    if (navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(value);
        return;
      } catch {}
    }

    const input = document.createElement("textarea");
    input.value = value;
    input.setAttribute("readonly", "");
    input.style.position = "fixed";
    input.style.left = "-9999px";
    input.style.opacity = "0";
    document.body.appendChild(input);
    input.select();
    input.setSelectionRange(0, input.value.length);
    const copied = document.execCommand("copy");
    input.remove();
    if (!copied) throw new Error("Copy failed");
  }

  function flashCopyButton(button, label = "Copied", cls = "copied") {
    if (!button) return;
    const original = button.dataset.defaultLabel || button.textContent || "Copy";
    button.dataset.defaultLabel = original;
    if (button._copyTimer) clearTimeout(button._copyTimer);
    button.textContent = label;
    button.classList.remove("copied", "failed");
    if (cls) button.classList.add(cls);
    button._copyTimer = setTimeout(() => {
      button.textContent = original;
      button.classList.remove("copied", "failed");
    }, 1200);
  }

  function hideImagePreview() {
    const preview = document.getElementById("sts-img-overlay");
    if (preview) preview.remove();
  }

  function moveImagePreview(e) {
    const preview = document.getElementById("sts-img-overlay");
    if (!preview || !e) return;
    const margin = 18;
    const offset = 20;
    const rect = preview.getBoundingClientRect();
    let left = e.clientX + offset;
    let top = e.clientY + offset;

    if (left + rect.width + margin > window.innerWidth) {
      left = e.clientX - rect.width - offset;
    }
    if (top + rect.height + margin > window.innerHeight) {
      top = e.clientY - rect.height - offset;
    }

    left = Math.max(margin, Math.min(left, window.innerWidth - rect.width - margin));
    top = Math.max(margin, Math.min(top, window.innerHeight - rect.height - margin));

    preview.style.left = left + "px";
    preview.style.top = top + "px";
  }

  function showImagePreview(src, e) {
    if (!src) return;
    let preview = document.getElementById("sts-img-overlay");
    if (!preview) {
      preview = document.createElement("div");
      preview.id = "sts-img-overlay";
      preview.innerHTML = '<img alt="Scene preview">';
      document.body.appendChild(preview);
    }
    const img = preview.querySelector("img");
    if (!img) return;
    if (img.src !== src) img.src = src;
    if (e) moveImagePreview(e);
    img.onload = () => moveImagePreview(e || { clientX: window.innerWidth / 2, clientY: window.innerHeight / 2 });
  }

  function pinCurrentTypingRowToTop() {
    if (S.activeTab !== "typing" || S.typing.currentIndex < 0) return;
    const list = $id("sts-list");
    if (!list) return;
    const row = list.querySelector('.sts-row[data-idx="' + S.typing.currentIndex + '"]');
    if (!row) return;
    const targetTop = Math.max(0, row.offsetTop - 6);
    if (Math.abs(list.scrollTop - targetTop) <= 6) return;
    list.scrollTop = targetTop;
  }

  function syncCollapsedUi() {
    const pill = $id("sts-pill");
    const panel = $id("sts-panel");
    if (pill) pill.style.display = S.collapsed ? "" : "none";
    if (panel) panel.style.display = S.collapsed ? "none" : "";
  }

  function render() {
    saveState(); // persist on every state change (debounced)
    hideImagePreview();
    syncCollapsedUi();
    const historyItems = pruneHistoryEntries(S.history.items);
    S.history.items = historyItems;
    const historyCount = historyItems.length;
    const tq = S.typing.queue;
    const selectedTq = getSelectedTypingItems();
    const selectedTotal = selectedTq.length;
    const selectedTyped = selectedTq.filter(q => q.status === "typed").length;
    let queued = 0, typed = 0;
    tq.forEach(q => { if (q.status === "queued") queued++; else if (q.status === "typed") typed++; });

    let rdy = 0, sent = 0;
    for (const sc of Object.values(S.scenes)) {
      if (sc.status === "ready") rdy++;
      else if (sc.status === "sent" || sc.status === "downloaded") sent++;
    }

    // Pill
    const pillDot = $id("sts-pill-dot");
    if (pillDot) pillDot.classList.toggle("on", S.connected || S.wsConnected);
    const pillP = $id("sts-pill-p");
    if (pillP) pillP.textContent = queued;
    const pillR = $id("sts-pill-r");
    if (pillR) pillR.textContent = rdy + sent;
    const pillProj = $id("sts-pill-proj");
    if (pillProj) pillProj.textContent = S.projectId || "";

    // Header
    const headDot = $id("sts-head-dot");
    if (headDot) headDot.classList.toggle("on", S.connected || S.wsConnected);
    // Port
    try {
      const portMatch = S.studioUrl.match(/:(\d+)/);
      const headPort = $id("sts-head-port");
      if (headPort) { headPort.textContent = portMatch ? ":" + portMatch[1] : ""; headPort.style.display = portMatch ? "" : "none"; }
    } catch {}

    // Connection bar — always visible, reflects real-time WS state
    const connBar = $id("sts-conn-bar");
    if (connBar) {
      connBar.style.display = "flex";
      const connIcon = $id("sts-conn-icon");
      const connMsg = $id("sts-conn-msg");
      if (S.wsConnected) {
        connBar.classList.add("ok");
        if (connIcon) connIcon.textContent = "\u2713";
        if (connMsg) connMsg.textContent = "Connected";
      } else {
        connBar.classList.remove("ok");
        if (connIcon) connIcon.textContent = "\u26A0";
        if (connMsg) connMsg.textContent = "Backend disconnected";
      }
    }

    // Stats
    const nq = $id("sts-n-q"); if (nq) nq.textContent = queued;
    const nt = $id("sts-n-typed"); if (nt) nt.textContent = typed;
    const nr = $id("sts-n-rdy"); if (nr) nr.textContent = rdy;
    const totalScenes = Object.keys(S.scenes).length;
    const ns = $id("sts-n-sent"); if (ns) ns.textContent = sent + "/" + totalScenes;
    const historyTabCount = $id("sts-history-tab-count");
    if (historyTabCount) historyTabCount.textContent = String(historyCount);

    // Header aspect ratio indicator
    const headRatio = $id("sts-head-ratio");
    if (headRatio) {
        if (S.aspectRatio) {
            headRatio.textContent = S.aspectRatio;
            headRatio.style.display = "";
        } else {
            headRatio.style.display = "none";
        }
    }

    // Progress
    if (S.activeTab === "typing") {
      const pct = selectedTotal > 0 ? (selectedTyped / selectedTotal) * 100 : 0;
      const fill = $id("sts-prog-fill"); if (fill) fill.style.width = pct + "%";
      const label = $id("sts-prog-label");
      const cd = $id("sts-prog-cd");

      if (S.typing.active && label) {
        const ci = S.typing.currentIndex;
        const curItem = ci >= 0 && tq[ci] ? tq[ci] : null;
        if (curItem && curItem.status !== "generating") {
          const pos = curItem ? (selectedTq.indexOf(curItem) + 1) : 0;
          label.textContent = selectedTotal > 0 ? "Typing " + pos + "/" + selectedTotal : "Typing...";
        }
        if (cd) { cd.textContent = getTypingCountdownLabel(); cd.className = "sts-cd" + ((S.typing.countdownType === "next" || S.typing.countdownType === "retry") ? " cool" : ""); }
      } else if (label && selectedTotal > 0) {
        label.textContent = selectedTyped === selectedTotal ? "All selected typed" : "Selected: " + selectedTyped + "/" + selectedTotal;
        if (cd) cd.textContent = "";
      } else if (label) {
        label.textContent = tq.length > 0 ? "No prompts selected" : "No prompts queued";
        if (cd) cd.textContent = "";
      }
    } else if (S.activeTab === "history") {
      const fill = $id("sts-prog-fill"); if (fill) fill.style.width = "0%";
      const label = $id("sts-prog-label");
      const cd = $id("sts-prog-cd");
      if (label) label.textContent = S.history.items.length ? S.history.items.length + " runs in last 7 days" : "No history yet";
      if (cd) { cd.textContent = ""; cd.className = "sts-cd"; }
    }

    // Action button
    const btn = $id("sts-action-btn");
    if (btn) {
      if (S.typing.active) {
        btn.textContent = "Stop"; btn.className = "sts-btn sts-btn-danger"; btn.disabled = false;
      } else if (S.typing.starting) {
        btn.textContent = "Starting..."; btn.className = "sts-btn sts-btn-ghost"; btn.disabled = true;
      } else {
        btn.textContent = selectedTotal > 0 ? "Start Typing" : "Waiting for Job";
        btn.className = "sts-btn sts-btn-primary"; btn.disabled = false;
      }
    }

    // Retry button
    const retryBtn = $id("sts-retry-btn");
    const hasErrors = tq.some(q => isTypingSelected(q) && (q.status === "error" || q.status === "failed"));
    if (retryBtn) retryBtn.style.display = (hasErrors && !S.typing.active) ? "" : "none";
    const testBtn = $id("sts-test-btn");
    if (testBtn) testBtn.style.display = S.showTestButton ? "" : "none";

    // List
    const list = $id("sts-list");
    if (!list) return;

    if (S.activeTab === "typing") {
      if (!tq.length) {
        list.innerHTML = '<div class="sts-empty"><div class="sts-empty-icon">&#x270D;</div>No prompts queued yet.<br>Click Assets Grabber in Studio.</div>';
        return;
      }
      // Group items by projectId, preserving original indices
      let html = "";
      let lastPid = null;
      tq.forEach((q, i) => {
        const pid = q.projectId || "";
        if (pid !== lastPid) {
          html += '<div class="sts-group-label">' + escHtml(pid || "Unknown") + '</div>';
          lastPid = pid;
        }
        const fullPrompt = q.displayPrompt || q.prompt || q.fullPrompt || "";
        const pr = fullPrompt.length > 46 ? fullPrompt.substring(0, 46) + "..." : fullPrompt;
        let sHTML = "", meta = "";
        const isSelected = isTypingSelected(q);
        const isCurrent = S.typing.active && i === S.typing.currentIndex;
        if (q.status === "queued") { sHTML = '<div class="sts-d-q"></div>'; meta = "queued"; }
        else if (q.status === "typing") { sHTML = '<div class="sts-d-typing"></div>'; meta = "typing..."; }
        else if (q.status === "generating") { sHTML = '<div class="sts-d-proc"></div>'; meta = "generating..."; }
        else if (q.status === "typed") { sHTML = '<span class="sts-d-typed">&#x2714;</span>'; meta = "typed"; }
        else if (q.status === "failed" || q.status === "error") { sHTML = '<span class="sts-d-err">&#x2718;</span>'; meta = q.status + (q.errorCount > 1 ? " (" + q.errorCount + "x)" : ""); }
        if (!isSelected) meta = "unchecked" + (meta ? " \u00b7 " + meta : "");
        const rowCls = "sts-row" +
          (isCurrent ? " highlight" : "") +
          (isCurrent && q.status === "generating" ? " active-generating" : "") +
          ((q.status === "error" || q.status === "failed") ? " error-clickable" : "");
        const thumbHtml = q.imageUrl ? '<img class="sts-row-thumb" src="' + q.imageUrl + '" alt="">' : '<div class="sts-row-thumb sts-row-thumb-empty">' + q.scene + "</div>";
        const checkboxHtml = '<label class="sts-row-check-wrap"><input type="checkbox" class="sts-row-check" data-role="typing-checkbox" data-idx="' + i + '"' + (isSelected ? " checked" : "") + (S.typing.active ? " disabled" : "") + "></label>";
        const copyBtnHtml = fullPrompt ? '<button class="sts-copy-btn" type="button" data-role="copy-prompt" data-copy-text="' + encodeCopyText(fullPrompt) + '" title="Copy full prompt">Copy</button>' : "";
        html += '<div class="' + rowCls + '" data-idx="' + i + '">' + checkboxHtml + thumbHtml + '<div class="sts-row-num">' + q.scene + '</div><div class="sts-row-info"><div class="sts-row-prompt">' + escHtml(pr) + '</div><div class="sts-row-meta">' + meta + "</div></div><div class=\"sts-row-status\">" + copyBtnHtml + sHTML + "</div></div>";
      });
      list.innerHTML = html;
      requestAnimationFrame(pinCurrentTypingRowToTop);
    } else if (S.activeTab === "sync") {
      const keys = Object.keys(S.scenes).sort((a, b) => parseInt(a) - parseInt(b));
      if (!keys.length) {
        list.innerHTML = '<div class="sts-empty"><div class="sts-empty-icon">&#x1F4E1;</div>Waiting for generations...</div>';
        return;
      }
      list.innerHTML = keys.map(num => {
        const sc = S.scenes[num];
        const fullPrompt = sc.prompt || "";
        const pr = fullPrompt.length > 52 ? fullPrompt.substring(0, 52) + "..." : fullPrompt;
        const badgeMap = {
          pending: ["pending", "pending"], processing: ["processing", "generating..."],
          ready: ["ready", sc.fileCount + " ready"], uploading: ["uploading", "uploading..."],
          sent: ["sent", sc.fileCount + " sent"], downloaded: ["downloaded", sc.fileCount + " synced"],
          error: ["error", "error"],
        };
        const [bCls, bText] = badgeMap[sc.status] || ["pending", sc.status];
        const copyBtnHtml = fullPrompt ? '<button class="sts-copy-btn" type="button" data-role="copy-prompt" data-copy-text="' + encodeCopyText(fullPrompt) + '" title="Copy full prompt">Copy</button>' : "";
        return '<div class="sts-card"><div class="sts-card-head"><div class="sts-card-num">' + num + '</div><div class="sts-card-prompt">' + escHtml(pr) + '</div>' + copyBtnHtml + '<span class="sts-card-badge sts-badge-' + bCls + '">' + bText + "</span></div></div>";
      }).join("");
    } else {
      const history = historyItems;
      if (!history.length) {
        list.innerHTML = '<div class="sts-empty"><div class="sts-empty-icon">&#x1F4DA;</div>No history yet.<br>Completed and stopped runs stay here for 7 days.</div>';
        return;
      }
      list.innerHTML = history.map((entry) => {
        const badge = getHistoryBadge(entry);
        const startedAt = entry.startedAt || entry.createdAt;
        let durationMs = entry.durationMs;
        const expanded = isHistoryExpanded(entry.id);
        if (!entry.endedAt && startedAt) durationMs = Date.now() - startedAt;
        const promptHtml = (entry.prompts || []).map((prompt) => {
          const fullPrompt = prompt.prompt || "";
          let meta = prompt.status || prompt.syncStatus || "queued";
          if (prompt.error) meta += " - " + prompt.error;
          return '<div class="sts-history-prompt">' +
            '<div class="sts-history-prompt-num">' + escHtml(String(prompt.scene || "?")) + '</div>' +
            '<div class="sts-history-prompt-body">' +
              '<div class="sts-history-prompt-text">' + escHtml(fullPrompt) + '</div>' +
              '<div class="sts-history-prompt-meta">' + escHtml(meta) + '</div>' +
            '</div>' +
            (fullPrompt ? '<button class="sts-copy-btn sts-copy-btn-sm" type="button" data-role="copy-prompt" data-copy-text="' + encodeCopyText(fullPrompt) + '" title="Copy full prompt">Copy</button>' : '') +
          '</div>';
          }).join("");
        return '<div class="sts-history-card' + (expanded ? ' open' : ' collapsed') + '">' +
          '<div class="sts-history-head">' +
            '<div class="sts-history-title">' + escHtml(entry.projectId || "Unknown project") + '</div>' +
            (entry.source === "test" ? '<span class="sts-card-badge sts-badge-test">test</span>' : "") +
            '<span class="sts-card-badge ' + badge.cls + '">' + escHtml(badge.text) + '</span>' +
            '<button class="sts-history-toggle" type="button" data-entry-id="' + escHtml(entry.id || "") + '" aria-expanded="' + (expanded ? "true" : "false") + '" title="' + (expanded ? "Collapse prompts" : "Expand prompts") + '">' + (expanded ? '&#x25BE;' : '&#x25B8;') + '</button>' +
          '</div>' +
          '<div class="sts-history-sub">' + escHtml(formatHistoryTimestamp(startedAt)) + ' - ' + escHtml(formatHistoryAge(entry.updatedAt || startedAt)) + '</div>' +
          '<div class="sts-history-meta">' +
            '<span class="sts-history-chip sts-history-chip-time">duration ' + escHtml(formatHistoryDuration(durationMs)) + '</span>' +
            '<span class="sts-history-chip sts-history-chip-count">' + escHtml(String(entry.sceneCount || 0)) + ' prompts</span>' +
            '<span class="sts-history-chip sts-history-chip-done">' + escHtml(String(entry.completedCount || 0)) + ' done</span>' +
            '<span class="sts-history-chip sts-history-chip-failed">' + escHtml(String(entry.failedCount || 0)) + ' failed</span>' +
            (entry.aspectRatio ? '<span class="sts-history-chip sts-history-chip-setting">' + escHtml(entry.aspectRatio) + '</span>' : '') +
            (entry.mode ? '<span class="sts-history-chip sts-history-chip-mode">' + escHtml(entry.mode) + '</span>' : '') +
            (entry.duration ? '<span class="sts-history-chip sts-history-chip-setting">' + escHtml(entry.duration) + '</span>' : '') +
          '</div>' +
          (expanded ? '<div class="sts-history-prompts">' + promptHtml + '</div>' : '') +
        '</div>';
      }).join("");
    }
  }

  // ── Inject UI ──────────────────────────────────────────

  function injectUI() {
    const root = document.createElement("div");
    root.id = "sts-sync";

    root.innerHTML = `
<!-- Collapsed Pill -->
<div class="sts-pill" id="sts-pill">
  <div class="sts-pill-dot" id="sts-pill-dot"></div>
  <span class="sts-pill-label">STS Grok</span>
  <span class="sts-pill-proj" id="sts-pill-proj"></span>
  <div class="sts-pill-counts">
    <span class="sts-pill-count-label">Q</span><span class="sts-c-pend" id="sts-pill-p">0</span>
    <span class="sts-pill-count-label">R</span><span class="sts-c-rdy" id="sts-pill-r">0</span>
  </div>
</div>

<!-- Expanded Panel -->
<div class="sts-panel" id="sts-panel" style="display:none;">
  <!-- Header -->
  <div class="sts-head">
    <div class="sts-head-left">
      <div class="sts-head-dot" id="sts-head-dot"></div>
      <h3>STS Grok Sync</h3>
      <span class="sts-head-port" id="sts-head-port"></span>
      <span class="sts-head-ratio" id="sts-head-ratio" style="display:none;"></span>
      <span class="sts-head-autotype" id="sts-head-autotype" style="display:none;"></span>
    </div>
    <div class="sts-head-btns">
      <button class="sts-hb" id="sts-settings-btn" title="Settings">&#x2699;</button>
      <button class="sts-hb" id="sts-collapse-btn" title="Collapse">&#x2715;</button>
    </div>
  </div>

  <!-- Connection bar -->
  <div class="sts-conn-bar" id="sts-conn-bar" style="display:none;">
    <span id="sts-conn-icon"></span>
    <span id="sts-conn-msg">Backend disconnected</span>
  </div>

  <!-- Settings -->
  <div class="sts-settings" id="sts-settings">
    <label>URL</label>
    <input type="text" class="sts-url-input" id="sts-url-input" />
    <button class="sts-url-save" id="sts-url-save">Save</button>
    <label class="sts-settings-toggle" title="Show or hide the TEST button">
      <input type="checkbox" id="sts-show-test-toggle" />
      <span>Show TEST button</span>
    </label>
  </div>

  <!-- Stats -->
  <div class="sts-stats">
    <div class="sts-stat"><span class="sts-sv sts-c-pend" id="sts-n-q">0</span><span class="sts-sl">Queue</span></div>
    <div class="sts-stat"><span class="sts-sv sts-c-proc" id="sts-n-typed">0</span><span class="sts-sl">Typed</span></div>
    <div class="sts-stat"><span class="sts-sv sts-c-rdy" id="sts-n-rdy">0</span><span class="sts-sl">Done</span></div>
    <div class="sts-stat"><span class="sts-sv sts-c-sent" id="sts-n-sent">0</span><span class="sts-sl">Synced</span></div>
  </div>

  <!-- Tabs -->
  <div class="sts-tabs">
    <button class="sts-tab active" data-tab="typing">Typing</button>
    <button class="sts-tab" data-tab="sync">Sync</button>
    <button class="sts-tab" data-tab="history">History <span class="sts-tab-count" id="sts-history-tab-count">0</span></button>
  </div>

  <!-- Progress -->
  <div class="sts-progress">
    <div class="sts-prog-track"><div class="sts-prog-fill" id="sts-prog-fill"></div></div>
    <span class="sts-prog-label" id="sts-prog-label">No prompts queued</span>
    <span class="sts-cd" id="sts-prog-cd"></span>
  </div>

  <!-- List -->
  <div class="sts-list" id="sts-list">
    <div class="sts-empty"><div class="sts-empty-icon">&#x270D;</div>No prompts queued yet.<br>Click Assets Grabber in Studio.</div>
  </div>

  <!-- Actions -->
  <div class="sts-actions">
    <button class="sts-btn sts-btn-primary" id="sts-action-btn">Start Typing</button>
    <button class="sts-btn sts-btn-warn" id="sts-retry-btn" style="display:none;">Retry Failed</button>
    <button class="sts-btn sts-btn-ghost sts-btn-sm" id="sts-clear-btn">Clear</button>
    <button class="sts-btn" id="sts-test-btn" style="background:#6366f1;color:#fff;font-size:11px;padding:6px 12px;" title="Test one prompt locally without uploading results">TEST</button>
  </div>
    </div>`;

    document.body.appendChild(root);
    syncCollapsedUi();

    // Event handlers — draggable pill
    (() => {
      const pill = $id("sts-pill");
      let dragging = false, hasMoved = false, ox, oy;
      pill.addEventListener("mousedown", (e) => {
        dragging = true; hasMoved = false;
        ox = e.clientX - pill.getBoundingClientRect().left;
        oy = e.clientY - pill.getBoundingClientRect().top;
        e.preventDefault();
      });
      document.addEventListener("mousemove", (e) => {
        if (!dragging) return;
        hasMoved = true;
        pill.style.left = (e.clientX - ox) + "px";
        pill.style.top = (e.clientY - oy) + "px";
        pill.style.right = "auto";
        pill.style.bottom = "auto";
      });
      document.addEventListener("mouseup", () => {
        if (dragging && !hasMoved) {
          S.collapsed = false;
          syncCollapsedUi();
          render();
        }
        dragging = false;
      });
    })();

    $id("sts-collapse-btn").addEventListener("click", () => {
      S.collapsed = true;
      syncCollapsedUi();
      render();
    });

    $id("sts-settings-btn").addEventListener("click", () => {
      S.showSettings = !S.showSettings;
      $id("sts-settings").classList.toggle("open", S.showSettings);
      $id("sts-settings-btn").classList.toggle("active", S.showSettings);
      if (S.showSettings) $id("sts-show-test-toggle").checked = !!S.showTestButton;
    });

    $id("sts-url-input").value = S.studioUrl;
    $id("sts-url-save").addEventListener("click", () => {
      const val = $id("sts-url-input").value.trim();
      if (val) {
        S.studioUrl = val;
        localStorage.setItem("sts-url", val);
        localStorage.setItem("sts-url-manual", val);
      } else {
        // Clear manual override → re-enable auto-discovery
        localStorage.removeItem("sts-url-manual");
      }
      S.wsConnected = false;
      connectWS();
      render();
    });
    $id("sts-show-test-toggle").checked = !!S.showTestButton;
    $id("sts-show-test-toggle").addEventListener("change", () => {
      S.showTestButton = !!$id("sts-show-test-toggle").checked;
      localStorage.setItem("sts-grok-show-test", S.showTestButton ? "true" : "false");
      render();
    });

    $id("sts-head-autotype").addEventListener("click", () => {
      S.autoType = !S.autoType;
      localStorage.setItem("sts-auto-type", S.autoType ? "true" : "false");
      if (S.autoType) S.typing.autoPaused = false;
      renderAutoType();
    });

    // Tabs
    for (const tab of root.querySelectorAll(".sts-tab")) {
      tab.addEventListener("click", () => {
        root.querySelectorAll(".sts-tab").forEach(t => t.classList.remove("active"));
        tab.classList.add("active");
        S.activeTab = tab.dataset.tab;
        render();
      });
    }

    // Action buttons
    $id("sts-action-btn").addEventListener("click", () => {
      if (S.typing.active) stopTyping();
      else startTyping();
    });

    $id("sts-retry-btn").addEventListener("click", () => {
      for (const q of S.typing.queue) {
        if (isTypingSelected(q) && (q.status === "error" || q.status === "failed") && (q.errorCount || 0) < 3) {
          q.status = "queued"; q.errorCount = 0;
        }
      }
      render();
      startTyping();
    });

    $id("sts-clear-btn").addEventListener("click", () => {
      let clearedProjects = getUniqueProjectIds(S.typing.queue);
      if (!clearedProjects.length && S.projectId) clearedProjects = [S.projectId];
      updateHistoryForProjects(clearedProjects, {
        status: S.typing.active ? "stopped" : "cleared",
        endedAt: Date.now(),
        activate: false,
      });
      if (S.typing.active) {
        S.typing.stopRequested = true;
        S.typing.active = false;
      }
      S.typing.queue = [];
      S.scenes = {};
      S.sentScenes = {};
      S.projectId = null;
      S.typing.typedCount = 0;
      S.typing.batchCount = 0;
      S.typing.currentIndex = -1;
      S.jobComplete = false;
      // Remove all badges from DOM
      document.querySelectorAll(".sts-scene-badge").forEach(b => b.remove());
      clearStoredState(); // wipe persistence too
      console.log("[STS] Cleared all jobs");
      render();
    });

    $id("sts-test-btn").addEventListener("click", () => {
      runTestPrompt();
    });

    // Checkbox delegation
    $id("sts-list").addEventListener("change", (e) => {
      const cb = e.target.closest('[data-role="typing-checkbox"]');
      if (!cb) return;
      const idx = parseInt(cb.dataset.idx, 10);
      if (S.typing.queue[idx]) {
        S.typing.queue[idx].selected = cb.checked;
        render();
      }
    });
    $id("sts-list").addEventListener("click", async (e) => {
      const copyBtn = e.target.closest('[data-role="copy-prompt"]');
      if (copyBtn) {
        e.preventDefault();
        e.stopPropagation();
        try {
          const encoded = copyBtn.getAttribute("data-copy-text") || "";
          const text = encoded ? decodeURIComponent(encoded) : "";
          await copyText(text);
          flashCopyButton(copyBtn);
        } catch (err) {
          console.warn("[STS] Copy prompt failed:", err);
          flashCopyButton(copyBtn, "Failed", "failed");
        }
        return;
      }
      const toggle = e.target.closest(".sts-history-toggle");
      if (!toggle) return;
      const entryId = toggle.getAttribute("data-entry-id");
      if (!entryId) return;
      S.history.expanded[entryId] = !isHistoryExpanded(entryId);
      render();
    });

    $id("sts-list").addEventListener("pointerover", (e) => {
      const thumb = e.target.closest(".sts-row-thumb");
      if (!thumb || thumb.tagName !== "IMG" || !thumb.src) return;
      showImagePreview(thumb.src, e);
    });
    $id("sts-list").addEventListener("pointermove", (e) => {
      const thumb = e.target.closest(".sts-row-thumb");
      if (!thumb || thumb.tagName !== "IMG" || !thumb.src) return;
      showImagePreview(thumb.src, e);
    });
    $id("sts-list").addEventListener("pointerout", (e) => {
      const thumb = e.target.closest(".sts-row-thumb");
      if (!thumb || thumb.tagName !== "IMG") return;
      const next = e.relatedTarget && e.relatedTarget.closest ? e.relatedTarget.closest(".sts-row-thumb") : null;
      if (next === thumb) return;
      hideImagePreview();
    });
  }

  // ── Init ───────────────────────────────────────────────

  injectUI();
  renderAutoType();
  window.__stsGrokState = S;

  // Restore persisted state, then start polling
  (async () => {
    await loadState();
    render(); // re-render with restored state
    await poll();
    async function adaptivePoll() {
      await poll();
      setTimeout(adaptivePoll, S.pollInterval);
    }
    setTimeout(adaptivePoll, S.pollInterval);
    setInterval(() => {
      const el = $id("sts-timer-val");
      if (el && S.lastPoll) el.textContent = Math.floor((Date.now() - S.lastPoll) / 1000) + "s ago";
    }, 1000);
  })();
}
