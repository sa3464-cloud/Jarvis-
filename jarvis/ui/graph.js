/* Canvas graph renderer with local forces, pointer navigation, and shortest paths. */
(function () {
  "use strict";
  const TYPE_COLORS = {
    course: "#5ee7df", note: "#59b9e9", assignment: "#f4c46b", project: "#b59aff",
    career: "#81d49b", exam: "#ff8d87", calendar: "#83a9ff", message: "#f58cbd"
  };
  const REDUCED = window.matchMedia("(prefers-reduced-motion: reduce)");
  const GRID_SIZE = 112;
  const REPULSION_CUTOFF = 168;
  const REPULSION = 2200;
  const IDEAL_LINK = 118;
  const EDGE_STRENGTH = 0.0055;
  const DAMPING = 0.84;
  const TAU = Math.PI * 2;

  function createGraph(canvas, callbacks) {
    const ctx = canvas.getContext("2d", { alpha: true });
    const state = { nodes: [], edges: [], width: 0, height: 0, dpr: 1, zoom: 1, panX: 0, panY: 0,
      hover: null, selected: null, visibleTypes: null, path: null, pathStart: null,
      dragging: null, moved: false, pointer: null, running: false, lastTime: 0,
      pulseAt: performance.now() + 4200, pulseIndex: 0, settleFrames: 0 };

    function resize() {
      const rect = canvas.getBoundingClientRect();
      state.width = Math.max(1, rect.width); state.height = Math.max(1, rect.height);
      state.dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.round(state.width * state.dpr);
      canvas.height = Math.round(state.height * state.dpr);
      ctx.setTransform(state.dpr, 0, 0, state.dpr, 0, 0);
      const cx = state.width / 2, cy = state.height / 2;
      for (const n of state.nodes) if (n.x === null) {
        n.x = cx + n.seedX * Math.min(state.width, state.height);
        n.y = cy + n.seedY * Math.min(state.width, state.height);
      }
      draw();
    }
    function setData(notes, edges) {
      state.nodes = notes.map((note, i) => {
        const angle = i * 2.399963229728653;
        const radius = 14 + Math.sqrt(i + 1) * 30;
        return { ...note, x: null, y: null, vx: 0, vy: 0,
          seedX: Math.cos(angle) * radius / 200, seedY: Math.sin(angle) * radius / 200,
          r: 5.4 + Math.min(note.degree, 12) * 0.62, phase: i * 0.79,
          visible: !state.visibleTypes || state.visibleTypes.has(note.type) };
      });
      state.edges = edges.map((edge) => ({ ...edge }));
      resize(); state.running = true; state.settleFrames = 0; state.lastTime = performance.now();
      requestAnimationFrame(frame);
    }
    function setVisibleTypes(types) {
      state.visibleTypes = new Set(types);
      for (const n of state.nodes) n.visible = state.visibleTypes.has(n.type);
      draw();
    }
    function byId(id) { return state.nodes.find((n) => n.id === id); }
    function screen(n) { return { x: n.x * state.zoom + state.panX, y: n.y * state.zoom + state.panY }; }
    function edgeKey(a, b) { return a < b ? a + ":" + b : b + ":" + a; }
    function connectedFor(id) {
      return state.hover === id || state.edges.some((e) =>
        (e.source === state.hover && e.target === id) || (e.target === state.hover && e.source === id));
    }

    function buildGrid() {
      const grid = new Map();
      for (let i = 0; i < state.nodes.length; i++) {
        const n = state.nodes[i], key = Math.floor(n.x / GRID_SIZE) + "," + Math.floor(n.y / GRID_SIZE);
        if (!grid.has(key)) grid.set(key, []);
        grid.get(key).push(i);
      }
      return grid;
    }
    function simulate(dt, now) {
      if (state.nodes.length < 2) return;
      const grid = buildGrid(), acc = state.nodes.map(() => ({ x: 0, y: 0 }));
      // Spatial grid and cutoff keep repulsion local instead of comparing every pair.
      for (let i = 0; i < state.nodes.length; i++) {
        const a = state.nodes[i], gx = Math.floor(a.x / GRID_SIZE), gy = Math.floor(a.y / GRID_SIZE);
        for (let ox = -1; ox <= 1; ox++) for (let oy = -1; oy <= 1; oy++) {
          const bucket = grid.get((gx + ox) + "," + (gy + oy)) || [];
          for (const j of bucket) {
            if (j <= i) continue;
            const b = state.nodes[j]; let dx = b.x - a.x, dy = b.y - a.y;
            const d2 = dx * dx + dy * dy;
            if (d2 >= REPULSION_CUTOFF * REPULSION_CUTOFF) continue;
            const d = Math.sqrt(d2) || 0.01, f = Math.min(0.8, REPULSION / (d2 + 400)) * dt;
            dx /= d; dy /= d;
            acc[i].x -= dx * f; acc[i].y -= dy * f; acc[j].x += dx * f; acc[j].y += dy * f;
          }
        }
      }
      const lookup = new Map(state.nodes.map((n, i) => [n.id, i]));
      for (const edge of state.edges) {
        const i = lookup.get(edge.source), j = lookup.get(edge.target);
        if (i === undefined || j === undefined || i === j) continue;
        const a = state.nodes[i], b = state.nodes[j], dx = b.x - a.x, dy = b.y - a.y;
        const d = Math.sqrt(dx * dx + dy * dy) || 0.01, force = (d - IDEAL_LINK) * EDGE_STRENGTH * dt;
        acc[i].x += dx / d * force; acc[i].y += dy / d * force;
        acc[j].x -= dx / d * force; acc[j].y -= dy / d * force;
      }
      const cx = state.width / 2, cy = state.height / 2; let energy = 0;
      for (let i = 0; i < state.nodes.length; i++) {
        const n = state.nodes[i];
        acc[i].x += (cx - n.x) * 0.0007 * dt; acc[i].y += (cy - n.y) * 0.0007 * dt;
        if (!REDUCED.matches && !state.dragging) {
          acc[i].x += Math.sin(now * 0.00042 + n.phase) * 0.003 * dt;
          acc[i].y += Math.cos(now * 0.00038 + n.phase) * 0.003 * dt;
        }
        if (state.dragging && state.dragging.node === n.id) { n.vx = 0; n.vy = 0; continue; }
        n.vx = (n.vx + acc[i].x) * DAMPING; n.vy = (n.vy + acc[i].y) * DAMPING;
        n.x += n.vx * dt; n.y += n.vy * dt; energy += Math.abs(n.vx) + Math.abs(n.vy);
      }
      if (energy < 0.06) state.settleFrames++; else state.settleFrames = 0;
    }
    function drawLabels(nodes) {
      const ordered = nodes.slice().sort((a, b) => b.degree - a.degree || a.title.localeCompare(b.title));
      const boxes = []; ctx.font = "11px Inter, Segoe UI, sans-serif"; ctx.textBaseline = "middle";
      for (const n of ordered) {
        const p = screen(n), label = n.title.length > 34 ? n.title.slice(0, 32) + "…" : n.title;
        const width = ctx.measureText(label).width + 8, height = 17;
        let x = p.x + n.r * state.zoom + 7, y = p.y - 1;
        if (x + width > state.width - 6) x = p.x - n.r * state.zoom - width - 7;
        const box = { left: x, right: x + width, top: y - height / 2, bottom: y + height / 2 };
        const active = n.id === state.hover || n.id === state.selected;
        const collides = boxes.some((b) => !(box.right < b.left || box.left > b.right || box.bottom < b.top || box.top > b.bottom));
        if (collides && !active) continue;
        boxes.push(box); ctx.fillStyle = active ? "#e6fbff" : "rgba(183,212,222,.72)";
        ctx.globalAlpha = state.hover && n.id !== state.hover && !connectedFor(n.id) ? 0.34 : 1;
        ctx.fillText(label, x + 4, y); ctx.globalAlpha = 1;
      }
    }
    function draw() {
      if (!ctx) return;
      ctx.clearRect(0, 0, state.width, state.height);
      const connected = new Set();
      if (state.hover) for (const e of state.edges) if (e.source === state.hover || e.target === state.hover) { connected.add(e.source); connected.add(e.target); }
      const pathEdges = state.path ? new Set(state.path.edges.map((pair) => edgeKey(pair[0], pair[1]))) : null;
      for (const e of state.edges) {
        const a = byId(e.source), b = byId(e.target);
        if (!a || !b || !a.visible || !b.visible) continue;
        const A = screen(a), B = screen(b), pathEdge = pathEdges && pathEdges.has(edgeKey(a.id, b.id));
        const dim = (state.hover && !connected.has(a.id)) || (pathEdges && !pathEdge);
        ctx.beginPath(); ctx.moveTo(A.x, A.y); ctx.lineTo(B.x, B.y);
        ctx.lineWidth = pathEdge ? 1.7 : 0.8;
        ctx.strokeStyle = pathEdge ? "rgba(98,226,227,.72)" : dim ? "rgba(65,115,137,.07)" : "rgba(68,154,180,.23)";
        ctx.stroke();
        const now = performance.now();
        if (!REDUCED.matches && now > state.pulseAt && state.edges.length && e === state.edges[state.pulseIndex % state.edges.length]) {
          const t = Math.min(1, Math.max(0, (now - state.pulseAt) / 1300));
          ctx.beginPath(); ctx.arc(A.x + (B.x - A.x) * t, A.y + (B.y - A.y) * t, 2.2, 0, TAU);
          ctx.fillStyle = "rgba(129,242,243,.74)"; ctx.fill();
        }
      }
      const shown = state.nodes.filter((n) => n.visible);
      for (const n of shown) {
        const p = screen(n), active = n.id === state.hover || n.id === state.selected;
        const dim = state.hover && n.id !== state.hover && !connected.has(n.id);
        ctx.beginPath(); ctx.arc(p.x, p.y, n.r * state.zoom + (active ? 2.2 : 0), 0, TAU);
        ctx.fillStyle = TYPE_COLORS[n.type] || "#95afbd"; ctx.globalAlpha = dim ? 0.22 : 0.9;
        ctx.shadowColor = active ? TYPE_COLORS[n.type] || "#8be7eb" : "transparent";
        ctx.shadowBlur = active ? 16 : 0; ctx.fill(); ctx.shadowBlur = 0; ctx.globalAlpha = 1;
        ctx.beginPath(); ctx.arc(p.x, p.y, n.r * state.zoom + 4.2, 0, TAU);
        ctx.strokeStyle = active ? "rgba(205,251,251,.62)" : "rgba(91,204,215,.14)";
        ctx.lineWidth = 0.65; ctx.stroke();
      }
      drawLabels(shown);
      if (state.edges.length && performance.now() > state.pulseAt + 1500) {
        state.pulseIndex++; state.pulseAt = performance.now() + 6400;
      }
    }
    function frame(now) {
      if (!state.running) return;
      const elapsed = Math.min(1.8, (now - (state.lastTime || now)) / 16.67); state.lastTime = now;
      if (!state.dragging) simulate(elapsed, now);
      draw();
      if (!REDUCED.matches || state.settleFrames < 18 || state.dragging) requestAnimationFrame(frame);
      else state.running = false;
    }
    function wake() { if (!state.running) { state.running = true; state.lastTime = performance.now(); requestAnimationFrame(frame); } }
    function worldPoint(e) { const r = canvas.getBoundingClientRect(); return { x: (e.clientX - r.left - state.panX) / state.zoom, y: (e.clientY - r.top - state.panY) / state.zoom }; }
    function pick(x, y) {
      const w = worldPoint({ clientX: x, clientY: y }); let best = null, bestD = Infinity;
      for (const n of state.nodes) if (n.visible) {
        const d = Math.hypot(n.x - w.x, n.y - w.y);
        if (d < n.r + 8 / state.zoom && d < bestD) { best = n; bestD = d; }
      }
      return best;
    }
    function shortestPath(start, end) {
      const graph = new Map(state.nodes.filter((n) => n.visible).map((n) => [n.id, []]));
      for (const e of state.edges) if (graph.has(e.source) && graph.has(e.target)) {
        graph.get(e.source).push(e.target); graph.get(e.target).push(e.source);
      }
      const queue = [start], previous = new Map([[start, null]]);
      while (queue.length) {
        const at = queue.shift(); if (at === end) break;
        for (const next of graph.get(at) || []) if (!previous.has(next)) { previous.set(next, at); queue.push(next); }
      }
      if (!previous.has(end)) return null;
      const path = []; for (let cur = end; cur !== null; cur = previous.get(cur)) path.push(cur);
      path.reverse(); const pathEdges = [];
      for (let i = 1; i < path.length; i++) pathEdges.push([path[i - 1], path[i]]);
      return { nodes: path, edges: pathEdges };
    }
    function emitPath(id) {
      if (!state.pathStart) {
        state.pathStart = id; state.path = null;
        callbacks.onPathStatus?.("Path start: " + (byId(id)?.title || "note") + ". Shift-click a second note.");
        draw(); return;
      }
      const start = state.pathStart; state.pathStart = null; const result = shortestPath(start, id); state.path = result;
      if (!result) callbacks.onPathStatus?.("No path found between " + (byId(start)?.title || "first note") + " and " + (byId(id)?.title || "second note") + ".");
      else { callbacks.onPathStatus?.("Path found: " + result.nodes.length + " notes, " + result.edges.length + " links."); callbacks.onSelect?.(id); }
      draw();
    }

    canvas.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      const node = pick(e.clientX, e.clientY); canvas.setPointerCapture(e.pointerId);
      state.dragging = node ? { node: node.id } : { pan: true, x: e.clientX, y: e.clientY, panX: state.panX, panY: state.panY };
      state.pointer = { x: e.clientX, y: e.clientY }; state.moved = false;
    });
    canvas.addEventListener("pointermove", (e) => {
      const node = pick(e.clientX, e.clientY); state.hover = node?.id || null;
      canvas.style.cursor = state.dragging ? "grabbing" : node ? "pointer" : "grab";
      if (state.dragging) {
        if (Math.hypot(e.clientX - state.pointer.x, e.clientY - state.pointer.y) > 3) state.moved = true;
        if (state.dragging.node) { const n = byId(state.dragging.node), w = worldPoint(e); if (n) { n.x = w.x; n.y = w.y; } }
        else { state.panX = state.dragging.panX + e.clientX - state.dragging.x; state.panY = state.dragging.panY + e.clientY - state.dragging.y; }
      }
      callbacks.onHover?.(node || null); draw();
    });
    canvas.addEventListener("pointerup", (e) => {
      const d = state.dragging; state.dragging = null;
      if (d && !state.moved) {
        const node = pick(e.clientX, e.clientY);
        if (node) {
          if (e.shiftKey) emitPath(node.id);
          else { state.path = null; state.pathStart = null; state.selected = node.id; callbacks.onSelect?.(node.id); draw(); }
        }
      }
      wake();
    });
    canvas.addEventListener("pointercancel", () => { state.dragging = null; wake(); });
    canvas.addEventListener("wheel", (e) => {
      e.preventDefault(); const before = worldPoint(e), factor = Math.exp(-e.deltaY * 0.0012);
      state.zoom = Math.max(0.35, Math.min(3.2, state.zoom * factor));
      const rect = canvas.getBoundingClientRect();
      state.panX = e.clientX - rect.left - before.x * state.zoom;
      state.panY = e.clientY - rect.top - before.y * state.zoom; draw();
    }, { passive: false });
    canvas.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { state.path = null; state.pathStart = null; callbacks.onPathStatus?.("Path cleared."); draw(); }
    });
    window.addEventListener("resize", resize);
    REDUCED.addEventListener?.("change", () => wake());

    return {
      setData, setVisibleTypes,
      setSelection(id) { state.selected = id; draw(); },
      reset() { state.zoom = 1; state.panX = 0; state.panY = 0; state.path = null; state.pathStart = null; callbacks.onPathStatus?.("View reset. Shift-click two notes to trace a connection."); wake(); draw(); },
      selectById(id) {
        const n = byId(id); if (!n) return;
        state.selected = id; state.panX = state.width / 2 - n.x * state.zoom; state.panY = state.height / 2 - n.y * state.zoom;
        callbacks.onSelect?.(id); draw();
      },
      get visibleCount() { return state.nodes.filter((n) => n.visible).length; }
    };
  }
  window.JarvisGraph = { createGraph, typeColors: TYPE_COLORS };
})();
