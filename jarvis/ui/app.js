/* Stage 2 UI state and safe text-only DOM rendering. */
(function () {
  "use strict";
  const $ = (selector) => document.querySelector(selector);
  const COLOR = window.JarvisGraph.typeColors;
  const graph = window.JarvisGraph.createGraph($("#graphCanvas"), {
    onSelect: selectNote, onPathStatus: setPathStatus, onHover: setHover
  });
  let indexData = null, selectedId = null, toastTimer = 0;
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const hasSpeechOutput = "speechSynthesis" in window && "SpeechSynthesisUtterance" in window;
  let recognition = null, isListening = false, speechEnabled = hasSpeechOutput, activeAudio = null;
  const sessionId = sessionStorage.getItem("jarvis.sessionId") || crypto.randomUUID();
  sessionStorage.setItem("jarvis.sessionId", sessionId);

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function showToast(message) {
    const toast = $("#toast"); toast.textContent = message; toast.classList.add("visible");
    clearTimeout(toastTimer); toastTimer = setTimeout(() => toast.classList.remove("visible"), 2500);
  }
  function setReactor(state, caption) {
    $("#reactorState").textContent = state;
    $("#reactorCaption").textContent = caption;
  }
  function updateVoiceControls() {
    const mic = $("#voiceButton"), mute = $("#voiceMute"), sectionMic = $("#voiceSectionMic");
    const recognitionReady = Boolean(SpeechRecognition);
    mic.disabled = !recognitionReady;
    mic.classList.toggle("voice-active", isListening);
    mic.setAttribute("aria-pressed", String(isListening));
    mic.title = recognitionReady ? (isListening ? "Stop microphone" : "Start microphone") : "Speech recognition is not supported by this browser";
    mic.setAttribute("aria-label", mic.title);
    mic.querySelector("b").textContent = isListening ? "Stop" : "Mic";
    sectionMic.disabled = !recognitionReady;
    sectionMic.textContent = isListening ? "Stop microphone" : "Start microphone";
    mute.disabled = !hasSpeechOutput;
    mute.classList.toggle("voice-muted", !speechEnabled);
    mute.setAttribute("aria-pressed", String(!speechEnabled));
    mute.title = speechEnabled ? "Mute JARVIS voice" : "Unmute JARVIS voice";
    mute.setAttribute("aria-label", mute.title);
    mute.querySelector("b").textContent = speechEnabled ? "Voice" : "Muted";
  }
  function stopVoice() {
    if (activeAudio) { activeAudio.pause(); activeAudio = null; }
    if (hasSpeechOutput) window.speechSynthesis.cancel();
  }
  function speakBrowser(text) {
    if (!speechEnabled || !hasSpeechOutput || !text) return;
    const reply = String(text).replace(/\s+/g, " ").trim();
    if (!reply) return;
    stopVoice();
    window.speechSynthesis.resume();
    const utterance = new SpeechSynthesisUtterance(reply);
    utterance.rate = 1.03;
    utterance.pitch = 0.95;
    utterance.onstart = () => setReactor("Speaking", "JARVIS is reading the local response aloud.");
    utterance.onend = () => { if (!isListening) setReactor("Idle", "Text tools and browser voice are ready locally."); };
    utterance.onerror = () => {
      setReactor("Idle", "Browser voice could not play the response.");
      showToast("Your browser could not play JARVIS's reply. Check the Voice button and system audio.");
    };
    window.speechSynthesis.speak(utterance);
  }
  async function playReply(result) {
    if (!speechEnabled || !result || !result.spoken) return;
    const voice = result.voice;
    if (!voice || !voice.requestId) {
      speakBrowser(result.spoken);
      return;
    }
    try {
      setReactor("Speaking", "Requesting the configured ElevenLabs voice.");
      const response = await fetch("/api/voice/speak", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ requestId: voice.requestId })
      });
      if (!response.ok) throw new Error("ElevenLabs voice request failed");
      stopVoice();
      const audioUrl = URL.createObjectURL(await response.blob());
      const audio = new Audio(audioUrl);
      activeAudio = audio;
      audio.onplay = () => setReactor("Speaking", "JARVIS is replying with the configured ElevenLabs voice.");
      audio.onended = () => { URL.revokeObjectURL(audioUrl); if (activeAudio === audio) activeAudio = null; setReactor("Idle", "Text tools and voice are ready locally."); };
      audio.onerror = () => { URL.revokeObjectURL(audioUrl); if (activeAudio === audio) activeAudio = null; speakBrowser(result.spoken); };
      await audio.play();
    } catch (_) {
      speakBrowser(result.spoken);
    }
  }
  function setupVoice() {
    if (SpeechRecognition) {
      recognition = new SpeechRecognition();
      recognition.lang = "en-US";
      recognition.continuous = false;
      recognition.interimResults = false;
      recognition.maxAlternatives = 1;
      recognition.onstart = () => { isListening = true; updateVoiceControls(); setReactor("Listening", "Speak one request, then JARVIS will respond."); };
      recognition.onresult = (event) => {
        const transcript = event.results[0][0].transcript.trim();
        if (transcript) sendMessage(transcript);
      };
      recognition.onerror = (event) => {
        if (event.error !== "aborted") showToast("Microphone: " + event.error + ". Check browser microphone permission.");
      };
      recognition.onend = () => { isListening = false; updateVoiceControls(); };
    }
    updateVoiceControls();
  }
  function toggleMicrophone() {
    if (!recognition) { showToast("Speech recognition is not supported in this browser. Type a request instead."); return; }
    if (isListening) { recognition.stop(); return; }
    stopVoice();
    try { recognition.start(); } catch (_) { showToast("Microphone is already starting. Please try again in a moment."); }
  }
  function toggleVoice() {
    if (!hasSpeechOutput) { showToast("Browser speech output is not supported here."); return; }
    speechEnabled = !speechEnabled;
    if (!speechEnabled) stopVoice();
    updateVoiceControls();
    showToast(speechEnabled ? "JARVIS voice is on." : "JARVIS voice is muted.");
  }
  function renderVoice(status) {
    $("#voiceProvider").textContent = (status.provider || "Browser voice").toUpperCase();
    $("#voiceDetail").textContent = status.detail || "Voice status unavailable.";
  }
  async function refreshVoiceStatus() {
    const response = await fetch("/api/voice/status", { cache: "no-store" });
    if (!response.ok) throw new Error("Could not refresh voice status.");
    renderVoice(await response.json());
  }
  function safeType(type) { return /^[a-z0-9_-]{1,40}$/i.test(type) ? "type-" + type.toLowerCase() : "type-other"; }
  function fmtTime(iso) {
    try { return new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit", hour12: true }).format(new Date(iso)); }
    catch (_) { return "—"; }
  }
  function updateClock() {
    $("#clock").textContent = new Intl.DateTimeFormat("en-US", {
      timeZone: "America/New_York", hour: "numeric", minute: "2-digit", second: "2-digit", hour12: true
    }).format(new Date());
  }
  function setPathStatus(text) { $("#pathStatus").textContent = text; $("#pathStatus").classList.add("active"); }
  function setHover(note) {
    $("#graphCanvas").setAttribute("aria-label", note
      ? "Hovered: " + note.title + ". Click to inspect; shift-click to trace a path."
      : "Interactive graph of indexed notes. Use Browse notes for keyboard access; shift-click two notes to find a path.");
  }
  function getNote(id) { return indexData && indexData.notes.find((note) => note.id === id); }

  function selectNote(id) {
    const note = getNote(id); if (!note) return;
    selectedId = id; graph.setSelection(id);
    const box = $("#inspectorContent"); box.replaceChildren();
    const header = el("div", "note-detail-heading");
    const type = el("span", "type-pill", note.type);
    type.className += " " + safeType(note.type);
    header.append(type, el("h2", "note-title", note.title));
    const source = el("div", "source-path");
    source.append(el("span", "meta-label", "SOURCE"), el("span", "mono", note.source + " / " + note.path));
    const excerpt = el("blockquote", "note-excerpt", note.excerpt || "No text excerpt was available for this file.");
    const citation = el("div", "citation-line", "Line " + note.line + " · " + note.path);
    const connections = indexData.edges.filter((edge) => edge.source === id || edge.target === id)
      .map((edge) => getNote(edge.source === id ? edge.target : edge.source)).filter(Boolean);
    const section = el("section", "connection-section"); section.append(el("div", "section-title", "CONNECTED NOTES"));
    if (!connections.length) section.append(el("p", "muted", "No resolved note links."));
    else {
      const list = el("div", "connection-list");
      for (const item of connections) {
        const button = el("button", "connection-button"); button.type = "button";
        const dot = el("i", "connection-dot " + safeType(item.type));
        button.append(dot, el("span", "connection-name", item.title), el("span", "connection-arrow", "↗"));
        button.addEventListener("click", () => graph.selectById(item.id)); list.append(button);
      }
      section.append(list);
    }
    box.append(header, source, excerpt, citation, section);
  }
  function renderHubs() {
    const list = $("#hubList"); list.replaceChildren();
    if (!indexData.hubs.length) { list.append(el("li", "muted", "No indexed notes yet.")); return; }
    for (const hub of indexData.hubs) {
      const li = el("li", "hub-item"), button = el("button", "hub-button"); button.type = "button";
      const rank = String(list.children.length + 1).padStart(2, "0");
      button.append(el("span", "hub-rank", rank), el("span", "hub-name", hub.title), el("span", "hub-degree", String(hub.degree)));
      button.addEventListener("click", () => graph.selectById(hub.id)); li.append(button); list.append(li);
    }
  }
  function updateVisibleCount() { $("#visibleCount").textContent = graph.visibleCount + " / " + indexData.notes.length; }
  function renderFilters() {
    const list = $("#filterList"); list.replaceChildren();
    const types = Object.entries(indexData.countsByType).sort(([a], [b]) => a.localeCompare(b));
    if (!types.length) { list.append(el("p", "muted", "No indexed source types.")); return; }
    const enabled = new Set(types.map(([type]) => type));
    for (const [type, count] of types) {
      const label = el("label", "filter-row"), checkbox = document.createElement("input");
      checkbox.type = "checkbox"; checkbox.checked = true; checkbox.value = type;
      checkbox.setAttribute("aria-label", "Show " + type + " nodes");
      const mark = el("span", "filter-mark " + safeType(type));
      checkbox.addEventListener("change", () => {
        if (checkbox.checked) enabled.add(type); else enabled.delete(type);
        graph.setVisibleTypes(enabled); updateVisibleCount();
      });
      label.append(checkbox, mark, el("span", "filter-name", type), el("span", "filter-count", String(count)));
      list.append(label);
    }
    updateVisibleCount();
  }
  function renderLegend() {
    const legend = $("#legend"); legend.replaceChildren();
    for (const type of Object.keys(indexData.countsByType).sort()) {
      const item = el("span", "legend-item"), dot = el("i", "legend-dot " + safeType(type));
      item.append(dot, el("span", "", type)); legend.append(item);
    }
  }
  function renderDirectory() {
    const directory = $("#noteDirectory"); directory.replaceChildren();
    for (const note of indexData.notes) {
      const button = el("button", "directory-item"); button.type = "button";
      const dot = el("i", "legend-dot " + safeType(note.type));
      button.append(dot, el("span", "directory-title", note.title), el("span", "directory-type", note.type));
      button.addEventListener("click", () => {
        graph.selectById(note.id); $(".browse-menu").open = false;
      });
      directory.append(button);
    }
  }
  function renderSourceStatus() {
    const isDemo = indexData.mode === "DEMO", badge = $("#modeBadge");
    badge.replaceChildren(el("i", "status-dot"), document.createTextNode(isDemo ? "DEMO" : "APPROVED SOURCES"));
    badge.className = "badge " + (isDemo ? "badge-demo" : "badge-live");
    $("#sourceStatus").textContent = indexData.notes.length + " NOTES · " + indexData.edges.length + " LINKS";
    $("#sourceDescription").textContent = isDemo
      ? "Fictional fixtures only. No personal folders, Canvas, or Gmail were read."
      : "Read-only files from explicitly approved local roots.";
    renderGmail(indexData.gmail);
    renderVoice(indexData.voice || { provider: "Browser voice", detail: "Voice status unavailable." });
    $("#refreshedAt").textContent = "Updated " + fmtTime(indexData.refreshed) + " ET";
    $("#linkCount").textContent = indexData.edges.length + " resolved links";
    $("#nodeCount").textContent = indexData.notes.length + " nodes";
    $("#modelBadge").textContent = indexData.model.label.toUpperCase();
    $("#reactorCaption").textContent = "Text tools active locally. Voice remains disabled until approved.";
    const warnings = [];
    if (indexData.unresolved.length) warnings.push(indexData.unresolved.length + " unresolved links");
    if (indexData.ambiguous.length) warnings.push(indexData.ambiguous.length + " ambiguous links");
    if (indexData.skipped.length) warnings.push(indexData.skipped.length + " skipped files");
    if (indexData.failures.length) warnings.push(indexData.failures.length + " read/extraction failures");
    if (!indexData.pdfExtractorAvailable) warnings.push("PDF extractor unavailable");
    const box = $("#sourceWarnings"); box.hidden = !warnings.length; box.replaceChildren();
    for (const warning of warnings) box.append(el("div", "warning-line", warning));
    $("#sourceLamp").classList.toggle("warn", warnings.length > 0);
  }
  function renderGmail(status) {
    $("#gmailAccount").textContent = status.account || "Not configured";
    $("#gmailConnection").textContent = status.connected ? "CONNECTED" : (status.configured ? "AUTH NEEDED" : "DISCONNECTED");
    $("#gmailConnection").classList.toggle("connected", status.connected);
    $("#gmailDetail").textContent = status.detail;
    const button = $("#gmailConnect");
    button.disabled = !status.configured || status.connected;
    button.textContent = status.connected ? "Gmail connected" : (status.configured ? "Authorize read-only" : "OAuth client file needed");
  }
  async function refreshGmailStatus() {
    const response = await fetch("/api/gmail/status", { cache: "no-store" });
    if (!response.ok) throw new Error("Could not refresh Gmail status.");
    renderGmail(await response.json());
  }
  async function connectGmail() {
    const popup = window.open("about:blank", "_blank");
    if (!popup) { showToast("Allow a popup for Google authorization, then try again."); return; }
    try {
      const response = await fetch("/api/gmail/connect", { method: "POST" });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Could not start Google authorization.");
      popup.location.href = result.url;
      let attempts = 0;
      const timer = setInterval(async () => {
        attempts++;
        try {
          await refreshGmailStatus();
          if ($("#gmailConnection").textContent === "CONNECTED" || attempts >= 30) clearInterval(timer);
        } catch (_) { if (attempts >= 30) clearInterval(timer); }
      }, 4000);
    } catch (error) {
      popup.close(); showToast(error.message);
    }
  }
  async function loadIndex() {
    try {
      const response = await fetch("/api/index", { headers: { Accept: "application/json" }, cache: "no-store" });
      if (!response.ok) throw new Error("Index request failed (" + response.status + ")");
      indexData = await response.json();
      graph.setData(indexData.notes, indexData.edges);
      renderHubs(); renderFilters(); renderLegend(); renderDirectory(); renderSourceStatus();
      refreshVoiceStatus().catch(() => {});
      updateClock(); setInterval(updateClock, 1000);
      const top = indexData.notes.find((note) => note.degree > 0); if (top) selectNote(top.id);
    } catch (error) {
      $("#sourceStatus").textContent = "INDEX UNAVAILABLE";
      $("#sourceDescription").textContent = "Could not load the local index. Restart JARVIS and refresh this page.";
      $("#reactorState").textContent = "Error"; $("#reactorCaption").textContent = error.message;
      $("#sourceLamp").classList.add("warn"); showToast("Index unavailable. Check the local JARVIS server.");
    }
  }
  function renderCard(card) {
    const box = el("section", "structured-card");
    box.append(el("strong", "card-title", card.title));
    if (card.detail) box.append(el("p", "card-detail", card.detail));
    if (card.items && card.items.length) {
      const list = el("ul", "card-items");
      for (const item of card.items) {
        const row = el("li", "card-item");
        row.append(el("strong", "card-item-title", item.title || item.path || "Source"));
        const meta = [item.from ? "From " + item.from : item.type, item.due ? "Due " + item.due : "",
          item.deadline ? "Possible deadline " + item.deadline : "", item.estimate || "",
          item.action || "", item.matchedSources && item.matchedSources.length ? "Related files: " + item.matchedSources.join(", ") : ""].filter(Boolean).join(" · ");
        if (meta) row.append(el("span", "card-item-meta", meta));
        if (item.excerpt) row.append(el("p", "card-excerpt", item.excerpt));
        if (item.path) row.append(el("span", "card-citation", item.path + (item.line ? " · line " + item.line : "")));
        else if (item.from) row.append(el("span", "card-citation", "Gmail · inbox (read-only)"));
        list.append(row);
      }
      box.append(list);
    }
    return box;
  }
  function appendMessage(role, text, card) {
    const feed = $("#chatMessages"), item = el("article", "chat-message " + (role === "user" ? "user-message" : "assistant-message"));
    item.append(el("span", "message-author", role === "user" ? "SETH" : "JARVIS · LOCAL"));
    item.append(el("p", "message-text", text));
    if (card) item.append(renderCard(card));
    feed.append(item); feed.scrollTop = feed.scrollHeight;
  }
  async function sendMessage(text) {
    const value = (text || $("#askInput").value).trim();
    if (!value) return;
    appendMessage("user", value); $("#askInput").value = "";
    $("#sendMessage").disabled = true; $("#chatTyping").hidden = false;
    $("#reactorState").textContent = "Thinking"; $("#reactorCaption").textContent = "Routing the request through local tools.";
    try {
      const response = await fetch("/api/chat", {
        method: "POST", headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ sessionId: sessionId, text: value })
      });
      if (!response.ok) throw new Error("Chat request failed (" + response.status + ")");
      const result = await response.json(); appendMessage("assistant", result.spoken, result.card); playReply(result);
    } catch (error) {
      appendMessage("assistant", "I couldn’t reach the local assistant service. Your message wasn’t sent to an external provider.", {
        title: "Local service unavailable", detail: error.message, kind: "status", items: []
      });
    } finally {
      $("#sendMessage").disabled = false; $("#chatTyping").hidden = true;
      if (!speechEnabled || !hasSpeechOutput) setReactor("Idle", "Text tools are active locally. Browser voice is muted or unavailable.");
      $("#askInput").focus();
    }
  }
  $("#resetView").addEventListener("click", () => graph.reset());
  $("#graphCanvas").addEventListener("dblclick", () => graph.reset());
  $("#sendMessage").addEventListener("click", () => sendMessage());
  $("#askInput").addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); sendMessage(); } });
  $("#briefButton").addEventListener("click", () => sendMessage("brief me"));
  $("#planButton").addEventListener("click", () => sendMessage("plan my day"));
  $("#gmailConnect").addEventListener("click", connectGmail);
  $("#voiceButton").addEventListener("click", toggleMicrophone);
  $("#voiceMute").addEventListener("click", toggleVoice);
  $("#voiceSectionMic").addEventListener("click", toggleMicrophone);
  $("#voiceSectionTest").addEventListener("click", () => sendMessage("can you hear me"));
  setupVoice();
  loadIndex();
})();
