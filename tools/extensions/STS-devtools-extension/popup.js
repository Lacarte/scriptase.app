/**
 * STS DevTools — Popup Controller
 */

const $  = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);
const results = $('#results');
const promptSection = $('#prompt-section');
const promptText = $('#prompt-text');
const copyPromptBtn = $('#btn-copy-prompt');
let currentPrompt = '';
let promptGenerating = false;

// ── Messaging ────────────────────────────────────────────────────────────

function send(action, payload = {}) {
  return chrome.runtime.sendMessage({ channel: 'sts-devtools', action, payload });
}

function sendContent(action, payload = {}) {
  return new Promise((resolve) => {
    chrome.tabs.query({ active: true, currentWindow: true }, ([tab]) => {
      if (!tab) { resolve({ error: 'No tab' }); return; }
      chrome.tabs.sendMessage(tab.id, { channel: 'sts-devtools-content', action, payload }, resolve);
    });
  });
}

// ── Results Display ──────────────────────────────────────────────────────

function showResults(content, cls = '') {
  results.className = 'visible';
  if (typeof content === 'string') {
    results.innerHTML = `<span class="${cls}">${escHtml(content)}</span>`;
  } else {
    results.innerHTML = `<pre class="result-info">${escHtml(JSON.stringify(content, null, 2))}</pre>`;
  }
}

function showTestResults(data) {
  results.className = 'visible';
  let html = `<b>${data.module}</b> — ${data.passed} pass, ${data.failed} fail\n\n`;
  for (const t of data.tests) {
    const icon = t.status === 'pass' ? '✓' : '✗';
    const cls = t.status === 'pass' ? 'result-pass' : 'result-fail';
    html += `<span class="${cls}">${icon} ${escHtml(t.name)}</span>`;
    if (t.error) html += `  <span class="result-fail">${escHtml(t.error)}</span>`;
    html += '\n';
  }
  results.innerHTML = html;
}

function escHtml(s) {
  const d = document.createElement('div');
  d.textContent = String(s);
  return d.innerHTML;
}

async function copyText(text) {
  const value = String(text || '');
  if (!value.trim()) throw new Error('No prompt to copy');

  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value);
      return;
    } catch {}
  }

  const input = document.createElement('textarea');
  input.value = value;
  input.setAttribute('readonly', '');
  input.style.position = 'fixed';
  input.style.left = '-9999px';
  input.style.opacity = '0';
  document.body.appendChild(input);
  input.select();
  input.setSelectionRange(0, input.value.length);
  const copied = document.execCommand('copy');
  input.remove();
  if (!copied) throw new Error('Copy failed');
}

function setPrompt(prompt) {
  currentPrompt = typeof prompt === 'string' && prompt.trim() ? prompt : '';
  if (!promptText || !copyPromptBtn) return;

  promptText.textContent = currentPrompt || 'No prompt detected on this page.';
  promptText.classList.toggle('empty', !currentPrompt);
  copyPromptBtn.disabled = !currentPrompt;
  copyPromptBtn.textContent = 'Copy';
}

function setPromptGenerating(isGenerating) {
  promptGenerating = !!isGenerating && !!currentPrompt;
  promptSection?.classList.toggle('active-current', promptGenerating);
  if (!promptGenerating) return;

  document.scrollingElement?.scrollTo({ top: 0, behavior: 'auto' });
  promptSection?.scrollIntoView({ block: 'start', behavior: 'auto' });
  promptText?.scrollTo({ top: 0, behavior: 'auto' });
}

function flashCopyButton(button, label = 'Copied') {
  if (!button) return;
  if (button._copyTimer) clearTimeout(button._copyTimer);
  button.textContent = label;
  button._copyTimer = setTimeout(() => {
    button.textContent = 'Copy';
  }, 1200);
}

// ── Status Check ─────────────────────────────────────────────────────────

async function refreshStatus() {
  try {
    const s = await send('get_status');
    $('#dot-sts').className = 'dot ' + (s.sts_reachable ? 'ok' : 'err');
    $('#dot-awa').className = 'dot ' + (s.awa_connected ? 'ok' : 'warn');
  } catch {
    $('#dot-sts').className = 'dot err';
    $('#dot-awa').className = 'dot err';
  }

  // Page state from content script
  try {
    const state = await sendContent('get_page_state');
    if (state && !state.error) {
      const route = state.route || '/';
      $('#current-route').textContent = route;
      const parts = [];
      if (state.story_text_length) parts.push(`${state.story_text_length} chars`);
      if (state.errors?.length) parts.push(`${state.errors.length} errors`);
      if (state.log_entries?.length) parts.push(`${state.log_entries.length} logs`);
      $('#page-meta').textContent = parts.join(' | ') || '';
      setPrompt(state.story_text || '');
      setPromptGenerating(state.is_generating);
    } else {
      $('#current-route').textContent = 'Not on STS';
      $('#page-meta').textContent = '';
      setPrompt('');
      setPromptGenerating(false);
    }
  } catch {
    $('#current-route').textContent = '-';
    setPrompt('');
    setPromptGenerating(false);
  }
}

// ── Navigation ───────────────────────────────────────────────────────────

$$('.nav-btn').forEach(btn => {
  btn.addEventListener('click', async () => {
    const page = btn.dataset.page;
    await send('navigate', { page });
    // Close popup after navigation
    setTimeout(() => window.close(), 200);
  });
});

// ── Module Tests ─────────────────────────────────────────────────────────

$$('.test-btn').forEach(btn => {
  btn.addEventListener('click', async () => {
    const mod = btn.dataset.test;
    btn.className = 'test-btn running';
    btn.textContent = '...';
    try {
      const r = await send('test_module', { module: mod });
      btn.className = 'test-btn ' + (r.failed === 0 ? 'pass' : 'fail');
      btn.textContent = mod.charAt(0).toUpperCase() + mod.slice(1);
      showTestResults(r);
    } catch (e) {
      btn.className = 'test-btn fail';
      btn.textContent = mod.charAt(0).toUpperCase() + mod.slice(1);
      showResults(e.message, 'result-fail');
    }
  });
});

// ── Actions ──────────────────────────────────────────────────────────────

$('#btn-screenshot').addEventListener('click', async () => {
  const r = await send('screenshot', { save: true });
  showResults(r.error ? r.error : `Saved: ${r.filename}`, r.error ? 'result-fail' : 'result-pass');
});

$('#btn-page-state').addEventListener('click', async () => {
  const state = await sendContent('get_page_state');
  if (state && !state.error) {
    setPrompt(state.story_text || '');
    setPromptGenerating(state.is_generating);
  }
  showResults(state);
});

copyPromptBtn?.addEventListener('click', async () => {
  try {
    await copyText(currentPrompt);
    flashCopyButton(copyPromptBtn);
  } catch (e) {
    showResults(e.message, 'result-fail');
  }
});

$('#btn-interactive').addEventListener('click', async () => {
  const els = await sendContent('list_interactive');
  if (Array.isArray(els)) {
    let html = `<b>${els.length} interactive elements</b>\n\n`;
    for (const el of els.slice(0, 40)) {
      html += `<span class="result-info">[${el.tag}] ${escHtml(el.text || '(empty)')} ${el.id ? '#' + el.id : ''}</span>\n`;
    }
    if (els.length > 40) html += `\n... and ${els.length - 40} more`;
    results.className = 'visible';
    results.innerHTML = html;
  } else {
    showResults(els);
  }
});

$('#btn-projects').addEventListener('click', async () => {
  const r = await send('list_projects');
  if (Array.isArray(r)) {
    showResults(`${r.length} projects:\n\n` + r.slice(0, 20).map(p =>
      `${p.project_id || p.id || '?'}  ${p.title || p.name || ''}`
    ).join('\n'));
  } else {
    showResults(r);
  }
});

$('#btn-jobs').addEventListener('click', async () => {
  const r = await send('pipeline_jobs');
  if (Array.isArray(r)) {
    showResults(`${r.length} jobs:\n\n` + r.slice(0, 15).map(j =>
      `${j.job_id || j.id || '?'}  ${j.status || ''}  ${j.project_id || ''}`
    ).join('\n'));
  } else {
    showResults(r);
  }
});

$('#btn-test-all').addEventListener('click', async () => {
  const modules = ['health', 'tts', 'scenes', 'storyboard', 'pipeline', 'niches', 'music', 'story'];
  results.className = 'visible';
  results.innerHTML = '<span class="result-info">Running all tests...</span>';

  let totalPass = 0, totalFail = 0;
  let html = '';

  for (const mod of modules) {
    const btn = document.querySelector(`.test-btn[data-test="${mod}"]`);
    if (btn) { btn.className = 'test-btn running'; btn.textContent = '...'; }

    try {
      const r = await send('test_module', { module: mod });
      totalPass += r.passed;
      totalFail += r.failed;
      const icon = r.failed === 0 ? '✓' : '✗';
      const cls = r.failed === 0 ? 'result-pass' : 'result-fail';
      html += `<span class="${cls}">${icon} ${mod}: ${r.passed} pass${r.failed ? ', ' + r.failed + ' fail' : ''}</span>\n`;
      for (const t of r.tests) {
        const tCls = t.status === 'pass' ? 'result-pass' : 'result-fail';
        html += `  <span class="${tCls}">${t.status === 'pass' ? '✓' : '✗'} ${escHtml(t.name)}${t.error ? ' — ' + escHtml(t.error) : ''}</span>\n`;
      }
      html += '\n';

      if (btn) {
        btn.className = 'test-btn ' + (r.failed === 0 ? 'pass' : 'fail');
        btn.textContent = mod.charAt(0).toUpperCase() + mod.slice(1);
      }
    } catch (e) {
      totalFail++;
      html += `<span class="result-fail">✗ ${mod}: ${escHtml(e.message)}</span>\n\n`;
      if (btn) { btn.className = 'test-btn fail'; btn.textContent = mod.charAt(0).toUpperCase() + mod.slice(1); }
    }
  }

  results.innerHTML = `<b>Total: ${totalPass} pass, ${totalFail} fail</b>\n\n` + html;
});

// ── Init ─────────────────────────────────────────────────────────────────

refreshStatus();
setInterval(refreshStatus, 1500);
