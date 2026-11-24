(() => {
  const byId = id => document.getElementById(id);
  const toClockPart = value => String(value).padStart(2, '0');
  const eastern = {timeZone: 'America/New_York'};
  const clockTime = new Intl.DateTimeFormat(undefined, {
    ...eastern, hour: 'numeric', minute: '2-digit', second: '2-digit', timeZoneName: 'short',
  });
  const clockDate = new Intl.DateTimeFormat(undefined, {...eastern, month: 'short', day: 'numeric', year: 'numeric'});
  const clock = byId('clock');
  const opened = performance.now();

  function tick() {
    const now = new Date();
    clock.dateTime = now.toISOString();
    byId('clock-time').textContent = clockTime.format(now);
    byId('clock-date').textContent = clockDate.format(now);
    const seconds = Math.floor((performance.now() - opened) / 1000);
    byId('uptime').textContent = [
      Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60,
    ].map(toClockPart).join(':');
  }

  tick();
  setInterval(tick, 1000);

  const dashboard = document.querySelector('[data-dashboard]');
  const input = byId(dashboard.dataset.input);
  byId('keyboard-shortcut').addEventListener('click', () => input.focus());

  const transcript = byId(dashboard.dataset.thread);
  const scrollbox = transcript.closest('.transcript');
  const exportButton = byId('export-conversation');
  const chatTurns = () => [...transcript.querySelectorAll('article.user, article.assistant')];

  new MutationObserver(() => {
    const count = chatTurns().length;
    exportButton.disabled = count === 0;
    byId('message-count').textContent = count;
    scrollbox.scrollTop = scrollbox.scrollHeight;
  }).observe(transcript, {childList: true, subtree: true});

  exportButton.addEventListener('click', () => {
    const lines = chatTurns().map(turn => turn.innerText.trim());
    const url = URL.createObjectURL(new Blob([lines.join('\n\n') + '\n'], {type: 'text/plain;charset=utf-8'}));
    const link = document.createElement('a');
    link.href = url;
    link.download = 'jarvis-conversation.txt';
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });

  const toggle = byId('camera-toggle');
  const shortcut = byId('camera-shortcut');
  const video = byId('camera-video');
  const placeholder = byId('camera-placeholder');
  const cameraStatus = byId('camera-status');
  let camera;
  let cameraRequest = 0;

  function cameraOff() {
    cameraRequest++;
    camera?.getTracks().forEach(track => track.stop());
    camera = undefined;
    video.srcObject = null;
    video.hidden = true;
    placeholder.hidden = false;
    toggle.setAttribute('aria-pressed', 'false');
    shortcut.setAttribute('aria-pressed', 'false');
    toggle.disabled = shortcut.disabled = false;
    cameraStatus.textContent = 'Camera off';
  }

  async function toggleCamera() {
    if (camera) {
      cameraOff();
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      cameraStatus.textContent = 'Camera unavailable in this browser.';
      return;
    }
    const request = ++cameraRequest;
    toggle.disabled = shortcut.disabled = true;
    cameraStatus.textContent = 'Waiting for camera permission…';
    try {
      const stream = await navigator.mediaDevices.getUserMedia({video: true, audio: false});
      if (request !== cameraRequest) {
        stream.getTracks().forEach(track => track.stop());
        return;
      }
      camera = stream;
      stream.getVideoTracks().forEach(track => track.addEventListener('ended', cameraOff, {once: true}));
      video.srcObject = stream;
      video.hidden = false;
      await video.play();
      if (request !== cameraRequest) return;
      placeholder.hidden = true;
      toggle.setAttribute('aria-pressed', 'true');
      shortcut.setAttribute('aria-pressed', 'true');
    } catch {
      if (request !== cameraRequest) return;
      cameraOff();
      cameraStatus.textContent = 'Camera unavailable. Check browser permission and device access.';
    } finally {
      if (request === cameraRequest) toggle.disabled = shortcut.disabled = false;
    }
  }

  toggle.addEventListener('click', toggleCamera);
  shortcut.addEventListener('click', toggleCamera);
  shortcut.setAttribute('aria-pressed', 'false');
  window.addEventListener('pagehide', cameraOff);
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) cameraOff();
  });
  new MutationObserver(() => {
    if (dashboard.hidden) cameraOff();
  }).observe(dashboard, {attributes: true, attributeFilter: ['hidden']});
  if (document.body.dataset.mode === 'embedded') {
    new MutationObserver(() => {
      if (!document.body.hasAttribute('data-paired')) cameraOff();
    }).observe(document.body, {attributes: true, attributeFilter: ['data-paired']});
  }
})();
