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

  const weatherUrl = new URL('https://api.open-meteo.com/v1/forecast');
  weatherUrl.search = new URLSearchParams({
    latitude: '40.7357',
    longitude: '-74.1724',
    current: 'temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m',
    temperature_unit: 'fahrenheit',
    wind_speed_unit: 'mph',
    timezone: eastern.timeZone,
  });
  const weatherConditions = {
    0: ['Clear', '☀'], 1: ['Mostly clear', '☀'], 2: ['Partly cloudy', '⛅'], 3: ['Overcast', '☁'],
    45: ['Fog', '≋'], 48: ['Fog', '≋'],
    51: ['Drizzle', '🌧'], 53: ['Drizzle', '🌧'], 55: ['Drizzle', '🌧'],
    56: ['Freezing drizzle', '🌧'], 57: ['Freezing drizzle', '🌧'],
    61: ['Rain', '🌧'], 63: ['Rain', '🌧'], 65: ['Heavy rain', '🌧'],
    66: ['Freezing rain', '🌧'], 67: ['Freezing rain', '🌧'],
    71: ['Snow', '❄'], 73: ['Snow', '❄'], 75: ['Heavy snow', '❄'], 77: ['Snow grains', '❄'],
    80: ['Rain showers', '🌧'], 81: ['Rain showers', '🌧'], 82: ['Heavy showers', '🌧'],
    85: ['Snow showers', '❄'], 86: ['Snow showers', '❄'],
    95: ['Thunderstorms', 'ϟ'], 96: ['Thunderstorms with hail', 'ϟ'], 99: ['Thunderstorms with hail', 'ϟ'],
  };

  function weatherReading(value, unit) {
    return Number.isFinite(value) ? Math.round(value) + unit : '—';
  }

  async function refreshWeather() {
    try {
      const response = await fetch(weatherUrl, {
        credentials: 'omit', referrerPolicy: 'no-referrer', signal: AbortSignal.timeout(10000),
      });
      if (!response.ok) throw Error('Weather request failed.');
      const {current} = await response.json();
      if (!Number.isFinite(current?.temperature_2m)) throw Error('Missing current temperature.');
      const [condition, icon] = weatherConditions[current.weather_code] ?? ['Current conditions', '☁'];
      byId('weather-temperature').textContent = weatherReading(current.temperature_2m, '°F');
      byId('weather-condition').textContent = condition;
      byId('weather-icon').textContent = icon;
      byId('weather-feels-like').textContent = weatherReading(current.apparent_temperature, '°F');
      byId('weather-humidity').textContent = weatherReading(current.relative_humidity_2m, '%');
      byId('weather-wind').textContent = weatherReading(current.wind_speed_10m, ' mph');
      byId('weather-details').hidden = false;
    } catch {
      byId('weather-temperature').textContent = '—';
      byId('weather-condition').textContent = 'Weather temporarily unavailable';
      byId('weather-icon').textContent = '☁';
      byId('weather-details').hidden = true;
    }
  }

  void refreshWeather();
  setInterval(refreshWeather, 15 * 60 * 1000);

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
