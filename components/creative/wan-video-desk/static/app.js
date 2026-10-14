"use strict";

const state = {
  models: [], formats: {}, takes: [], jobs: [], selectedTake: null,
  videoModels: [], reference: null, expanderModel: null, promptMode: "direct",
  busy: false, busyUpload: false,
};

const ui = {
  openclaw: document.querySelector("#openclawStatus"), wan: document.querySelector("#wanStatus"), queue: document.querySelector("#queueStatus"),
  raw: document.querySelector("#rawPrompt"), expanded: document.querySelector("#expandedPrompt"), negative: document.querySelector("#negativePrompt"),
  originalPreview: document.querySelector("#originalPreview"), rawCount: document.querySelector("#rawCount"), expandedCount: document.querySelector("#expandedCount"),
  model: document.querySelector("#modelSelect"), modelNote: document.querySelector("#modelNote"), expand: document.querySelector("#expandBtn"), reexpand: document.querySelector("#reexpandBtn"), rawBtn: document.querySelector("#rawBtn"),
  duration: document.querySelector("#durationInput"), durationRange: document.querySelector("#durationRange"), durationTimecode: document.querySelector("#durationTimecode"),
  steps: document.querySelector("#stepsInput"), stepsRange: document.querySelector("#stepsRange"), stepsReadout: document.querySelector("#stepsReadout"),
  formatReadout: document.querySelector("#formatReadout"), seed: document.querySelector("#seedInput"), randomSeed: document.querySelector("#randomSeedBtn"), batch: document.querySelector("#batchCount"),
  referencePanel: document.querySelector("#referencePanel"), referenceHint: document.querySelector("#referenceHint"), chooseReference: document.querySelector("#chooseReferenceBtn"), referenceDrop: document.querySelector("#referenceDropZone"), referenceInput: document.querySelector("#referenceInput"),
  referenceEmpty: document.querySelector("#referenceEmpty"), referenceImage: document.querySelector("#referenceImage"), referenceMeta: document.querySelector("#referenceMeta"),
  referenceName: document.querySelector("#referenceName"), removeReference: document.querySelector("#removeReferenceBtn"),
  t2vModel: document.querySelector("#t2vModelLabel"), i2vModel: document.querySelector("#i2vModelLabel"),
  generate: document.querySelector("#generateBtn"), generateSummary: document.querySelector("#generateSummary"), action: document.querySelector("#actionStatus"),
  timer: document.querySelector("#generationTimer"), timerLabel: document.querySelector("#generationTimerLabel"), timerNote: document.querySelector("#generationTimerNote"), timerBox: document.querySelector(".generation-clock"),
  jobList: document.querySelector("#jobList"), jobCount: document.querySelector("#jobCount"),
  emptyPreview: document.querySelector("#emptyPreview"), video: document.querySelector("#resultVideo"), previewTimecode: document.querySelector("#previewTimecode"),
  resultMeta: document.querySelector("#resultMeta"), resultActions: document.querySelector("#resultActions"), download: document.querySelector("#downloadBtn"),
  showFolder: document.querySelector("#showFolderBtn"), reuse: document.querySelector("#reuseBtn"), rerun: document.querySelector("#rerunBtn"),
  history: document.querySelector("#history"), historyCount: document.querySelector("#historyCount"), toast: document.querySelector("#toast"),
};

const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g, character => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[character]);

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const type = response.headers.get("content-type") || "";
  const body = type.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) throw new Error(body?.error || body || `${response.status} ${response.statusText}`);
  return body;
}

function pill(element, text, mode = "") {
  element.textContent = text;
  element.className = `status-pill ${mode}`.trim();
}

function notify(message, error = false) {
  ui.toast.textContent = message;
  ui.toast.classList.toggle("error", error);
  ui.toast.classList.add("show");
  clearTimeout(notify.timer);
  notify.timer = setTimeout(() => ui.toast.classList.remove("show"), 3600);
}

function setAction(message, error = false) {
  ui.action.textContent = message;
  ui.action.classList.toggle("error", error);
}

function checked(name) { return document.querySelector(`input[name="${name}"]:checked`)?.value; }
function currentVideoModel() { return checked("videoModel") || "wan2.2-t2v-rapid-aio-v10-nsfw-Q5_K.gguf"; }
function selectedVideoModel() { return state.videoModels.find(item => item.id === currentVideoModel()); }
function currentMode() { return checked("videoMode") === "i2v" ? "i2v" : "t2v"; }
function currentFps() { return [16, 24].includes(Number(checked("fps"))) ? Number(checked("fps")) : 16; }
function currentSteps() { return Math.max(4, Math.min(20, Math.round(Number(ui.steps.value) || 4))); }

function elapsedSeconds(job, now = Date.now() / 1000) {
  if (!job?.started_at) return null;
  return Math.max(0, Number(job.finished_at || now) - Number(job.started_at));
}

function formatElapsed(seconds) {
  if (seconds == null || !Number.isFinite(Number(seconds))) return "—";
  const total = Math.max(0, Math.floor(Number(seconds)));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  return hours ? `${String(hours).padStart(2,"0")}:${String(minutes).padStart(2,"0")}:${String(secs).padStart(2,"0")}` : `${String(minutes).padStart(2,"0")}:${String(secs).padStart(2,"0")}`;
}

function updatePromptViews() {
  const raw = ui.raw.value.trim();
  const expanded = ui.expanded.value.trim();
  ui.originalPreview.textContent = raw || "Your original wording stays visible here.";
  ui.rawCount.textContent = `${raw.length} chars`;
  ui.expandedCount.textContent = `${expanded.length} chars`;
}

function currentFormat() {
  const quality = checked("quality") || "480p";
  const aspect = checked("aspect") || "16:9";
  const size = state.formats?.[quality]?.[aspect] || ([quality, aspect].join("/") === "720p/16:9" ? [1280, 720] : [832, 480]);
  const duration = Math.max(1, Math.min(10, Math.round(Number(ui.duration.value) || 3)));
  const fps = currentFps();
  const steps = currentSteps();
  return {quality, aspect, width: size[0], height: size[1], duration, fps, steps, frames: duration * fps + 1};
}

function updateFormat() {
  const format = currentFormat();
  ui.duration.value = format.duration;
  ui.durationRange.value = format.duration;
  ui.steps.value = format.steps;
  ui.stepsRange.value = format.steps;
  ui.stepsReadout.textContent = format.steps;
  ui.durationTimecode.textContent = `00:${String(format.duration).padStart(2, "0")}`;
  ui.formatReadout.textContent = `${format.width} × ${format.height} · ${format.frames} frames · ${format.fps} fps`;
  ui.generateSummary.textContent = `${currentMode() === "i2v" ? "Image" : "Text"} input · ${format.duration} sec · ${format.fps} fps · ${format.steps} steps`;
}

function setReference(reference) {
  state.reference = reference || null;
  ui.referenceImage.hidden = !state.reference;
  ui.referenceEmpty.hidden = Boolean(state.reference);
  ui.referenceMeta.hidden = !state.reference;
  if (state.reference) {
    ui.referenceImage.src = state.reference.media_url;
    ui.referenceName.textContent = `${state.reference.name} · ${state.reference.width}×${state.reference.height}`;
  } else {
    ui.referenceImage.removeAttribute("src");
    ui.referenceName.textContent = "";
  }
  ui.referenceInput.value = "";
}

function updateVideoModel() {
  const selected = selectedVideoModel();
  const needsReference = currentMode() === "i2v";
  const supportedModes = selected?.modes || (selected?.mode ? [selected.mode] : []);
  const incompatible = Boolean(supportedModes.length && !supportedModes.includes(currentMode()));
  ui.referencePanel.dataset.active = String(needsReference);
  ui.referenceHint.textContent = needsReference
    ? "Required by Image input. The image stays local and anchors the first frame."
    : state.reference
      ? "Reference stored, but Text input will not use it."
      : "Text input does not use a reference image.";
  ui.generate.disabled = state.busy || Boolean(selected && !selected.ready) || incompatible || (needsReference && !state.reference);
  if (selected && !selected.ready) setAction(`${selected.name} is missing a required local model.`, true);
  else if (incompatible) setAction(`${selected.name} cannot run with ${currentMode() === "i2v" ? "Image" : "Text"} input. Pick the matching WAN architecture; both controls remain changeable.`, true);
  else if (needsReference && !state.reference) setAction("Image input needs a reference image.");
  else setAction(`${currentMode() === "i2v" ? "Image" : "Text"} input with ${selected?.name || currentVideoModel()}. Ready to queue.`);
  updateFormat();
}

async function uploadReference(file = ui.referenceInput.files[0]) {
  if (!file || state.busyUpload) return;
  if (!/^image\/(png|jpeg|webp)$/.test(file.type)) return notify("Choose a PNG, JPEG or WebP image.", true);
  if (file.size <= 0 || file.size > 20 * 1024 * 1024) return notify("Reference image must be no larger than 20 MB.", true);
  state.busyUpload = true;
  ui.referenceDrop.classList.remove("dragging");
  setAction("Adding the reference image locally…");
  try {
    const reference = await api("/api/video-studio/reference", {
      method: "POST", headers: {"Content-Type": file.type, "X-Filename": encodeURIComponent(file.name)}, body: file,
    });
    setReference(reference);
    updateVideoModel();
    setAction("Reference ready. Your model selection has not changed.");
  } catch (error) { setAction(error.message, true); notify(error.message, true); }
  finally { state.busyUpload = false; }
}

function randomSeed() {
  const values = new Uint32Array(2);
  crypto.getRandomValues(values);
  ui.seed.value = String((values[0] & 0x1fffff) * 4294967296 + values[1]);
  setAction(`Random seed ${ui.seed.value} selected.`);
}

async function loadModels() {
  try {
    const data = await api("/api/video-studio/models");
    state.models = data.models || [];
    const saved = localStorage.getItem("wanVideoDeskModel");
    const preferred = saved && state.models.some(item => item.id === saved) ? saved :
      (state.models.find(item => item.id === "openclaw/openai/gpt-5.6-sol")?.id || state.models[0]?.id);
    ui.model.innerHTML = state.models.map(item => `<option value="${escapeHtml(item.id)}" ${item.id === preferred ? "selected" : ""}>${escapeHtml(item.name)} · ${item.source}</option>`).join("");
    updateModelNote();
  } catch (error) {
    ui.model.innerHTML = '<option value="">Prompt models unavailable</option>';
    ui.modelNote.textContent = "Prompt expansion is unavailable; direct WAN prompting still works.";
  }
}

function updateModelNote() {
  const model = state.models.find(item => item.id === ui.model.value);
  ui.modelNote.textContent = model ? `${model.name} prepares wording ${model.source === "local" ? "locally" : "through OpenClaw"}; WAN generates the video on this workstation.` : "Use the rough idea directly or select a prompt model.";
}

async function expandPrompt() {
  const prompt = ui.raw.value.trim();
  if (!prompt) return notify("Enter a rough video idea first.", true);
  if (!ui.model.value) return notify("No prompt model is available. Use the rough idea directly.", true);
  ui.expand.disabled = ui.reexpand.disabled = true;
  setAction("Building one continuous motion prompt…");
  try {
    const result = await api("/api/video-studio/expand", {
      method: "POST", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({model: ui.model.value, prompt}),
    });
    ui.expanded.value = result.expanded_prompt;
    state.expanderModel = result.model;
    state.promptMode = "expanded";
    updatePromptViews();
    setAction("Motion prompt ready. Edit it or generate the take.");
  } catch (error) { setAction(error.message, true); notify(error.message, true); }
  finally { ui.expand.disabled = ui.reexpand.disabled = false; }
}

function useRawPrompt() {
  ui.expanded.value = ui.raw.value.trim();
  state.expanderModel = null;
  state.promptMode = "direct";
  updatePromptViews();
  setAction("Using the rough idea unchanged.");
}

async function generate(overrides = {}) {
  if (state.busy || state.busyUpload) return;
  const format = currentFormat();
  const videoModel = String(overrides.video_model ?? currentVideoModel());
  const mode = String(overrides.mode ?? currentMode()) === "i2v" ? "i2v" : "t2v";
  const referenceId = overrides.reference_image_id ?? state.reference?.id ?? null;
  const finalPrompt = String(overrides.final_prompt ?? ui.expanded.value.trim() ?? "").trim() || String(overrides.original_prompt ?? ui.raw.value.trim()).trim();
  const originalPrompt = String(overrides.original_prompt ?? ui.raw.value.trim() ?? finalPrompt).trim();
  if (!finalPrompt) return notify("Enter a video idea before generating.", true);
  const selected = state.videoModels.find(item => item.id === videoModel);
  const supportedModes = selected?.modes || (selected?.mode ? [selected.mode] : []);
  if (supportedModes.length && !supportedModes.includes(mode)) return notify(`${selected.name} cannot run with ${mode === "i2v" ? "Image" : "Text"} input.`, true);
  if (mode === "i2v" && !referenceId) return notify("Image input needs a reference image.", true);
  const payload = {
    video_model: videoModel, mode, reference_image_id: referenceId,
    original_prompt: originalPrompt,
    final_prompt: finalPrompt,
    negative: overrides.negative ?? ui.negative.value.trim(),
    expander_model: overrides.expander_model ?? state.expanderModel,
    prompt_mode: overrides.prompt_mode ?? (ui.expanded.value.trim() ? state.promptMode : "direct"),
    quality: overrides.quality ?? format.quality,
    aspect: overrides.aspect ?? format.aspect,
    duration_seconds: Number(overrides.duration_seconds ?? format.duration),
    fps: Number(overrides.fps ?? format.fps),
    steps: Number(overrides.steps ?? format.steps),
    seed: Number(overrides.seed ?? ui.seed.value),
    batch_count: Number(overrides.batch_count ?? ui.batch.value),
  };
  state.busy = true;
  ui.generate.disabled = true;
  setAction("Adding the WAN video job to the local queue…");
  try {
    const result = await api("/api/video-studio/generate", {
      method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(payload),
    });
    notify(`Queued ${result.jobs.length} video ${result.jobs.length === 1 ? "take" : "takes"}.`);
    setAction("Queued. WAN runs one video at a time.");
    await refreshState();
  } catch (error) { setAction(error.message, true); notify(error.message, true); }
  finally {
    state.busy = false;
    updateVideoModel();
  }
}

function jobLabel(job) {
  if (job.status === "running") return job.stage || "running";
  if (job.status === "queued") return "waiting";
  return job.status;
}

function jobTiming(job) {
  const elapsed = formatElapsed(elapsedSeconds(job));
  if (job.status === "running") return `${elapsed} elapsed`;
  if (job.status === "complete") return `${elapsed} generation`;
  if (job.status === "failed") return `${elapsed} before failure`;
  if (job.status === "cancelled") return "cancelled";
  return `${job.duration_seconds || ((job.frames - 1) / (job.fps || 16)) || 0}s clip`;
}

function updateGenerationTimer() {
  const active = state.jobs.find(job => job.status === "running");
  const queued = state.jobs.filter(job => job.status === "queued").length;
  const latestFinished = [...state.jobs].reverse().find(job => job.started_at && job.finished_at);
  if (active) {
    ui.timerLabel.textContent = "Generating now";
    ui.timerNote.textContent = `${jobLabel(active)} · ${active.fps || 16} fps · ${active.steps || 4} steps`;
    ui.timer.textContent = formatElapsed(elapsedSeconds(active));
    ui.timerBox.classList.add("running");
  } else if (queued) {
    ui.timerLabel.textContent = "Waiting to start";
    ui.timerNote.textContent = `${queued} ${queued === 1 ? "job" : "jobs"} in the local queue.`;
    ui.timer.textContent = "00:00";
    ui.timerBox.classList.remove("running");
  } else if (latestFinished) {
    ui.timerLabel.textContent = latestFinished.status === "complete" ? "Last generation" : "Last attempt";
    ui.timerNote.textContent = `${latestFinished.status} · ${latestFinished.fps || 16} fps · ${latestFinished.steps || 4} steps`;
    ui.timer.textContent = formatElapsed(elapsedSeconds(latestFinished));
    ui.timerBox.classList.remove("running");
  } else {
    ui.timerLabel.textContent = "Generation time";
    ui.timerNote.textContent = "Starts when the WAN job begins.";
    ui.timer.textContent = "—";
    ui.timerBox.classList.remove("running");
  }
  document.querySelectorAll("[data-job-time]").forEach(element => {
    const job = state.jobs.find(item => item.id === element.dataset.jobTime);
    if (job) element.textContent = jobTiming(job);
  });
}

function renderJobs() {
  const jobs = [...state.jobs].reverse().slice(0, 8);
  ui.jobCount.textContent = `${state.jobs.length} job${state.jobs.length === 1 ? "" : "s"}`;
  if (!jobs.length) { ui.jobList.innerHTML = '<p class="empty-small">No video jobs yet.</p>'; return; }
  ui.jobList.innerHTML = jobs.map(job => `<article class="job"><span class="job-state">${escapeHtml(jobLabel(job))}</span><span class="job-prompt">${escapeHtml(job.prompt || "Video take")}</span>${job.status === "queued" ? `<button class="button quiet" data-cancel="${escapeHtml(job.id)}">Cancel</button>` : `<span class="job-time" data-job-time="${escapeHtml(job.id)}">${escapeHtml(jobTiming(job))}</span>`}</article>`).join("");
  ui.jobList.querySelectorAll("[data-cancel]").forEach(button => button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      await api("/api/queue/action", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({action:"cancel", job_id:button.dataset.cancel})});
      await refreshState();
    } catch (error) { notify(error.message, true); button.disabled = false; }
  }));
}

function formatAspect(value) { return value === "mobile" ? "9:16 mobile" : value; }

function selectTake(take, play = false) {
  state.selectedTake = take;
  ui.emptyPreview.hidden = true;
  ui.video.hidden = false;
  ui.previewTimecode.hidden = false;
  if (ui.video.dataset.takeId !== take.id) {
    ui.video.src = take.media_url;
    ui.video.dataset.takeId = take.id;
    ui.video.load();
  }
  if (play) ui.video.play().catch(() => {});
  ui.download.href = take.media_url;
  ui.download.download = `${take.id}.mp4`;
  const rows = [
    ["Prompt", take.original_prompt || take.prompt], ["Final motion prompt", take.expanded_prompt || take.prompt],
    ["Mode", take.mode === "i2v" ? "Image to video" : "Text to video"],
    ["Reference", take.reference_image?.name || (take.mode === "i2v" ? "Stored project reference" : "None")],
    ["Format", `${take.quality || "custom"} · ${formatAspect(take.aspect_ratio || "16:9")} · ${take.width}×${take.height}`],
    ["Running time", `${take.duration_seconds ?? ((take.frames - 1) / (take.fps || 16))} sec · ${take.frames} frames · ${take.fps || 16} fps`],
    ["Generation time", formatElapsed(take.generation_seconds)],
    ["Seed", take.seed], ["Model", `${take.model || "WAN 2.2 Rapid"} · ${take.quant || "Q5_K"}`],
    ["Recipe", `${take.steps || 4} steps · CFG ${take.cfg ?? 1} · ${take.sampler || "euler_ancestral"} · ${take.scheduler || "beta"} · shift ${take.shift || 8}`],
    ["QC", `${String(take.qc?.status || "unscored").toUpperCase()}${take.qc?.warnings?.length ? ` · ${take.qc.warnings.join(" · ")}` : " · no automated warnings"}`],
    ["Output", take.absolute_path],
  ];
  ui.resultMeta.innerHTML = `<dl>${rows.map(([key,value]) => `<div class="meta-row"><dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("")}</dl>`;
  ui.resultMeta.hidden = ui.resultActions.hidden = false;
  updateTimecode();
}

function renderHistory() {
  ui.historyCount.textContent = `${state.takes.length} video${state.takes.length === 1 ? "" : "s"}`;
  if (!state.takes.length) { ui.history.innerHTML = '<p class="empty-small">Generated videos stay on disk and collect here.</p>'; return; }
  ui.history.innerHTML = state.takes.slice(0, 18).map(take => `<article class="history-card" data-id="${escapeHtml(take.id)}"><button class="history-select" data-action="select" type="button"><video src="${escapeHtml(take.media_url)}#t=0.01" muted playsinline preload="metadata"></video><span class="history-copy"><strong>${escapeHtml(take.original_prompt || take.prompt)}</strong><span>${escapeHtml((take.mode || "t2v").toUpperCase())} · ${escapeHtml(take.quality || "custom")} · ${take.duration_seconds}s · ${take.fps || 16} fps · ${take.steps || 4} steps · ${formatElapsed(take.generation_seconds)}</span></span></button><button class="history-delete" data-action="delete" type="button" aria-label="Delete video" title="Delete video">×</button></article>`).join("");
  ui.history.querySelectorAll('[data-action="select"]').forEach(button => button.addEventListener("click", () => {
    const take = state.takes.find(item => item.id === button.closest("[data-id]").dataset.id);
    if (take) selectTake(take, true);
  }));
  ui.history.querySelectorAll('[data-action="delete"]').forEach(button => button.addEventListener("click", async () => {
    const take = state.takes.find(item => item.id === button.closest("[data-id]").dataset.id);
    if (!take || !confirm("Delete this video? It will be moved to Trash.")) return;
    button.disabled = true;
    try {
      await api("/api/video-studio/delete", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({id:take.id})});
      if (state.selectedTake?.id === take.id) state.selectedTake = null;
      notify("Video moved to Trash.");
      await refreshState();
    } catch (error) { notify(error.message, true); button.disabled = false; }
  }));
}

async function refreshState() {
  try {
    const data = await api("/api/video-studio/state");
    const previousNewest = state.takes[0]?.id;
    state.formats = data.formats || state.formats;
    state.videoModels = data.video_models || state.videoModels;
    const t2v = state.videoModels.find(item => item.id === "wan2.2-t2v-rapid-aio-v10-nsfw-Q5_K.gguf");
    const i2v = state.videoModels.find(item => item.id === "wan2.2-i2v-rapid-aio-v10-nsfw-Q5_K.gguf");
    if (t2v) ui.t2vModel.textContent = `${t2v.name}${t2v.ready ? "" : " · unavailable"}`;
    if (i2v) ui.i2vModel.textContent = `${i2v.name}${i2v.ready ? "" : " · unavailable"}`;
    state.takes = data.takes || [];
    state.jobs = data.jobs || [];
    pill(ui.openclaw, data.openclaw.online ? `OpenClaw · ${data.openclaw.models} models` : "OpenClaw · unavailable", data.openclaw.online ? "good" : "bad");
    const active = state.jobs.find(job => job.status === "running");
    const queued = state.jobs.filter(job => job.status === "queued").length;
    pill(ui.wan, active ? `WAN · ${jobLabel(active)}` : (data.queue.engine.online ? "WAN · ready" : "WAN · ready on demand"), active ? "busy" : "good");
    pill(ui.queue, active ? `Queue · 1 running, ${queued} waiting` : queued ? `Queue · ${queued} waiting` : "Queue · idle", active || queued ? "busy" : "good");
    renderJobs(); renderHistory(); updateFormat(); updateGenerationTimer();
    if (state.takes[0] && (!state.selectedTake || state.takes[0].id !== previousNewest)) {
      selectTake(state.takes[0], Boolean(previousNewest) && state.takes[0].id !== previousNewest);
    } else if (!state.takes.length) {
      state.selectedTake = null;
      ui.video.pause(); ui.video.removeAttribute("src"); ui.video.load(); ui.video.hidden = true;
      ui.previewTimecode.hidden = true; ui.emptyPreview.hidden = false;
      ui.resultMeta.hidden = ui.resultActions.hidden = true;
    }
    if (active) setAction(`Generating — ${jobLabel(active)}.`);
    else if (queued) setAction(`${queued} video ${queued === 1 ? "job" : "jobs"} waiting.`);
    else {
      const latest = state.jobs[state.jobs.length - 1];
      if (latest?.status === "failed") setAction(`Failed — ${latest.error || "generation error"}`, true);
      else if (latest?.status === "complete") setAction("Finished — play the take and judge the motion.");
    }
  } catch (error) {
    pill(ui.wan, "WAN · backend unavailable", "bad");
    setAction(error.message, true);
  }
}

function setRadio(name, value) {
  const input = document.querySelector(`input[name="${name}"][value="${CSS.escape(String(value))}"]`);
  if (input) input.checked = true;
}

function reuseTake(take) {
  ui.raw.value = take.original_prompt || take.prompt;
  ui.expanded.value = take.expanded_prompt || take.prompt;
  ui.negative.value = take.negative || "";
  ui.seed.value = take.seed;
  ui.duration.value = take.duration_seconds || Math.max(1, Math.round((take.frames - 1) / (take.fps || 16)));
  ui.steps.value = take.steps || 4;
  setRadio("quality", take.quality || "480p");
  setRadio("aspect", take.aspect_ratio || "16:9");
  setRadio("fps", take.fps || 16);
  const restoredModel = take.model;
  if (restoredModel) setRadio("videoModel", restoredModel);
  setRadio("videoMode", take.mode || "t2v");
  setReference(take.reference_image || null);
  if (take.expander_model && [...ui.model.options].some(option => option.value === take.expander_model)) ui.model.value = take.expander_model;
  state.expanderModel = take.expander_model || null;
  state.promptMode = take.prompt_mode || "direct";
  updatePromptViews(); updateVideoModel();
  scrollTo({top:0, behavior:"smooth"});
  notify("Take settings restored to the desk.");
}

function updateTimecode() {
  const seconds = Math.max(0, ui.video.currentTime || 0);
  const whole = Math.floor(seconds);
  const frames = Math.floor((seconds - whole) * (state.selectedTake?.fps || 16));
  ui.previewTimecode.textContent = `00:00:${String(whole).padStart(2,"0")}:${String(frames).padStart(2,"0")}`;
}

ui.raw.addEventListener("input", updatePromptViews);
ui.expanded.addEventListener("input", () => { state.promptMode = "edited"; updatePromptViews(); });
ui.model.addEventListener("change", () => { localStorage.setItem("wanVideoDeskModel", ui.model.value); updateModelNote(); });
ui.expand.addEventListener("click", expandPrompt); ui.reexpand.addEventListener("click", expandPrompt); ui.rawBtn.addEventListener("click", useRawPrompt);
document.querySelectorAll('input[name="quality"],input[name="aspect"],input[name="fps"]').forEach(input => input.addEventListener("change", updateFormat));
document.querySelectorAll('input[name="videoModel"]').forEach(input => input.addEventListener("change", () => {
  localStorage.setItem("wanVideoDeskVideoModel", currentVideoModel());
  updateVideoModel();
}));
document.querySelectorAll('input[name="videoMode"]').forEach(input => input.addEventListener("change", () => {
  localStorage.setItem("wanVideoDeskMode", currentMode());
  updateVideoModel();
}));
ui.chooseReference.addEventListener("click", () => ui.referenceInput.click());
ui.referenceInput.addEventListener("change", () => uploadReference());
ui.referenceDrop.addEventListener("dragover", event => { event.preventDefault(); if (!state.busyUpload) ui.referenceDrop.classList.add("dragging"); });
ui.referenceDrop.addEventListener("dragleave", () => ui.referenceDrop.classList.remove("dragging"));
ui.referenceDrop.addEventListener("drop", event => {
  event.preventDefault(); ui.referenceDrop.classList.remove("dragging");
  const file = [...event.dataTransfer.files].find(item => /^image\/(png|jpeg|webp)$/.test(item.type));
  if (file) uploadReference(file); else notify("Drop a PNG, JPEG or WebP image.", true);
});
ui.removeReference.addEventListener("click", () => { setReference(null); updateVideoModel(); setAction("Reference removed. Model selection unchanged."); });
ui.duration.addEventListener("input", () => { ui.durationRange.value = ui.duration.value; updateFormat(); });
ui.durationRange.addEventListener("input", () => { ui.duration.value = ui.durationRange.value; updateFormat(); });
ui.steps.addEventListener("input", () => { ui.stepsRange.value = ui.steps.value; updateFormat(); });
ui.stepsRange.addEventListener("input", () => { ui.steps.value = ui.stepsRange.value; updateFormat(); });
ui.randomSeed.addEventListener("click", randomSeed); ui.generate.addEventListener("click", () => generate());
ui.video.addEventListener("timeupdate", updateTimecode);
ui.reuse.addEventListener("click", () => state.selectedTake && reuseTake(state.selectedTake));
ui.rerun.addEventListener("click", () => state.selectedTake && generate({
  original_prompt: state.selectedTake.original_prompt || state.selectedTake.prompt,
  final_prompt: state.selectedTake.expanded_prompt || state.selectedTake.prompt,
  negative: state.selectedTake.negative || "", expander_model: state.selectedTake.expander_model,
  prompt_mode: state.selectedTake.prompt_mode, quality: state.selectedTake.quality || "480p",
  aspect: state.selectedTake.aspect_ratio || "16:9", duration_seconds: state.selectedTake.duration_seconds,
  fps: state.selectedTake.fps || 16, steps: state.selectedTake.steps || 4,
  seed: state.selectedTake.seed, batch_count: 1, video_model: state.selectedTake.model,
  mode: state.selectedTake.mode || "t2v",
  reference_image_id: state.selectedTake.reference_image?.id || null,
}));
ui.showFolder.addEventListener("click", async () => {
  if (!state.selectedTake) return;
  ui.showFolder.disabled = true;
  try {
    const result = await api("/api/video-studio/show-output", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({path:state.selectedTake.absolute_path})});
    notify(result.selected ? "Selected in the system file manager." : "Opened the output folder.");
  } catch (error) { notify(error.message, true); }
  finally { ui.showFolder.disabled = false; }
});

updatePromptViews(); updateFormat();
Promise.all([loadModels(), refreshState()]).then(() => {
  const remembered = localStorage.getItem("wanVideoDeskVideoModel");
  if (remembered && state.videoModels.some(item => item.id === remembered)) setRadio("videoModel", remembered);
  setRadio("videoMode", localStorage.getItem("wanVideoDeskMode") === "i2v" ? "i2v" : "t2v");
  updateVideoModel();
  setInterval(refreshState, 2500); setInterval(updateGenerationTimer, 1000);
});
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/video-studio/sw.js").catch(() => {});
