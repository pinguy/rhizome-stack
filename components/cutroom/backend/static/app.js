"use strict";

// Cutroom browser controller. Kept dependency-free so the studio works offline.
const state = {
  project: null,
  projects: [],
  models: null,
  queue: { jobs: [], engine: {} },
  activeTab: "plan",
  selectedSong: null,
  pollTimer: null,
  saveTimer: null,
  saving: false,
  assetFilter: "all",
  shotFilter: "all",
  reviewShotId: null,
  reviewTakeId: null,
  selectedTimelineItemId: null,
  selectedTitleId: null,
  timelineDrag: null,
  seenCompletedJobs: new Set(),
};

const BIBLE_LABELS = {
  core_concept: "Core concept", overall_look: "Overall look", genre_style: "Genre / style",
  colour_language: "Colour language", lighting_language: "Lighting language",
  character: "Character description", hair: "Hair", face: "Face", wardrobe: "Wardrobe",
  recurring_props: "Recurring props", location_1: "Primary location",
  additional_locations: "Additional locations", camera_language: "Camera language",
  recurring_motifs: "Recurring motifs", visual_rules: "Visual rules",
  avoid: "Things to avoid", negative_guidance: "Negative guidance",
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, character => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

function formatTime(seconds, milliseconds = false) {
  const value = Math.max(0, Number(seconds) || 0);
  const minutes = Math.floor(value / 60);
  const secs = Math.floor(value % 60);
  const suffix = milliseconds ? `.${String(Math.floor((value % 1) * 1000)).padStart(3, "0")}` : "";
  return `${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}${suffix}`;
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const type = response.headers.get("content-type") || "";
  const body = type.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    throw new Error(body?.error || body || `${response.status} ${response.statusText}`);
  }
  return body;
}

function toast(message, error = false) {
  const element = $("#toast");
  element.textContent = message;
  element.classList.toggle("error", error);
  element.classList.add("show");
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => element.classList.remove("show"), 3200);
}

function setSaveState(message) {
  $("#saveState").textContent = message;
}

function setTab(tab) {
  state.activeTab = tab;
  $$('[data-tab]').forEach(button => button.classList.toggle("active", button.dataset.tab === tab));
  $$(".tab-panel").forEach(panel => panel.classList.toggle("active", panel.id === `tab-${tab}`));
}

function showHome() {
  state.project = null;
  $("#emptyState").classList.remove("hidden");
  $("#workspace").classList.add("hidden");
  $("#projectEyebrow").textContent = "NO PROJECT";
  $("#projectName").value = "Cutroom";
  $("#projectName").disabled = true;
  $$("#recentProjects button").forEach(button => button.classList.remove("active"));
}

function showProject(project) {
  state.project = project;
  $("#emptyState").classList.add("hidden");
  $("#workspace").classList.remove("hidden");
  $("#projectEyebrow").textContent = `PROJECT · ${project.id}`;
  $("#projectName").value = project.name;
  $("#projectName").disabled = false;
  $("#durationLabel").textContent = `/ ${formatTime(project.audio?.duration, true)}`;
  $("#masterAudio").src = `/media/${encodeURIComponent(project.id)}/${project.audio.path.split("/").map(encodeURIComponent).join("/")}`;
  $$("#recentProjects button").forEach(button => button.classList.toggle("active", button.dataset.projectId === project.id));
  setTab(state.activeTab);
  setSaveState(`Saved · revision ${project.revision}`);
  renderSongMap();
  renderBible();
  $("#directorBrief").value = project.director?.brief || "";
  $("#lyrics").value = project.director?.lyrics || "";
  renderAssets();
  renderSeedVault();
  renderShots();
  renderTimeline();
  renderFinish();
}

function mediaUrl(path) {
  if (!state.project || !path) return "";
  const encoded = path.split("/").map(encodeURIComponent).join("/");
  return `/media/${encodeURIComponent(state.project.id)}/${encoded}`;
}

function renderAssets() {
  const assets = state.project?.assets || [];
  const filtered = assets.filter(asset => {
    if (state.assetFilter === "all") return true;
    if (state.assetFilter === "approved") return asset.approved || asset.state === "approved";
    if (state.assetFilter === "favourite") return asset.favourite;
    return asset.state === state.assetFilter;
  });
  $$("[data-asset-filter]").forEach(button => button.classList.toggle("active", button.dataset.assetFilter === state.assetFilter));
  if (!filtered.length) {
    $("#assetGallery").innerHTML = `<div class="empty-gallery"><b>No ${escapeHtml(state.assetFilter === "all" ? "references" : state.assetFilter + " assets")} yet.</b><p>Import one or generate a visual anchor for this production.</p></div>`;
    return;
  }
  $("#assetGallery").innerHTML = filtered.map(asset => `
    <article class="asset-card ${asset.approved ? "approved" : ""}">
      <span class="badge">${escapeHtml(asset.kind || "reference")}</span>
      <img class="asset-image" src="${mediaUrl(asset.path)}" alt="${escapeHtml(asset.kind || "Project reference")}" loading="lazy">
      <div class="asset-info">
        <strong>${escapeHtml(asset.prompt || "Imported reference")}</strong>
        <small>${escapeHtml(asset.model || asset.backend || "local")} · seed ${asset.seed ?? "imported"}</small>
        <small>${asset.width || "?"}×${asset.height || "?"} · ${escapeHtml(asset.state || "candidate")}</small>
      </div>
      <div class="asset-actions">
        <button data-asset-action="approve" data-asset-id="${escapeHtml(asset.id)}">${asset.approved ? "Approved ✓" : "Approve"}</button>
        <button data-asset-action="favourite" data-asset-id="${escapeHtml(asset.id)}">${asset.favourite ? "Favourite ★" : "Favourite"}</button>
        <button data-asset-action="animate" data-asset-id="${escapeHtml(asset.id)}">Animate</button>
        <button data-asset-action="salvage" data-asset-id="${escapeHtml(asset.id)}">Salvage</button>
      </div>
    </article>`).join("");
}

function recordSeed(seed, note = "Generated take") {
  if (!state.project) return null;
  const value = Math.max(1, Math.trunc(Number(seed) || 0));
  const seeds = state.project.seeds || (state.project.seeds = []);
  let entry = seeds.find(item => Number(item.seed) === value);
  if (!entry) {
    entry = { seed: value, favourite: false, known_good: false, bad: false, note, uses: 0 };
    seeds.push(entry);
  }
  entry.uses = Number(entry.uses || 0) + 1;
  entry.last_used_at = Date.now() / 1000;
  return entry;
}

function renderSeedVault() {
  const container = $("#seedList");
  if (!container || !state.project) return;
  const seeds = [...(state.project.seeds || [])].sort((a, b) =>
    Number(Boolean(b.favourite)) - Number(Boolean(a.favourite)) ||
    Number(Boolean(b.known_good)) - Number(Boolean(a.known_good)) ||
    Number(b.last_used_at || 0) - Number(a.last_used_at || 0));
  container.innerHTML = seeds.length ? seeds.map(entry => `
    <article class="seed-entry ${entry.bad ? "bad" : ""}" data-seed="${Number(entry.seed)}">
      <b>${Number(entry.seed)}</b>
      <div class="seed-flags">${entry.known_good ? "<span>KNOWN GOOD</span>" : ""}${entry.favourite ? "<span>★ FAVOURITE</span>" : ""}${entry.bad ? "<span>BAD MOTION</span>" : ""}</div>
      <input data-seed-note="${Number(entry.seed)}" value="${escapeHtml(entry.note || "")}" aria-label="Seed note">
      <small>${Number(entry.uses || 0)} recorded use${Number(entry.uses || 0) === 1 ? "" : "s"}</small>
      <nav>
        <button data-seed-action="apply" data-seed="${Number(entry.seed)}">Use on all shots</button>
        <button data-seed-action="favourite" data-seed="${Number(entry.seed)}">${entry.favourite ? "Unfavourite" : "Favourite"}</button>
        <button data-seed-action="known" data-seed="${Number(entry.seed)}">${entry.known_good ? "Unmark known" : "Known good"}</button>
        <button data-seed-action="bad" data-seed="${Number(entry.seed)}">${entry.bad ? "Clear bad" : "Mark bad"}</button>
        <button data-seed-action="remove" data-seed="${Number(entry.seed)}">Remove</button>
      </nav>
    </article>`).join("") : '<p class="muted">No seeds recorded yet.</p>';
}

function addSeedFromForm(randomise = false) {
  if (!state.project) return;
  const seed = randomise ? randomSeed() : Math.max(1, Math.trunc(Number($("#seedValue").value) || 420251006));
  $("#seedValue").value = String(seed);
  if (randomise) return;
  const note = $("#seedNote").value.trim() || "Saved manually";
  const existing = (state.project.seeds || []).find(item => Number(item.seed) === seed);
  if (existing) existing.note = note;
  else recordSeed(seed, note);
  $("#seedNote").value = "";
  renderSeedVault();
  scheduleSave();
}

function updateSeed(action, value) {
  if (!state.project) return;
  const seeds = state.project.seeds || (state.project.seeds = []);
  const entry = seeds.find(item => Number(item.seed) === Number(value));
  if (!entry) return;
  if (action === "apply") {
    (state.project.shots || []).forEach(shot => { shot.seed = Number(entry.seed); });
    entry.uses = Number(entry.uses || 0) + 1;
    entry.last_used_at = Date.now() / 1000;
    renderShots();
    toast(`Seed ${entry.seed} copied to every shot.`);
  }
  if (action === "favourite") entry.favourite = !entry.favourite;
  if (action === "known") entry.known_good = !entry.known_good;
  if (action === "bad") {
    entry.bad = !entry.bad;
    if (entry.bad) entry.favourite = false;
  }
  if (action === "remove") state.project.seeds = seeds.filter(item => item !== entry);
  renderSeedVault();
  scheduleSave();
}

function shotState(shot) {
  const takes = shot.takes || [];
  if (shot.selected_take_id || takes.some(take => take.state === "keep")) return "kept";
  if (takes.some(take => take.state === "review" || take.state === "candidate")) return "review";
  return "unshot";
}

function renderShots() {
  if (!state.project) return;
  const presets = state.models?.presets || {
    compatibility: [768, 448], draft: [832, 480], quality: [1280, 704],
  };
  const advertisedBackends = state.models?.video_backends?.filter(item => item.ready) || [];
  const backends = advertisedBackends.length ? advertisedBackends : [
    { id: "wan-2.2-rapid", name: "WAN 2.2 Rapid Q5_K", fps: 16, t2v: true, i2v: false },
  ];
  const references = (state.project.assets || []).filter(asset => asset.approved || asset.state === "approved");
  $$('[data-shot-filter]').forEach(button => button.classList.toggle("active", button.dataset.shotFilter === state.shotFilter));
  const shots = (state.project.shots || []).filter(shot => state.shotFilter === "all" || shotState(shot) === state.shotFilter);
  if (!shots.length) {
    $("#shotFactory").innerHTML = `<div class="empty-gallery"><b>No ${escapeHtml(state.shotFilter)} shots.</b><p>Change the filter or return to the shot plan.</p></div>`;
    return;
  }
  $("#shotFactory").innerHTML = shots.map(shot => {
    const status = shotState(shot);
    const preset = shot.preset || state.project.settings?.default_preset || "compatibility";
    const backendId = shot.backend || state.project.settings?.video_backend || state.models?.default_video_backend || "wan-2.2-rapid";
    const backend = backends.find(item => item.id === backendId) || backends[0] || { id: backendId, fps: 16, t2v: true, i2v: false };
    const frames = state.models?.valid_frames_by_backend?.[backend.id] || state.models?.valid_frames || [17, 33, 49, 65, 81];
    const selectedFrames = frames.includes(Number(shot.frames)) ? Number(shot.frames) : frames[0];
    const fps = Number(backend.fps) || 16;
    const takes = shot.takes || [];
    const referenceOptions = ['<option value="">Choose approved reference</option>'].concat(references.map(asset =>
      `<option value="${escapeHtml(asset.id)}" ${shot.reference_asset_id === asset.id ? "selected" : ""}>${escapeHtml(asset.kind)} · ${escapeHtml(asset.id.slice(-6))}</option>`
    )).join("");
    return `<article class="shot-card" data-shot-id="${escapeHtml(shot.id)}">
      <div class="shot-ident">
        <b>${String(shot.number).padStart(3, "0")}</b>
        <span class="shot-status ${status}">${escapeHtml(status)}</span>
        <strong>${escapeHtml(shot.section || "Sequence")}</strong>
        <small>${formatTime(shot.start, true)} → ${formatTime(shot.end, true)}</small>
        <small>${Number(shot.duration || 0).toFixed(2)} sec timeline slot</small>
      </div>
      <div class="shot-compose">
        <textarea data-shot-field="prompt" aria-label="Shot prompt">${escapeHtml(shot.prompt || "")}</textarea>
        <details><summary>Negative guidance</summary><textarea data-shot-field="negative" rows="3">${escapeHtml(shot.negative || state.project.bible?.negative_guidance || "")}</textarea></details>
        <div class="shot-controls">
          <label>Backend<select data-shot-field="backend">${backends.map(item => `<option value="${escapeHtml(item.id)}" ${backend.id === item.id ? "selected" : ""}>${escapeHtml(item.name)}</option>`).join("")}</select></label>
          <label>Mode<select data-shot-field="mode"><option value="i2v" ${shot.mode === "i2v" ? "selected" : ""} ${backend.i2v ? "" : "disabled"}>I2V · ${backend.i2v ? "reference" : "download pending"}</option><option value="t2v" ${shot.mode !== "i2v" ? "selected" : ""}>T2V · prompt</option></select></label>
          <label>Reference<select data-shot-field="reference_asset_id" ${shot.mode !== "i2v" || !backend.i2v ? "disabled" : ""}>${referenceOptions}</select></label>
          <label>Generated length<select data-shot-field="frames">${frames.map(value => `<option value="${value}" ${selectedFrames === value ? "selected" : ""}>${value}f · ${((value - 1) / fps).toFixed(2)}s</option>`).join("")}</select></label>
          <label>Resolution<select data-shot-field="preset">${Object.entries(presets).map(([key, size]) => `<option value="${escapeHtml(key)}" ${preset === key ? "selected" : ""}>${escapeHtml(key)} · ${size[0]}×${size[1]}</option>`).join("")}</select></label>
          <label>Seed<input data-shot-field="seed" type="number" value="${Number(shot.seed ?? 420251006)}"></label>
          <label>Takes<input data-shot-field="take_count" type="number" min="1" max="12" value="${Math.max(1, Math.min(12, Number(shot.take_count) || 1))}"></label>
        </div>
        <button class="primary" data-shot-action="generate" data-shot-id="${escapeHtml(shot.id)}">Generate ${shot.mode === "i2v" ? "reference-led" : "text-led"} takes · ${escapeHtml(backend.name || backend.id)}</button>
      </div>
      <div class="takes">
        ${takes.length ? takes.map(take => `<article class="take ${escapeHtml(take.state || "review")}">
          <video src="${mediaUrl(take.path)}" controls muted playsinline preload="metadata"></video>
          <span class="take-state">${escapeHtml((take.state || "review").toUpperCase())}</span>
          <span class="take-qc ${escapeHtml(take.qc?.status || "unscored")}">${escapeHtml((take.qc?.status || "unscored").toUpperCase())}</span>
          <small>seed ${take.seed}</small>
          <button data-take-action="review" data-shot-id="${escapeHtml(shot.id)}" data-take-id="${escapeHtml(take.id)}">Review motion</button>
        </article>`).join("") : '<div class="takes-empty"><b>No motion takes</b><small>Generate one or more seeds, then judge the moving footage.</small></div>'}
      </div>
    </article>`;
  }).join("");
}

function findTake(shotId, takeId) {
  const shot = state.project?.shots?.find(item => item.id === shotId);
  return { shot, take: shot?.takes?.find(item => item.id === takeId) };
}

function openTakeReview(shotId, takeId) {
  const { shot, take } = findTake(shotId, takeId);
  if (!shot || !take) return;
  state.reviewShotId = shotId;
  state.reviewTakeId = takeId;
  $("#reviewContent").innerHTML = `<div class="review-grid">
    <div>
      <video id="reviewVideo" class="review-video" src="${mediaUrl(take.path)}" controls playsinline preload="auto"></video>
      <div class="frame-controls"><button data-review-action="step-back">← Frame</button><button data-review-action="step-forward">Frame →</button><span>Always judge this take in motion.</span></div>
    </div>
    <aside>
      <span class="review-kicker">SHOT ${String(shot.number).padStart(3, "0")} · ${escapeHtml((take.state || "review").toUpperCase())}</span>
      <h2>Take ${escapeHtml(take.id.slice(-6))}</h2>
      <p>${escapeHtml(take.prompt || shot.prompt || "")}</p>
      <div class="review-meta">seed ${take.seed}<br>${take.width}×${take.height} · ${take.frames}f · ${Number(take.fps || 24)}fps<br>${escapeHtml((take.mode || shot.mode || "t2v").toUpperCase())} · ${escapeHtml(take.backend || "ltx-2.5")} ${escapeHtml(take.quant || "")}<br>QC ${escapeHtml((take.qc?.status || "unscored").toUpperCase())}${take.qc?.warnings?.length ? `<br>${take.qc.warnings.map(escapeHtml).join("<br>")}` : " · no automated warnings"}</div>
      <div class="form-row review-trims"><label>Useful from<input data-take-field="trim_in" type="number" min="0" step="${(1 / Number(take.fps || 24)).toFixed(6)}" value="${Number(take.trim_in || 0)}"></label><label>Useful to<input data-take-field="trim_out" type="number" min="0" step="${(1 / Number(take.fps || 24)).toFixed(6)}" placeholder="full take" value="${take.trim_out ?? ""}"></label></div>
      <div class="review-actions">
        <button class="keep" data-review-action="keep">KEEP → timeline</button>
        <button class="salvage" data-review-action="salvage">SALVAGE</button>
        <button data-review-action="same-seed">Regenerate same seed</button>
        <button data-review-action="new-seed">Regenerate new seed</button>
        <button class="bin" data-review-action="bin">BIN take</button>
        <button data-review-action="close">Close review</button>
      </div>
    </aside>
  </div>`;
  $("#reviewModal").classList.remove("hidden");
}

function closeTakeReview() {
  const video = $("#reviewVideo");
  if (video) video.pause();
  $("#reviewModal").classList.add("hidden");
  state.reviewShotId = null;
  state.reviewTakeId = null;
}

function timelineDuration() {
  return Number(state.project?.analysis?.audio?.duration || state.project?.audio?.duration || 0);
}

function renderTimeline() {
  if (!state.project) return;
  const timeline = state.project.timeline || (state.project.timeline = { snap: true, zoom: 1, items: [], titles: [] });
  const duration = Math.max(.001, timelineDuration());
  const zoom = Math.max(1, Number(timeline.zoom) || 1);
  $("#zoomRange").value = String(zoom);
  $("#snapButton").classList.toggle("on", timeline.snap !== false);
  $("#snapButton").textContent = timeline.snap === false ? "⌁ Free" : "⌁ Snap";
  const edit = $("#editTimeline");
  edit.style.width = `${zoom * 100}%`;
  edit.style.minWidth = `${Math.max(900, zoom * 900)}px`;
  const step = duration <= 30 ? 1 : duration <= 120 ? 5 : 10;
  const marks = [];
  for (let second = 0; second <= duration + .001; second += step) {
    marks.push(`<span style="left:${second / duration * 100}%">${formatTime(second)}</span>`);
  }
  $("#timelineRuler").innerHTML = marks.join("");
  $("#timelineRuler").style.width = edit.style.width;
  $("#timelineRuler").style.minWidth = edit.style.minWidth;
  const items = [...(timeline.items || [])].sort((a, b) => a.start - b.start);
  const shotMap = new Map((state.project.shots || []).map(shot => [shot.id, shot]));
  $("#timelineBlocks").innerHTML = items.map(item => {
    const shot = shotMap.get(item.shot_id);
    const left = Math.max(0, Number(item.start) / duration * 100);
    const width = Math.max(.1, (Number(item.end) - Number(item.start)) / duration * 100);
    const selected = item.id === state.selectedTimelineItemId;
    return `<article class="timeline-block ${selected ? "selected" : ""} ${item.take_id ? "filled" : "missing"}" data-timeline-id="${escapeHtml(item.id)}" style="left:${left}%;width:${width}%">
      <i class="handle left" data-boundary="left"></i><b>${shot ? String(shot.number).padStart(3, "0") : "—"}</b>
      <span>${escapeHtml(shot?.section || item.shot_id || "Untitled")}</span>
      <small>${item.take_id ? "TAKE" : "MISSING"}</small><i class="handle right" data-boundary="right"></i>
    </article>`;
  }).join("") + (timeline.titles || []).map(title => {
    const left = Math.max(0, Number(title.start) / duration * 100);
    const width = Math.max(.1, (Number(title.end) - Number(title.start)) / duration * 100);
    return `<article class="title-block ${title.id === state.selectedTitleId ? "selected" : ""}" data-title-id="${escapeHtml(title.id)}" style="left:${left}%;width:${width}%">T · ${escapeHtml(title.text || "TITLE")}</article>`;
  }).join("");
  renderEditInspector();
  renderCoverage();
  requestAnimationFrame(drawWaveforms);
}

function renderCoverage() {
  const timeline = state.project?.timeline || {};
  const duration = timelineDuration();
  const items = [...(timeline.items || [])].sort((a, b) => a.start - b.start);
  const missing = items.filter(item => !item.take_id).length;
  let gaps = items.length ? Math.max(0, items[0].start) : duration;
  let overlaps = 0;
  items.forEach((item, index) => {
    if (index) {
      const delta = item.start - items[index - 1].end;
      if (delta > .002) gaps += delta;
      if (delta < -.002) overlaps += -delta;
    }
  });
  if (items.length) gaps += Math.max(0, duration - items.at(-1).end);
  const covered = Math.max(0, duration - gaps);
  $("#coverageReport").innerHTML = [
    ["Master clock", formatTime(duration, true), "good"],
    ["Timeline coverage", `${duration ? Math.round(covered / duration * 100) : 0}%`, gaps < .002 ? "good" : "warn"],
    ["Missing takes", String(missing), missing ? "warn" : "good"],
    ["Gaps", `${gaps.toFixed(3)}s`, gaps < .002 ? "good" : "warn"],
    ["Overlaps", `${overlaps.toFixed(3)}s`, overlaps < .002 ? "good" : "warn"],
  ].map(([label, value, tone]) => `<div class="coverage-row"><b>${label}</b><span class="${tone}">${value}</span></div>`).join("");
}

function renderEditInspector() {
  const timeline = state.project?.timeline || {};
  const title = (timeline.titles || []).find(item => item.id === state.selectedTitleId);
  if (title) {
    $("#inspectorTitle").textContent = "Title overlay";
    $("#editInspector").innerHTML = `<label>Text<input data-title-field="text" value="${escapeHtml(title.text || "")}"></label>
      <div class="form-row"><label>Start<input data-title-field="start" type="number" min="0" step="0.001" value="${Number(title.start).toFixed(3)}"></label><label>End<input data-title-field="end" type="number" min="0" step="0.001" value="${Number(title.end).toFixed(3)}"></label></div>
      <div class="form-row"><label>Size<input data-title-field="size" type="number" min="12" max="180" value="${Number(title.size || 52)}"></label><label>Position<select data-title-field="position"><option value="upper" ${title.position === "upper" ? "selected" : ""}>Upper</option><option value="centre" ${title.position === "centre" ? "selected" : ""}>Centre</option><option value="lower" ${title.position === "lower" ? "selected" : ""}>Lower</option></select></label></div>
      <button class="ghost danger" data-timeline-action="delete-title">Delete title</button>`;
    return;
  }
  const item = (timeline.items || []).find(entry => entry.id === state.selectedTimelineItemId);
  if (!item) {
    $("#inspectorTitle").textContent = "Select a shot block";
    $("#editInspector").innerHTML = '<p class="muted">Select a block to adjust its song-clock boundaries, source trim, speed, fit and transition. The source song remains locked.</p>';
    return;
  }
  const shot = state.project.shots?.find(entry => entry.id === item.shot_id);
  const takes = shot?.takes || [];
  $("#inspectorTitle").textContent = `Shot ${String(shot?.number || "—").padStart(3, "0")}`;
  $("#editInspector").innerHTML = `<div class="form-row"><label>Song start<input data-item-field="start" type="number" min="0" step="0.001" value="${Number(item.start).toFixed(3)}"></label><label>Song end<input data-item-field="end" type="number" min="0" step="0.001" value="${Number(item.end).toFixed(3)}"></label></div>
    <label>Take<select data-item-field="take_id"><option value="">Missing / black card</option>${takes.filter(take => take.state !== "bin").map(take => `<option value="${escapeHtml(take.id)}" ${item.take_id === take.id ? "selected" : ""}>${escapeHtml(take.id.slice(-6))} · ${take.seed} · ${escapeHtml(take.state)}</option>`).join("")}</select></label>
    <div class="form-row"><label>Source trim in<input data-item-field="trim_in" type="number" min="0" step="0.042" value="${Number(item.trim_in || 0)}"></label><label>Speed<input data-item-field="speed" type="number" min="0.1" max="4" step="0.05" value="${Number(item.speed || 1)}"></label></div>
    <div class="form-row"><label>Fit<select data-item-field="fit"><option value="cover" ${item.fit !== "contain" ? "selected" : ""}>Crop to fill</option><option value="contain" ${item.fit === "contain" ? "selected" : ""}>Fit with bars</option></select></label><label>Transition<select data-item-field="transition"><option value="cut" ${item.transition !== "fade" ? "selected" : ""}>Hard cut</option><option value="fade" ${item.transition === "fade" ? "selected" : ""}>Fade through black</option></select></label></div>
    <label class="check-line"><input data-item-field="reverse" type="checkbox" ${item.reverse ? "checked" : ""}> Reverse source motion</label>
    <div class="inspector-actions"><button class="ghost" data-timeline-action="move-left">← Earlier</button><button class="ghost" data-timeline-action="duplicate">Duplicate</button><button class="ghost" data-timeline-action="move-right">Later →</button><button class="ghost" data-timeline-action="clear-take">Clear take</button></div>`;
}

function nearestSnap(value) {
  const duration = timelineDuration();
  const clamped = Math.max(0, Math.min(duration, Number(value) || 0));
  if (state.project?.timeline?.snap === false) return Math.round(clamped * 1000) / 1000;
  const points = [0, duration, ...(state.project.analysis?.bars || []), ...(state.project.analysis?.beats || [])];
  return Math.round(points.reduce((best, point) => Math.abs(point - clamped) < Math.abs(best - clamped) ? point : best, clamped) * 1000) / 1000;
}

function timelineItems() {
  return [...(state.project?.timeline?.items || [])].sort((a, b) => a.start - b.start);
}

function selectTimelineItem(itemId) {
  state.selectedTimelineItemId = itemId;
  state.selectedTitleId = null;
  renderTimeline();
}

function splitTimelineItem() {
  if (!state.project) return;
  const playhead = $("#masterAudio").currentTime;
  const items = timelineItems();
  const item = items.find(entry => entry.id === state.selectedTimelineItemId)
    || items.find(entry => playhead > entry.start + .04 && playhead < entry.end - .04);
  if (!item) return toast("Select a block or place the playhead inside one.", true);
  const cut = nearestSnap(playhead > item.start + .04 && playhead < item.end - .04 ? playhead : (item.start + item.end) / 2);
  if (cut <= item.start + .04 || cut >= item.end - .04) return toast("That cut is too close to the block edge.", true);
  const right = { ...item, id: `item-${window.crypto.randomUUID()}`, start: cut };
  right.trim_in = Number(item.trim_in || 0) + (cut - item.start) * Number(item.speed || 1);
  item.end = cut;
  state.project.timeline.items.push(right);
  state.selectedTimelineItemId = right.id;
  renderTimeline();
  scheduleSave();
}

function mergeTimelineRight() {
  const items = timelineItems();
  let index = items.findIndex(item => item.id === state.selectedTimelineItemId);
  if (index < 0) index = items.findIndex(item => $("#masterAudio").currentTime >= item.start && $("#masterAudio").currentTime < item.end);
  if (index < 0 || index >= items.length - 1) return toast("Select a block with a cut to its right.", true);
  const item = items[index];
  const right = items[index + 1];
  item.end = right.end;
  state.project.timeline.items = state.project.timeline.items.filter(entry => entry.id !== right.id);
  state.selectedTimelineItemId = item.id;
  renderTimeline();
  scheduleSave();
}

function swapTimelineContent(direction) {
  const items = timelineItems();
  const index = items.findIndex(item => item.id === state.selectedTimelineItemId);
  const otherIndex = index + direction;
  if (index < 0 || otherIndex < 0 || otherIndex >= items.length) return;
  const keys = ["shot_id", "take_id", "trim_in", "speed", "reverse", "fit", "transition"];
  for (const key of keys) [items[index][key], items[otherIndex][key]] = [items[otherIndex][key], items[index][key]];
  state.selectedTimelineItemId = items[otherIndex].id;
  renderTimeline();
  scheduleSave();
}

function duplicateTimelineItem() {
  const item = state.project?.timeline?.items?.find(entry => entry.id === state.selectedTimelineItemId);
  if (!item || item.end - item.start < .1) return;
  const midpoint = Math.round((item.start + item.end) * 500) / 1000;
  const copy = { ...item, id: `item-${window.crypto.randomUUID()}`, start: midpoint };
  item.end = midpoint;
  state.project.timeline.items.push(copy);
  state.selectedTimelineItemId = copy.id;
  renderTimeline();
  scheduleSave();
}

function addTitle() {
  if (!state.project) return;
  const start = Math.max(0, Math.min(timelineDuration() - .04, $("#masterAudio").currentTime || 0));
  const title = { id: `title-${window.crypto.randomUUID()}`, text: "TITLE", start, end: Math.min(timelineDuration(), start + 3), size: 52, position: "lower" };
  state.project.timeline.titles.push(title);
  state.selectedTitleId = title.id;
  state.selectedTimelineItemId = null;
  renderTimeline();
  scheduleSave();
}

function timelineAction(action) {
  if (action === "split") splitTimelineItem();
  if (action === "merge") mergeTimelineRight();
  if (action === "move-left") swapTimelineContent(-1);
  if (action === "move-right") swapTimelineContent(1);
  if (action === "duplicate") duplicateTimelineItem();
  if (action === "clear-take") {
    const item = state.project?.timeline?.items?.find(entry => entry.id === state.selectedTimelineItemId);
    if (item) { item.take_id = null; renderTimeline(); scheduleSave(); }
  }
  if (action === "delete-title" && state.selectedTitleId) {
    state.project.timeline.titles = state.project.timeline.titles.filter(title => title.id !== state.selectedTitleId);
    state.selectedTitleId = null; renderTimeline(); scheduleSave();
  }
}

function updateTimelineBoundary(item, boundary, rawValue) {
  const items = timelineItems();
  const index = items.findIndex(entry => entry.id === item.id);
  if (index < 0) return;
  if (boundary === "start") {
    const min = index ? items[index - 1].start + .04 : 0;
    const value = Math.max(min, Math.min(item.end - .04, nearestSnap(rawValue)));
    item.start = value;
    if (index) items[index - 1].end = value;
  } else {
    const max = index < items.length - 1 ? items[index + 1].end - .04 : timelineDuration();
    const value = Math.max(item.start + .04, Math.min(max, nearestSnap(rawValue)));
    item.end = value;
    if (index < items.length - 1) items[index + 1].start = value;
  }
}

function renderFinish() {
  if (!state.project) return;
  const renderState = state.project.render_state || { status: "idle" };
  const button = $('[data-action="render"]');
  if (button) {
    button.disabled = renderState.status === "running";
    button.innerHTML = renderState.status === "running" ? "Rendering local master…" : 'Render music video <span>→</span>';
  }
  const missing = (state.project.timeline?.items || []).filter(item => !item.take_id).length;
  if (renderState.status === "running") {
    const elapsed = Math.max(0, Math.round(Date.now() / 1000 - Number(renderState.started_at || Date.now() / 1000)));
    $("#renderState").innerHTML = `<b>Rendering</b> · ${elapsed}s elapsed · FFmpeg is assembling the song-clock timeline.`;
  } else if (renderState.status === "failed") {
    $("#renderState").innerHTML = `<b class="bad">Render failed</b> · ${escapeHtml(renderState.error || "See project log")}`;
  } else if (renderState.status === "complete") {
    $("#renderState").innerHTML = `<b class="good">Render complete</b> · ${renderState.result?.width || "?"}×${renderState.result?.height || "?"} · ${formatTime(renderState.result?.duration, true)}`;
  } else {
    $("#renderState").innerHTML = missing
      ? `<b>${missing} timeline ${missing === 1 ? "slot has" : "slots have"} no kept take.</b> They will render as labelled placeholders until coverage is complete.`
      : "Ready to render the approved timeline against the source song.";
  }
  const renders = [...(state.project.renders || [])].reverse();
  $("#renderHistory").innerHTML = renders.length ? renders.map(item => `<article class="render-item">
    <video controls preload="metadata" src="${mediaUrl(item.path)}"></video>
    <div><b>${escapeHtml(item.preset || "master")} · ${item.width}×${item.height}</b><small>${formatTime(item.duration, true)} · exact song clock</small></div>
    <nav><a href="${mediaUrl(item.path)}" target="_blank">Open MP4</a><a href="${mediaUrl(item.manifest)}" target="_blank">Manifest</a><a href="${mediaUrl(item.shot_list)}" target="_blank">Shot list</a><a href="${mediaUrl(item.log)}" target="_blank">Render log</a></nav>
  </article>`).join("") : '<div class="empty-gallery"><b>No delivery masters yet.</b><p>The first render will appear here with its manifest and log.</p></div>';
}

async function startFinalRender() {
  if (!state.project) return;
  const preset = $('input[name="renderPreset"]:checked')?.value || "720p";
  try {
    await saveProject();
    await api(`/api/project/${encodeURIComponent(state.project.id)}/render`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ preset }),
    });
    state.project = await api(`/api/project/${encodeURIComponent(state.project.id)}`);
    renderFinish();
    toast("Final render started locally.");
  } catch (error) {
    toast(error.message, true);
  }
}

async function setTakeState(value) {
  if (!state.project || !state.reviewShotId || !state.reviewTakeId) return;
  try {
    const project = await api(`/api/project/${encodeURIComponent(state.project.id)}/take/${encodeURIComponent(state.reviewTakeId)}/state`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ state: value }),
    });
    showProject(project);
    closeTakeReview();
    toast(value === "keep" ? "Take kept and sent to the timeline." : value === "salvage" ? "Take moved to the Salvage Bin." : "Take binned without deleting its source file.");
  } catch (error) {
    toast(error.message, true);
  }
}

async function uploadAsset(file) {
  if (!state.project || !file) return;
  setSaveState("Importing reference…");
  try {
    await api(`/api/project/${encodeURIComponent(state.project.id)}/asset/upload`, {
      method: "POST",
      headers: {
        "Content-Type": file.type || "application/octet-stream",
        "X-Filename": encodeURIComponent(file.name),
        "X-Asset-Kind": $("#assetKind").value,
        "X-Shot-Id": $("#assetShot").value,
      },
      body: file,
    });
    await openProject(state.project.id);
    toast("Reference imported and approved.");
  } catch (error) {
    setSaveState("Import failed");
    toast(error.message, true);
  } finally {
    $("#assetFile").value = "";
  }
}

async function updateAsset(assetId, action) {
  const asset = state.project?.assets.find(item => item.id === assetId);
  if (!asset) return;
  if (action === "animate") {
    const shotId = asset.shot_id || $("#assetShot").value || state.project.shots?.[0]?.id;
    const shot = state.project.shots?.find(item => item.id === shotId);
    if (!shot) return toast("Create or choose a shot before animating this reference.", true);
    shot.reference_asset_id = asset.id;
    shot.mode = "i2v";
    asset.shot_id = shot.id;
    await saveProject();
    setTab("shots");
    toast(`Reference attached to shot ${shot.number}.`);
    return;
  }
  const body = action === "approve"
    ? { approved: !asset.approved, state: asset.approved ? "candidate" : "approved" }
    : action === "favourite"
      ? { favourite: !asset.favourite }
      : { state: "salvage", approved: false };
  try {
    const project = await api(`/api/project/${encodeURIComponent(state.project.id)}/asset/${encodeURIComponent(assetId)}/state`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    showProject(project);
  } catch (error) {
    toast(error.message, true);
  }
}

function renderBible() {
  const bible = state.project?.bible || {};
  $("#bibleFields").innerHTML = Object.entries(BIBLE_LABELS).map(([key, label]) => `
    <label>${escapeHtml(label)}
      <textarea data-bible-field="${escapeHtml(key)}" placeholder="Define ${escapeHtml(label.toLowerCase())}…">${escapeHtml(bible[key] || "")}</textarea>
    </label>`).join("");
}

function scheduleSave() {
  if (!state.project) return;
  setSaveState("Unsaved changes");
  window.clearTimeout(state.saveTimer);
  state.saveTimer = window.setTimeout(() => saveProject(), 700);
}

async function saveProject() {
  if (!state.project || state.saving) return;
  state.saving = true;
  window.clearTimeout(state.saveTimer);
  setSaveState("Saving…");
  try {
    const saved = await api(`/api/project/${encodeURIComponent(state.project.id)}/save`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(state.project),
    });
    state.project = saved;
    setSaveState(`Saved · revision ${saved.revision}`);
    await refreshProjects();
  } catch (error) {
    setSaveState("Save failed");
    toast(error.message, true);
  } finally {
    state.saving = false;
  }
}

function renderSongMap() {
  const project = state.project;
  const analysis = project?.analysis;
  if (!analysis) return;
  const duration = analysis.audio?.duration || project.audio?.duration || 0;
  const sections = analysis.sections || [];
  $("#analysisCards").innerHTML = [
    [analysis.bpm?.toFixed?.(1) || analysis.bpm || "—", "Estimated BPM"],
    [formatTime(duration), "Master duration"],
    [String(project.shots?.length || 0), "Proposed shots"],
    [String(sections.length), "Song regions"],
  ].map(([value, label]) => `<div class="metric"><b>${escapeHtml(value)}</b><span>${escapeHtml(label)}</span></div>`).join("");

  $("#sections").innerHTML = sections.length ? sections.map(section => `
    <div class="section-row">
      <small>${formatTime(section.start)}–${formatTime(section.end)}</small>
      <div><strong>${escapeHtml(section.name)}</strong><div class="energy-bar"><i style="width:${Math.round((section.energy || 0) * 100)}%"></i></div></div>
      <small>${Math.round((section.energy || 0) * 100)}%</small>
    </div>`).join("") : '<p class="muted">No broad regions detected.</p>';

  $("#shotCount").textContent = `${project.shots?.length || 0} shots`;
  $("#shotPlan").innerHTML = (project.shots || []).map(shot => `
    <div class="shot-row">
      <b>${String(shot.number).padStart(3, "0")}</b>
      <small>${formatTime(shot.start, true)}<br>${shot.duration.toFixed(2)} sec</small>
      <div><strong>${escapeHtml(shot.section)}</strong><small>${escapeHtml(shot.prompt || "Awaiting visual direction")}</small></div>
      <span>${escapeHtml(shot.framing)} · ${escapeHtml(shot.camera)}</span>
      <small>${escapeHtml(shot.mode.toUpperCase())}<br>${shot.frames}f</small>
    </div>`).join("");

  const shotSelect = $("#assetShot");
  shotSelect.innerHTML = '<option value="">Project-wide</option>' + (project.shots || []).map(shot =>
    `<option value="${escapeHtml(shot.id)}">${String(shot.number).padStart(3, "0")} · ${formatTime(shot.start)}</option>`
  ).join("");
  requestAnimationFrame(drawWaveforms);
}

function drawWave(canvas, height) {
  const analysis = state.project?.analysis;
  if (!analysis) return;
  const duration = analysis.audio?.duration || 1;
  const ratio = window.devicePixelRatio || 1;
  const width = Math.max(320, canvas.clientWidth);
  canvas.width = Math.floor(width * ratio);
  canvas.height = Math.floor(height * ratio);
  const context = canvas.getContext("2d");
  context.scale(ratio, ratio);
  context.clearRect(0, 0, width, height);

  context.strokeStyle = "rgba(255,177,59,.34)";
  context.lineWidth = 1;
  for (const bar of analysis.bars || []) {
    const x = bar / duration * width;
    context.beginPath(); context.moveTo(x, 0); context.lineTo(x, height); context.stroke();
  }

  context.strokeStyle = "rgba(93,228,255,.16)";
  for (const beat of analysis.beats || []) {
    const x = beat / duration * width;
    context.beginPath(); context.moveTo(x, height * .72); context.lineTo(x, height); context.stroke();
  }

  const waveform = analysis.waveform || [];
  context.strokeStyle = "#5de4ff";
  context.lineWidth = 1;
  context.beginPath();
  waveform.forEach((bucket, index) => {
    const x = index / Math.max(1, waveform.length - 1) * width;
    context.moveTo(x, height * (.5 + bucket[0] * .44));
    context.lineTo(x, height * (.5 + bucket[1] * .44));
  });
  context.stroke();

  context.strokeStyle = "rgba(255,255,255,.45)";
  context.setLineDash([3, 4]);
  for (const shot of state.project.shots || []) {
    const x = shot.start / duration * width;
    context.beginPath(); context.moveTo(x, 0); context.lineTo(x, height); context.stroke();
  }
  context.setLineDash([]);
}

function drawWaveforms() {
  drawWave($("#waveform"), 108);
  drawWave($("#editWaveform"), 72);
}

function updatePlayhead() {
  const audio = $("#masterAudio");
  const duration = state.project?.analysis?.audio?.duration || audio.duration || 1;
  const percent = Math.min(100, audio.currentTime / duration * 100);
  $("#playTime").textContent = formatTime(audio.currentTime, true);
  $("#playhead").style.left = `${percent}%`;
  $("#editPlayhead").style.left = `${percent}%`;
  $("#playButton").textContent = audio.paused ? "▶" : "❚❚";
}

function seekFromPointer(event, element) {
  if (!state.project) return;
  const rect = element.getBoundingClientRect();
  const fraction = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
  $("#masterAudio").currentTime = fraction * (state.project.analysis?.audio?.duration || 0);
  updatePlayhead();
}

function renderRecentProjects() {
  const container = $("#recentProjects");
  if (!state.projects.length) {
    container.innerHTML = '<p class="muted">No productions yet.</p>';
    return;
  }
  container.innerHTML = state.projects.map(project => `
    <button data-project-id="${escapeHtml(project.id)}" class="${state.project?.id === project.id ? "active" : ""}">
      <strong>${escapeHtml(project.name)}</strong>
      <small>${formatTime(project.duration)} · ${project.shots} shots · ${project.assets} assets</small>
    </button>`).join("");
}

function renderEngine() {
  const engine = state.queue.engine || {};
  const running = state.queue.jobs?.find(job => job.status === "running");
  const queued = state.queue.jobs?.filter(job => job.status === "queued").length || 0;
  $("#queueCount").textContent = String(queued + (running ? 1 : 0));
  $("#engineDot").className = `engine-dot ${running ? "busy" : engine.online ? "online" : ""}`;
  $("#engineLabel").textContent = running ? (running.kind === "art" ? "Art engine working" : "Video engine working") : engine.online ? "Engines ready" : "Engines idle";
  $("#engineDetail").textContent = running ? running.stage : "Local only · loopback";
  renderQueue();
}

function renderQueue() {
  const jobs = [...(state.queue.jobs || [])].reverse();
  if (!jobs.length) {
    $("#queueList").innerHTML = '<div class="empty-gallery"><b>Queue is clear.</b><p>Add reference or motion takes for an unattended run.</p></div>';
    return;
  }
  $("#queueList").innerHTML = jobs.slice(0, 80).map(job => {
    const elapsed = (job.finished_at || Date.now() / 1000) - (job.started_at || job.created_at || Date.now() / 1000);
    const progress = job.status === "complete" ? 100 : job.status === "running" ? (job.stage.includes("decode") ? 82 : job.stage.includes("sampling") ? 48 : 16) : 0;
    return `<article class="queue-job ${escapeHtml(job.status)}">
      <header><b>${escapeHtml(job.kind === "art" ? "Reference" : "Shot " + (job.shot_id || ""))}</b><em>${escapeHtml(job.status)}</em></header>
      <small>${escapeHtml(job.stage || "waiting")} · seed ${job.seed ?? "random"} · ${Math.max(0, Math.round(elapsed))} sec</small>
      <div class="job-progress"><i style="width:${progress}%"></i></div>
      ${job.error ? `<small class="job-error">${escapeHtml(job.error)}</small>` : ""}
      ${job.status === "queued" ? `<button data-job-action="cancel" data-job-id="${escapeHtml(job.id)}">Cancel queued item</button>` : ""}
      ${["failed", "cancelled"].includes(job.status) ? `<button data-job-action="retry" data-job-id="${escapeHtml(job.id)}">Retry</button>` : ""}
    </article>`;
  }).join("");
}

async function refreshProjects() {
  const result = await api("/api/projects");
  state.projects = result.projects || [];
  renderRecentProjects();
}

async function refreshHealth() {
  const result = await api("/api/health");
  state.queue = result.queue || { jobs: [], engine: {} };
  renderEngine();
  const newlyComplete = state.queue.jobs?.filter(job => job.status === "complete" && !state.seenCompletedJobs.has(job.id)) || [];
  newlyComplete.forEach(job => state.seenCompletedJobs.add(job.id));
  if (state.project && newlyComplete.some(job => job.project_id === state.project.id)) {
    const project = await api(`/api/project/${encodeURIComponent(state.project.id)}`);
    showProject(project);
  }
  if (state.project?.render_state?.status === "running") {
    const project = await api(`/api/project/${encodeURIComponent(state.project.id)}`);
    showProject(project);
  }
}

async function queueAction(action, jobId = null) {
  try {
    state.queue = await api("/api/queue/action", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, job_id: jobId }),
    });
    renderEngine();
  } catch (error) {
    toast(error.message, true);
  }
}

async function queueArt() {
  if (!state.project) return;
  const originalPrompt = $("#assetPrompt").value.trim();
  if (!originalPrompt) return toast("Write the reference prompt first.", true);
  const model = $("#assetModel").value;
  if (!model) return toast("Choose an available prompt model.", true);
  const resolution = $("#assetResolution").value || state.models?.default_image_preset || "landscape-standard";
  const selectedSize = state.models?.image_presets?.find(item => item.id === resolution);
  const width = resolution === "custom" ? Number($("#assetWidth").value) : selectedSize?.width;
  const height = resolution === "custom" ? Number($("#assetHeight").value) : selectedSize?.height;
  const button = $('[data-action="generate-art"]');
  const progress = $("#assetProgress");
  const detail = $("#assetProgressDetail");
  const selected = [...$("#assetModel").options].find(option => option.value === model);
  const modelName = selected?.textContent || model.replace("openclaw/", "");
  const started = Date.now();
  const updateProgress = () => {
    detail.textContent = `${modelName} is preparing the image prompt · ${formatTime((Date.now() - started) / 1000)} elapsed`;
  };
  button.disabled = true;
  button.textContent = "Preparing prompt…";
  progress.hidden = false;
  updateProgress();
  const progressTimer = window.setInterval(updateProgress, 1000);
  try {
    const expanded = await api("/api/image-studio/expand", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model, prompt: originalPrompt }),
    });
    detail.textContent = "Prompt ready · adding the Qwen image job…";
    button.textContent = "Queuing reference…";
    const payload = {
      kind: "art", prompt: expanded.expanded_prompt, negative: $("#assetNegative").value.trim(),
      original_prompt: originalPrompt, expanded_prompt: expanded.expanded_prompt,
      expander_model: expanded.model, prompt_mode: "expanded",
      seed: Number($("#assetSeed").value) || 420251006,
      take_count: Math.max(1, Math.min(8, Number($("#assetVariants").value) || 1)),
      image_preset: resolution,
      width, height,
      asset_kind: $("#assetKind").value, shot_id: $("#assetShot").value || null,
    };
    const result = await api(`/api/project/${encodeURIComponent(state.project.id)}/queue`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
    });
    toast(`Queued ${result.jobs.length} reference ${result.jobs.length === 1 ? "take" : "takes"}.`);
    $("#queueDrawer").classList.add("open");
    await refreshHealth();
  } catch (error) {
    toast(error.message, true);
  } finally {
    window.clearInterval(progressTimer);
    progress.hidden = true;
    button.disabled = false;
    button.textContent = "Generate reference";
  }
}

function randomSeed() {
  const values = new Uint32Array(2);
  window.crypto.getRandomValues(values);
  return (values[0] & 0x1fffff) * 4294967296 + values[1];
}

async function queueShot(shotId, overrides = {}) {
  if (!state.project) return;
  const shot = state.project.shots?.find(item => item.id === shotId);
  const card = $$(".shot-card").find(element => element.dataset.shotId === shotId);
  if (!shot || !card) return;
  const value = name => card.querySelector(`[data-shot-field="${name}"]`)?.value;
  const backendId = overrides.backend || value("backend") || shot.backend || state.project.settings?.video_backend || state.models?.default_video_backend || "wan-2.2-rapid";
  const backend = state.models?.video_backends?.find(item => item.id === backendId);
  const mode = overrides.mode || value("mode") || shot.mode || "t2v";
  if (backend && !backend[mode]) {
    toast(`${backend.name} does not have ${mode.toUpperCase()} enabled yet.`, true);
    return;
  }
  const reference = overrides.reference_asset_id ?? value("reference_asset_id") ?? shot.reference_asset_id ?? null;
  if (mode === "i2v" && !reference) {
    toast("Choose an approved reference before generating an I2V take.", true);
    return;
  }
  const preset = overrides.preset || value("preset") || shot.preset || "compatibility";
  const presetSize = state.models?.presets?.[preset] || [768, 448];
  const payload = {
    kind: "video",
    backend: backendId,
    mode,
    shot_id: shot.id,
    reference_asset_id: mode === "i2v" ? reference : null,
    prompt: overrides.prompt || value("prompt")?.trim() || shot.prompt,
    negative: overrides.negative ?? value("negative")?.trim() ?? shot.negative ?? state.project.bible?.negative_guidance ?? "",
    seed: Number(overrides.seed ?? value("seed") ?? shot.seed ?? 420251006),
    frames: Number(overrides.frames ?? value("frames") ?? shot.frames ?? 49),
    width: Number(overrides.width ?? presetSize[0]),
    height: Number(overrides.height ?? presetSize[1]),
    take_count: Math.max(1, Math.min(12, Number(overrides.take_count ?? value("take_count") ?? 1))),
  };
  for (let index = 0; index < payload.take_count; index += 1) {
    recordSeed(payload.seed + index, index ? `Variant from seed ${payload.seed}` : `Shot ${shot.number} take`);
  }
  shot.mode = payload.mode;
  shot.backend = payload.backend;
  shot.reference_asset_id = payload.reference_asset_id;
  shot.prompt = payload.prompt;
  shot.negative = payload.negative;
  shot.seed = payload.seed;
  shot.frames = payload.frames;
  shot.preset = preset;
  shot.take_count = payload.take_count;
  try {
    await saveProject();
    const result = await api(`/api/project/${encodeURIComponent(state.project.id)}/queue`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
    });
    toast(`Queued ${result.jobs.length} motion ${result.jobs.length === 1 ? "take" : "takes"}.`);
    $("#queueDrawer").classList.add("open");
    await refreshHealth();
  } catch (error) {
    toast(error.message, true);
  }
}

async function regenerateReviewedTake(useNewSeed) {
  const { shot, take } = findTake(state.reviewShotId, state.reviewTakeId);
  if (!shot || !take) return;
  const seed = useNewSeed ? randomSeed() : take.seed;
  closeTakeReview();
  await queueShot(shot.id, {
    backend: take.backend || shot.backend,
    mode: take.mode || shot.mode,
    reference_asset_id: take.reference_asset_id || shot.reference_asset_id,
    prompt: take.prompt || shot.prompt,
    negative: take.negative || shot.negative,
    seed,
    frames: take.frames,
    width: take.width,
    height: take.height,
    take_count: 1,
  });
}

async function openProject(projectId) {
  setSaveState("Opening…");
  try {
    const project = await api(`/api/project/${encodeURIComponent(projectId)}`);
    showProject(project);
    renderRecentProjects();
  } catch (error) {
    setSaveState("Open failed");
    toast(error.message, true);
  }
}

function openImport() {
  $("#importModal").classList.remove("hidden");
  $("#newProjectName").focus();
}

function closeImport() {
  $("#importModal").classList.add("hidden");
}

function chooseSong(file) {
  if (!file) return;
  state.selectedSong = file;
  $("#chosenSong").textContent = `${file.name} · ${(file.size / 1024 / 1024).toFixed(1)} MB`;
  if (!$("#newProjectName").value.trim()) {
    $("#newProjectName").value = file.name.replace(/\.[^.]+$/, "");
  }
}

function uploadSong(file, name) {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", "/api/projects/new");
    request.responseType = "json";
    request.setRequestHeader("Content-Type", file.type || "application/octet-stream");
    request.setRequestHeader("X-Filename", encodeURIComponent(file.name));
    request.setRequestHeader("X-Project-Name", encodeURIComponent(name));
    request.upload.addEventListener("progress", event => {
      if (event.lengthComputable) {
        setSaveState(`Importing ${Math.round(event.loaded / event.total * 100)}%`);
      }
    });
    request.addEventListener("load", () => {
      if (request.status >= 200 && request.status < 300) resolve(request.response);
      else reject(new Error(request.response?.error || `Upload failed (${request.status})`));
    });
    request.addEventListener("error", () => reject(new Error("Song upload connection failed")));
    request.send(file);
  });
}

async function createProjectFromSong() {
  const file = state.selectedSong;
  if (!file) {
    toast("Choose a finished song first.", true);
    return;
  }
  const name = $("#newProjectName").value.trim() || file.name.replace(/\.[^.]+$/, "");
  const progress = $("#importProgress");
  progress.classList.add("busy");
  setSaveState("Importing song…");
  try {
    const created = await uploadSong(file, name);
    setSaveState("Analysing timing…");
    const analysed = await api(`/api/project/${encodeURIComponent(created.id)}/analyse`, { method: "POST" });
    closeImport();
    showProject(analysed);
    await refreshProjects();
    toast(`Analysed ${analysed.shots.length} proposed shots`);
    state.selectedSong = null;
    $("#songFile").value = "";
    $("#chosenSong").textContent = "No song selected";
  } catch (error) {
    setSaveState("Import failed");
    toast(error.message, true);
  } finally {
    progress.classList.remove("busy");
  }
}

async function reanalyseProject() {
  if (!state.project) return;
  setSaveState("Re-analysing…");
  try {
    const project = await api(`/api/project/${encodeURIComponent(state.project.id)}/analyse`, { method: "POST" });
    showProject(project);
    toast(`Rebuilt ${project.shots.length} proposed shots`);
  } catch (error) {
    setSaveState("Analysis failed");
    toast(error.message, true);
  }
}

function populateDirectorModels() {
  const select = $("#directorModel");
  const models = state.models?.director_models || [];
  if (!models.length) {
    select.innerHTML = '<option value="">No AI Director model available</option>';
    return;
  }
  const group = (label, source) => {
    const rows = models.filter(model => model.source === source);
    return rows.length ? `<optgroup label="${label}">${rows.map(model =>
      `<option value="${escapeHtml(model.id)}">${escapeHtml(model.name)}</option>`).join("")}</optgroup>` : "";
  };
  select.innerHTML = group("Local · this workstation", "local") + group("Remote · provider-backed", "remote");
  const ids = models.map(model => model.id);
  const saved = state.project?.director?.model || "";
  const migrated = saved && !saved.startsWith("openclaw/") ? `openclaw/ollama/${saved}` : saved;
  const preferred = models.find(model => model.id === "openclaw/openai/gpt-5.6-sol") ||
    models.find(model => model.source === "remote") || models[0];
  select.value = ids.includes(migrated) ? migrated : preferred.id;
}

function populateAssetModels() {
  const select = $("#assetModel");
  const models = state.models?.director_models || [];
  if (!models.length) {
    select.innerHTML = '<option value="">No prompt model available</option>';
    updateAssetModelNote();
    return;
  }
  const group = (label, source) => {
    const rows = models.filter(model => model.source === source);
    return rows.length ? `<optgroup label="${label}">${rows.map(model =>
      `<option value="${escapeHtml(model.id)}">${escapeHtml(model.name)}</option>`).join("")}</optgroup>` : "";
  };
  select.innerHTML = group("Local · this workstation", "local") + group("Remote · provider-backed", "remote");
  const remembered = localStorage.getItem("cutroomAssetModel");
  const ids = models.map(model => model.id);
  const directorModel = state.project?.director?.model || "";
  const migratedDirector = directorModel && !directorModel.startsWith("openclaw/") ? `openclaw/ollama/${directorModel}` : directorModel;
  const preferred = models.find(model => model.id === "openclaw/openai/gpt-5.6-sol") ||
    models.find(model => model.source === "remote") || models[0];
  select.value = ids.includes(remembered) ? remembered : ids.includes(migratedDirector) ? migratedDirector : preferred.id;
  updateAssetModelNote();
}

function updateAssetModelNote() {
  const select = $("#assetModel");
  const selected = [...select.options].find(option => option.value === select.value);
  const local = selected?.parentElement?.label?.startsWith("Local");
  $("#assetModelNote").textContent = local
    ? "Runs on this workstation, then unloads so Qwen can generate the image locally."
    : "Prepares the image prompt remotely; Qwen generates the image locally.";
}

function populateImagePresets() {
  const select = $("#assetResolution");
  const presets = state.models?.image_presets || [];
  const shapes = ["Landscape", "Square", "Portrait"];
  select.innerHTML = shapes.map(shape => {
    const rows = presets.filter(item => item.shape === shape);
    return `<optgroup label="${shape}">${rows.map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.label)} · ${item.width}×${item.height}</option>`).join("")}</optgroup>`;
  }).join("") + '<optgroup label="Custom"><option value="custom">Custom safe size…</option></optgroup>';
  select.value = state.models?.default_image_preset || "landscape-standard";
  syncImagePresetFields();
}

function syncImagePresetFields() {
  const custom = $("#assetResolution").value === "custom";
  $("#assetCustomSize").hidden = !custom;
}

async function runDirector() {
  if (!state.project) return;
  const model = $("#directorModel").value;
  if (!model) {
    toast("No AI Director model is available.", true);
    return;
  }
  setSaveState("Director is planning…");
  const button = $('[data-action="direct"]');
  const progress = $("#directorProgress");
  const detail = $("#directorProgressDetail");
  const selected = [...$("#directorModel").options].find(option => option.value === model);
  const modelName = selected?.textContent || model.replace("openclaw/", "");
  const started = Date.now();
  const updateProgress = () => {
    detail.textContent = `${modelName} is planning coherent coverage · ${formatTime((Date.now() - started) / 1000)} elapsed`;
  };
  button.disabled = true;
  button.textContent = "Planning coherent coverage…";
  progress.hidden = false;
  updateProgress();
  const progressTimer = window.setInterval(updateProgress, 1000);
  try {
    const project = await api(`/api/project/${encodeURIComponent(state.project.id)}/director`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model,
        brief: $("#directorBrief").value.trim(),
        lyrics: $("#lyrics").value.trim(),
      }),
    });
    showProject(project);
    populateDirectorModels();
    toast("Director proposal applied. Every field remains editable.");
  } catch (error) {
    setSaveState("Director failed");
    toast(error.message, true);
  } finally {
    window.clearInterval(progressTimer);
    progress.hidden = true;
    button.disabled = false;
    button.textContent = "Propose concept & shot language";
  }
}

function bindShell() {
  $("#assetResolution").addEventListener("change", syncImagePresetFields);
  $("#assetModel").addEventListener("change", () => {
    localStorage.setItem("cutroomAssetModel", $("#assetModel").value);
    updateAssetModelNote();
  });
  document.addEventListener("click", event => {
    const timelineControl = event.target.closest("[data-timeline-action]");
    if (timelineControl) {
      timelineAction(timelineControl.dataset.timelineAction);
      return;
    }
    const titleBlock = event.target.closest("[data-title-id]");
    if (titleBlock) {
      state.selectedTitleId = titleBlock.dataset.titleId;
      state.selectedTimelineItemId = null;
      renderTimeline();
      return;
    }
    const timelineBlock = event.target.closest("[data-timeline-id]");
    if (timelineBlock) {
      selectTimelineItem(timelineBlock.dataset.timelineId);
      return;
    }
    const reviewAction = event.target.closest("[data-review-action]");
    if (reviewAction) {
      const action = reviewAction.dataset.reviewAction;
      if (action === "close") closeTakeReview();
      if (action === "keep" || action === "salvage" || action === "bin") setTakeState(action);
      if (action === "same-seed") regenerateReviewedTake(false);
      if (action === "new-seed") regenerateReviewedTake(true);
      if (action === "step-back" || action === "step-forward") {
        const video = $("#reviewVideo");
        if (video) {
          video.pause();
          video.currentTime = Math.max(0, Math.min(video.duration || Infinity, video.currentTime + (action === "step-back" ? -1 : 1) / 24));
        }
      }
      return;
    }
    const takeAction = event.target.closest("[data-take-action]");
    if (takeAction) {
      openTakeReview(takeAction.dataset.shotId, takeAction.dataset.takeId);
      return;
    }
    const shotAction = event.target.closest("[data-shot-action]");
    if (shotAction) {
      queueShot(shotAction.dataset.shotId);
      return;
    }
    const seedAction = event.target.closest("[data-seed-action]");
    if (seedAction) {
      updateSeed(seedAction.dataset.seedAction, Number(seedAction.dataset.seed));
      return;
    }
    const shotFilter = event.target.closest("[data-shot-filter]");
    if (shotFilter) {
      state.shotFilter = shotFilter.dataset.shotFilter;
      renderShots();
      return;
    }
    const jobAction = event.target.closest("[data-job-action]");
    if (jobAction) {
      queueAction(jobAction.dataset.jobAction, jobAction.dataset.jobId);
      return;
    }
    const assetAction = event.target.closest("[data-asset-action]");
    if (assetAction) {
      updateAsset(assetAction.dataset.assetId, assetAction.dataset.assetAction);
      return;
    }
    const assetFilter = event.target.closest("[data-asset-filter]");
    if (assetFilter) {
      state.assetFilter = assetFilter.dataset.assetFilter;
      renderAssets();
      return;
    }
    const tab = event.target.closest("[data-tab]");
    if (tab) {
      setTab(tab.dataset.tab);
      return;
    }

    const project = event.target.closest("[data-project-id]");
    if (project) {
      openProject(project.dataset.projectId);
      return;
    }

    const action = event.target.closest("[data-action]")?.dataset.action;
    if (!action) return;
    if (action === "home") showHome();
    if (action === "new-project") openImport();
    if (action === "close-modal") closeImport();
    if (action === "refresh") refreshProjects().catch(error => toast(error.message, true));
    if (action === "queue") $("#queueDrawer").classList.toggle("open");
    if (action === "create-project") createProjectFromSong();
    if (action === "reanalyze") reanalyseProject();
    if (action === "save") saveProject();
    if (action === "direct") runDirector();
    if (action === "upload-asset") $("#assetFile").click();
    if (action === "generate-art") queueArt();
    if (action === "add-title") addTitle();
    if (action === "render") startFinalRender();
    if (action === "random-seed") addSeedFromForm(true);
    if (action === "random-asset-seed") $("#assetSeed").value = String(randomSeed());
    if (action === "add-seed") addSeedFromForm(false);
    if (action === "pause-queue") queueAction("pause_after_current");
    if (action === "resume-queue") queueAction("resume");
  });

  $("#projectName").addEventListener("input", event => {
    if (!state.project) return;
    state.project.name = event.target.value;
    scheduleSave();
  });
  $("#bibleFields").addEventListener("input", event => {
    const key = event.target.dataset.bibleField;
    if (!key || !state.project) return;
    state.project.bible[key] = event.target.value;
    scheduleSave();
  });
  $("#shotFactory").addEventListener("input", event => {
    const key = event.target.dataset.shotField;
    const card = event.target.closest(".shot-card");
    const shot = state.project?.shots?.find(item => item.id === card?.dataset.shotId);
    if (!key || !shot) return;
    const numeric = ["frames", "seed", "take_count"].includes(key);
    shot[key] = numeric ? Number(event.target.value) : event.target.value;
    scheduleSave();
  });
  $("#shotFactory").addEventListener("change", event => {
    const field = event.target.dataset.shotField;
    if (field === "backend") {
      const card = event.target.closest(".shot-card");
      const shot = state.project?.shots?.find(item => item.id === card?.dataset.shotId);
      const backend = state.models?.video_backends?.find(item => item.id === event.target.value);
      if (shot && backend) {
        shot.backend = backend.id;
        if (!backend[shot.mode]) shot.mode = "t2v";
        const frames = state.models?.valid_frames_by_backend?.[backend.id] || [];
        if (frames.length && !frames.includes(Number(shot.frames))) shot.frames = frames[0];
        state.project.settings ||= {};
        state.project.settings.video_backend = backend.id;
        state.project.settings.fps = backend.fps;
        scheduleSave();
      }
    }
    if (field === "mode" || field === "backend") renderShots();
  });
  $("#seedList").addEventListener("input", event => {
    const seed = Number(event.target.dataset.seedNote);
    const entry = state.project?.seeds?.find(item => Number(item.seed) === seed);
    if (!entry) return;
    entry.note = event.target.value;
    scheduleSave();
  });
  $("#reviewContent").addEventListener("input", event => {
    const key = event.target.dataset.takeField;
    const { take } = findTake(state.reviewShotId, state.reviewTakeId);
    if (!key || !take) return;
    take[key] = event.target.value === "" ? null : Math.max(0, Number(event.target.value) || 0);
    scheduleSave();
  });
  $("#editInspector").addEventListener("change", event => {
    const itemKey = event.target.dataset.itemField;
    const titleKey = event.target.dataset.titleField;
    if (itemKey) {
      const item = state.project?.timeline?.items?.find(entry => entry.id === state.selectedTimelineItemId);
      if (!item) return;
      if (itemKey === "start" || itemKey === "end") {
        updateTimelineBoundary(item, itemKey, Number(event.target.value));
      } else if (itemKey === "reverse") {
        item.reverse = event.target.checked;
      } else if (["trim_in", "speed"].includes(itemKey)) {
        item[itemKey] = Number(event.target.value) || (itemKey === "speed" ? 1 : 0);
      } else {
        item[itemKey] = event.target.value || null;
      }
      renderTimeline();
      scheduleSave();
    }
    if (titleKey) {
      const title = state.project?.timeline?.titles?.find(entry => entry.id === state.selectedTitleId);
      if (!title) return;
      if (["start", "end", "size"].includes(titleKey)) title[titleKey] = Number(event.target.value) || 0;
      else title[titleKey] = event.target.value;
      title.start = Math.max(0, Math.min(timelineDuration() - .04, title.start));
      title.end = Math.max(title.start + .04, Math.min(timelineDuration(), title.end));
      renderTimeline();
      scheduleSave();
    }
  });

  $("#songFile").addEventListener("change", event => chooseSong(event.target.files[0]));
  $("#assetFile").addEventListener("change", event => uploadAsset(event.target.files[0]));
  const dropZone = $("#dropZone");
  dropZone.addEventListener("dragover", event => {
    event.preventDefault();
    dropZone.classList.add("dragging");
  });
  dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragging"));
  dropZone.addEventListener("drop", event => {
    event.preventDefault();
    dropZone.classList.remove("dragging");
    chooseSong(event.dataTransfer.files[0]);
  });

  $("#importModal").addEventListener("click", event => {
    if (event.target === $("#importModal")) closeImport();
  });
  $("#reviewModal").addEventListener("click", event => {
    if (event.target === $("#reviewModal")) closeTakeReview();
  });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape") {
      closeImport();
      closeTakeReview();
      $("#queueDrawer").classList.remove("open");
    }
  });

  const audio = $("#masterAudio");
  $("#playButton").addEventListener("click", () => audio.paused ? audio.play() : audio.pause());
  $("#snapButton").addEventListener("click", () => {
    if (!state.project) return;
    state.project.timeline.snap = !state.project.timeline.snap;
    renderTimeline();
    scheduleSave();
  });
  $("#zoomRange").addEventListener("input", event => {
    if (!state.project) return;
    state.project.timeline.zoom = Number(event.target.value) || 1;
    renderTimeline();
  });
  $("#zoomRange").addEventListener("change", scheduleSave);
  audio.addEventListener("timeupdate", updatePlayhead);
  audio.addEventListener("play", updatePlayhead);
  audio.addEventListener("pause", updatePlayhead);
  $(".wave-wrap").addEventListener("pointerdown", event => seekFromPointer(event, event.currentTarget));
  $("#editTimeline").addEventListener("pointerdown", event => {
    const handle = event.target.closest("[data-boundary]");
    if (handle) {
      const block = handle.closest("[data-timeline-id]");
      const item = state.project?.timeline?.items?.find(entry => entry.id === block?.dataset.timelineId);
      if (!item) return;
      event.preventDefault();
      state.selectedTimelineItemId = item.id;
      state.selectedTitleId = null;
      state.timelineDrag = {
        itemId: item.id, boundary: handle.dataset.boundary,
        startX: event.clientX, start: Number(item.start), end: Number(item.end),
      };
      return;
    }
    if (!event.target.closest(".timeline-block,.title-block")) seekFromPointer(event, event.currentTarget);
  });
  document.addEventListener("pointermove", event => {
    const drag = state.timelineDrag;
    if (!drag || !state.project) return;
    const item = state.project.timeline.items.find(entry => entry.id === drag.itemId);
    if (!item) return;
    const delta = (event.clientX - drag.startX) / $("#editTimeline").getBoundingClientRect().width * timelineDuration();
    updateTimelineBoundary(item, drag.boundary === "left" ? "start" : "end", (drag.boundary === "left" ? drag.start : drag.end) + delta);
    renderTimeline();
  });
  document.addEventListener("pointerup", () => {
    if (!state.timelineDrag) return;
    state.timelineDrag = null;
    scheduleSave();
  });
  window.addEventListener("resize", () => window.requestAnimationFrame(drawWaveforms));
}

async function start() {
  bindShell();
  try {
    const [models] = await Promise.all([
      api("/api/models"),
      refreshProjects(),
      refreshHealth(),
    ]);
    state.models = models;
    populateDirectorModels();
    populateAssetModels();
    populateImagePresets();
    setSaveState("Ready");
  } catch (error) {
    setSaveState("Backend unavailable");
    toast(`Studio backend: ${error.message}`, true);
  }
  state.pollTimer = window.setInterval(() => refreshHealth().catch(() => {}), 3000);
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
}

start();
