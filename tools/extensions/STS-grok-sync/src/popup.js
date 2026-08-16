document.addEventListener('DOMContentLoaded', function() {
  var statusBadge = document.getElementById('statusBadge');
  var statusLabel = document.getElementById('statusLabel');
  var statusText = document.getElementById('statusText');

  function setStatus(connected, detail) {
    if (connected) {
      statusBadge.className = 'status-badge online';
      statusLabel.textContent = 'Connected';
      statusText.textContent = detail || 'WebSocket connected to STS backend';
    } else {
      statusBadge.className = 'status-badge offline';
      statusLabel.textContent = 'Reconnecting';
      statusText.textContent = detail || 'Scanning for STS backend...';
    }
  }

  function checkStatus() {
    chrome.runtime.sendMessage({ action: 'STS_WS_GET_STATUS' }, function(bgResp) {
      if (chrome.runtime.lastError || !bgResp) {
        setStatus(false, 'Background worker not responding');
        return;
      }

      chrome.tabs.query({ active: true, currentWindow: true }, function(tabs) {
        var tab = tabs && tabs[0];
        if (!tab || !tab.url || tab.url.indexOf('grok.com') === -1) {
          setStatus(bgResp.connected, bgResp.connected ? 'Open grok.com to use' : null);
          return;
        }

        chrome.tabs.sendMessage(tab.id, { action: 'STS_STATUS' }, function(response) {
          if (chrome.runtime.lastError || !response) {
            setStatus(bgResp.connected);
            return;
          }
          var detail = '';
          if (bgResp.connected && response.projectId) {
            detail = 'Project: ' + response.projectId;
          }
          setStatus(bgResp.connected, detail || undefined);
        });
      });
    });
  }

  checkStatus();
  setInterval(checkStatus, 2000);
});
