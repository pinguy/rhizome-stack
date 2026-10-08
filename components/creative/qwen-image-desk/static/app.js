"use strict";

const $ = (selector) => document.querySelector(selector);
const ui = {
  raw: $("#rawPrompt"), negative: $("#negativePrompt"), expanded: $("#expandedPrompt"),
  original: $("#originalPreview"), model: $("#modelSelect"), modelNote: $("#modelNote"),
  expand: $("#expandBtn"), reexpand: $("#reexpandBtn"), rawBtn: $("#rawBtn"),
  preset: $("#presetSelect"), customSize: $("#customSize"), customWidth: $("#customWidth"), customHeight: $("#customHeight"),
  seed: $("#seedInput"), randomSeed: $("#randomSeedBtn"),
  batch: $("#batchSelect"), generate: $("#generateBtn"), action: $("#actionStatus"),
  openclaw: $("#openclawStatus"), qwen: $("#qwenStatus"), queue: $("#queueStatus"),
  jobList: $("#jobList"), queueCount: $("#queueCount"), resultImage: $("#resultImage"),
  fullImage: $("#fullImageLink"), emptyPreview: $("#emptyPreview"), preview: $("#previewStage"),
  resultMeta: $("#resultMeta"), resultActions: $("#resultActions"),
  history: $("#historyGrid"), historyCount: $("#historyCount"),
  showFolder: $("#showFolderBtn"), reuse: $("#reuseBtn"), rerun: $("#rerunBtn"),
  rawCount: $("#rawCount"), expandedCount: $("#expandedCount"), toast: $("#toast"),
  referenceInput: $("#referenceInput"), referencePreview: $("#referencePreview"),
  referenceImage: $("#referenceImage"), referenceName: $("#referenceName"),
  referenceNote: $("#referenceNote"), removeReference: $("#removeReferenceBtn"),
};

const state = { assets: [], jobs: [], presets: [], selectedAsset: null, promptMode: "edited", expanderModel: null, busyExpand: false, reference: null, busyUpload: false };
let toastTimer;

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}

function notify(message, error = false) {
  ui.toast.textContent = message;
  ui.toast.className = `toast show${error ? " error" : ""}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => ui.toast.className = "toast", 3200);
}

function setAction(message, error = false) {
  ui.action.textContent = message;
  ui.action.className = `action-status${error ? " error" : ""}`;
}

function pill(element, text, mode = "") {
  element.textContent = text;
  element.className = `status-pill${mode ? ` ${mode}` : ""}`;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[char]);
}

function updatePromptViews() {
  const raw = ui.raw.value.trim();
  const expanded = ui.expanded.value.trim();
  ui.original.textContent = raw || "Your original wording stays visible here.";
  ui.rawCount.textContent = `${raw.length} chars`;
  ui.expandedCount.textContent = `${expanded.length} chars`;
}

async function loadModels() {
  try {
    const data = await api("/api/image-studio/models");
    const remembered = localStorage.getItem("qwenDeskModel");
    const preferred = data.models.some(item => item.id === remembered) ? remembered :
      (data.models.find(item => item.id === "openclaw/openai/gpt-5.6-sol")?.id || data.models[0]?.id);
    const group = (label, source) => {
      const rows = data.models.filter(item => item.source === source);
      return rows.length ? `<optgroup label="${label}">${rows.map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join("")}</optgroup>` : "";
    };
    ui.model.innerHTML = group("Local · this workstation", "local") + group("Remote · provider-backed", "remote");
    ui.model.value = preferred || "";
    const localCount = data.models.filter(item => item.source === "local").length;
    pill(ui.openclaw, `OpenClaw · ${data.models.length} models · ${localCount} local`, "good");
    updateModelNote();
  } catch (error) {
    ui.model.innerHTML = "<option value=''>OpenClaw unavailable</option>";
    pill(ui.openclaw, "OpenClaw · unavailable", "bad");
    ui.modelNote.textContent = error.message;
  }
}

function updateModelNote() {
  const selected = [...ui.model.options].find(option => option.value === ui.model.value);
  const local = selected?.parentElement?.label?.startsWith("Local");
  ui.modelNote.textContent = local
    ? "Local model on this workstation. It unloads after expansion so Qwen can use the GPU."
    : "Remote OpenClaw model. It only rewrites the prompt; Qwen generates the picture locally.";
}

function renderPresets(presets, defaultPreset) {
  const previous = ui.preset.value;
  const shapes = ["Landscape", "Square", "Portrait"];
  ui.preset.innerHTML = shapes.map(shape => {
    const rows = presets.filter(item => item.shape === shape);
    return `<optgroup label="${shape}">${rows.map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.label)} · ${item.width}×${item.height}</option>`).join("")}</optgroup>`;
  }).join("") + '<optgroup label="Custom"><option value="custom">Custom safe size…</option></optgroup>';
  ui.preset.value = presets.some(item => item.id === previous) || previous === "custom" ? previous : defaultPreset;
  syncCustomSize();
}

function syncCustomSize() {
  ui.customSize.hidden = ui.preset.value !== "custom";
}

async function expandPrompt() {
  if (state.busyUpload) return notify("Wait for the reference upload to finish.", true);
  const prompt = ui.raw.value.trim();
  if (!prompt) return notify("Enter a rough prompt first.", true);
  if (!ui.model.value) return notify("Choose an available OpenClaw model.", true);
  state.busyExpand = true;
  ui.expand.disabled = ui.reexpand.disabled = ui.generate.disabled = true;
  setAction(`Expanding with ${ui.model.value.replace("openclaw/", "")}…`);
  try {
    const result = await api("/api/image-studio/expand", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({model: ui.model.value, prompt, editing: Boolean(state.reference)}),
    });
    ui.expanded.value = result.expanded_prompt;
    state.expanderModel = result.model;
    state.promptMode = "expanded";
    updatePromptViews();
    setAction("Prompt expanded — review or edit it before generating.");
    notify("Prompt expanded.");
  } catch (error) {
    setAction(`Expansion failed — ${error.message}`, true);
    notify(error.message, true);
  } finally {
    state.busyExpand = false;
    ui.expand.disabled = ui.reexpand.disabled = false;
    ui.generate.disabled = false;
  }
}

function useRawPrompt() {
  const prompt = ui.raw.value.trim();
  if (!prompt) return notify("Enter a rough prompt first.", true);
  ui.expanded.value = prompt;
  state.expanderModel = null;
  state.promptMode = "raw";
  updatePromptViews();
  setAction("Using the raw prompt — ready to generate.");
}

function randomSeed() {
  const values = new Uint32Array(2);
  crypto.getRandomValues(values);
  ui.seed.value = String((BigInt(values[0]) << 21n) + BigInt(values[1] & 0x1fffff));
}

function setReference(reference) {
  state.reference = reference;
  ui.referencePreview.hidden = !reference;
  ui.referenceInput.value = "";
  if (reference) {
    ui.referenceImage.src = reference.media_url;
    ui.referenceName.textContent = `${reference.name} · ${reference.width}×${reference.height}`;
  } else {
    ui.referenceImage.removeAttribute("src");
    ui.referenceName.textContent = "";
  }
  ui.referenceNote.textContent = reference
    ? "Describe what to change. Everything else should stay the same. Reference is fitted to the selected frame (centre-cropped if proportions differ). The prompt model receives text only."
    : "No reference — create a new image from your prompt. PNG, JPEG or WebP, up to 20 MB. Images stay on this workstation.";
  ui.generate.firstElementChild.textContent = reference ? "Edit with Qwen" : "Generate with Qwen";
}

async function uploadReference() {
  const file = ui.referenceInput.files[0];
  if (!file) return;
  if (!file.size || file.size > 20 * 1024 * 1024) {
    ui.referenceInput.value = "";
    return notify("Choose an image up to 20 MB.", true);
  }
  state.busyUpload = true;
  ui.referenceInput.disabled = ui.removeReference.disabled = true;
  setAction("Uploading reference locally…");
  try {
    const reference = await api("/api/image-studio/reference", {
      method: "POST", headers: {"Content-Type": file.type || "application/octet-stream", "X-Filename": encodeURIComponent(file.name)}, body: file,
    });
    setReference(reference);
    const scale = Math.min(1, 1024 / Math.max(reference.width, reference.height));
    ui.customWidth.value = Math.max(256, Math.round(reference.width * scale / 64) * 64);
    ui.customHeight.value = Math.max(256, Math.round(reference.height * scale / 64) * 64);
    ui.preset.value = "custom";
    syncCustomSize();
    setAction("Reference ready — enter the changes you want, then Edit with Qwen.");
  } catch (error) {
    ui.referenceInput.value = "";
    setAction(`Reference upload failed — ${error.message}`, true);
    notify(error.message, true);
  } finally {
    state.busyUpload = false;
    ui.referenceInput.disabled = ui.removeReference.disabled = false;
  }
}

async function generate(overrides = {}) {
  if (state.busyUpload) return notify("Wait for the reference upload to finish.", true);
  const finalPrompt = overrides.final_prompt || ui.expanded.value.trim() || ui.raw.value.trim();
  const originalPrompt = overrides.original_prompt || ui.raw.value.trim() || finalPrompt;
  if (!finalPrompt) return notify("Enter or expand a prompt first.", true);
  const payload = {
    original_prompt: originalPrompt,
    final_prompt: finalPrompt,
    negative: overrides.negative ?? ui.negative.value.trim(),
    expander_model: overrides.expander_model ?? state.expanderModel,
    prompt_mode: overrides.prompt_mode || state.promptMode,
    preset: overrides.preset || ui.preset.value,
    custom_width: Number(overrides.custom_width ?? ui.customWidth.value),
    custom_height: Number(overrides.custom_height ?? ui.customHeight.value),
    seed: Number(overrides.seed ?? ui.seed.value),
    batch_count: Number(overrides.batch_count ?? ui.batch.value),
    reference_image_id: Object.hasOwn(overrides, "reference_image_id") ? overrides.reference_image_id : (state.reference?.id || null),
  };
  ui.generate.disabled = true;
  setAction("Submitting to the local Qwen queue…");
  try {
    const result = await api("/api/image-studio/generate", {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload),
    });
    setAction(`${result.jobs.length} image job${result.jobs.length === 1 ? "" : "s"} queued.`);
    notify("Queued for local Qwen generation.");
    await refreshState();
  } catch (error) {
    setAction(`Generation failed — ${error.message}`, true);
    notify(error.message, true);
  } finally {
    ui.generate.disabled = false;
  }
}

function jobLabel(job) {
  if (job.status === "running") return job.stage || "generating";
  if (job.status === "complete") return "finished";
  if (job.status === "failed") return "failed";
  return job.status === "queued" ? "queued" : job.status;
}

function renderJobs() {
  const jobs = [...state.jobs].reverse().slice(0, 6);
  ui.queueCount.textContent = String(state.jobs.length);
  if (!jobs.length) { ui.jobList.innerHTML = '<p class="empty-small">No image jobs yet.</p>'; return; }
  ui.jobList.innerHTML = jobs.map(job => `<div class="job" title="${escapeHtml(job.error || job.prompt)}"><span class="job-state">${escapeHtml(jobLabel(job))}</span><span class="job-prompt">${escapeHtml(job.prompt)}</span><span class="job-seed">${escapeHtml(job.seed)}</span></div>`).join("");
}

function assetPreset(asset) {
  if (asset.image_preset && (asset.image_preset === "custom" || state.presets.some(item => item.id === asset.image_preset))) return asset.image_preset;
  return state.presets.find(item => item.width === asset.width && item.height === asset.height)?.id || "custom";
}

function selectAsset(asset) {
  state.selectedAsset = asset;
  ui.emptyPreview.hidden = true;
  ui.fullImage.hidden = false;
  ui.preview.classList.remove("empty");
  ui.resultImage.src = `${asset.media_url}?v=${encodeURIComponent(asset.created_at)}`;
  ui.fullImage.href = asset.media_url;
  const created = new Date(asset.created_at * 1000).toLocaleString();
  const rows = [
    ["Original", asset.original_prompt || asset.prompt],
    ["Final for Qwen", asset.expanded_prompt || asset.prompt],
    ["Prompt model", asset.expander_model || "Raw/manual prompt"],
    ["Qwen", `${asset.model} · ${asset.quant}`],
    ["Mode", asset.reference_image ? `Reference edit · ${asset.reference_image.name}` : "Text to image"],
    ["Settings", `${asset.width}×${asset.height} · seed ${asset.seed} · ${asset.steps || 25} steps · CFG ${asset.cfg ?? 1}`],
    ["Created", created],
    ["Output", asset.absolute_path],
  ];
  ui.resultMeta.innerHTML = `<dl>${rows.map(([key, value]) => `<div class="meta-row"><dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("")}</dl>`;
  ui.resultMeta.hidden = ui.resultActions.hidden = false;
}

function renderHistory() {
  ui.historyCount.textContent = `${state.assets.length} image${state.assets.length === 1 ? "" : "s"}`;
  if (!state.assets.length) { ui.history.innerHTML = '<p class="empty-small">Generated images stay on disk and will collect here.</p>'; return; }
  ui.history.innerHTML = state.assets.slice(0, 18).map(asset => `<button class="history-card" data-id="${escapeHtml(asset.id)}" type="button"><img src="${escapeHtml(asset.media_url)}" loading="lazy" alt="Qwen result"><span class="history-copy"><strong>${escapeHtml(asset.original_prompt || asset.prompt)}</strong><span>${asset.width}×${asset.height} · seed ${asset.seed}</span></span></button>`).join("");
  ui.history.querySelectorAll("[data-id]").forEach(button => button.addEventListener("click", () => selectAsset(state.assets.find(asset => asset.id === button.dataset.id))));
}

async function refreshState() {
  try {
    const data = await api("/api/image-studio/state");
    const previousNewest = state.assets[0]?.id;
    state.assets = data.assets;
    state.jobs = data.jobs;
    if (JSON.stringify(state.presets) !== JSON.stringify(data.presets)) {
      state.presets = data.presets;
      renderPresets(state.presets, data.default_preset);
    }
    pill(ui.openclaw, data.openclaw.online ? `OpenClaw · ${data.openclaw.models} models · ${data.openclaw.local} local` : "OpenClaw · unavailable", data.openclaw.online ? "good" : "bad");
    const active = state.jobs.find(job => job.status === "running");
    const queued = state.jobs.filter(job => job.status === "queued").length;
    pill(ui.qwen, active ? `Qwen · ${jobLabel(active)}` : (data.queue.engine.online ? "Qwen · ready" : "Qwen · ready on demand"), active ? "busy" : "good");
    pill(ui.queue, active ? `Queue · 1 running, ${queued} waiting` : queued ? `Queue · ${queued} waiting` : "Queue · idle", active || queued ? "busy" : "good");
    renderJobs();
    renderHistory();
    if (state.assets[0] && (!state.selectedAsset || state.assets[0].id !== previousNewest)) selectAsset(state.assets[0]);
    if (active) setAction(`Generating — ${jobLabel(active)}.`);
    else if (queued) setAction(`${queued} image job${queued === 1 ? "" : "s"} queued.`);
    else {
      const failed = [...state.jobs].reverse().find(job => job.status === "failed");
      const latest = state.jobs[state.jobs.length - 1];
      if (latest?.status === "failed" && failed) setAction(`Failed — ${failed.error || "generation error"}`, true);
      else if (latest?.status === "complete") setAction("Finished — inspect the image at full size.");
    }
  } catch (error) {
    pill(ui.qwen, "Qwen · backend unavailable", "bad");
    setAction(error.message, true);
  }
}

function reuseAsset(asset) {
  setReference(asset.reference_image || null);
  ui.raw.value = asset.original_prompt || asset.prompt;
  ui.expanded.value = asset.expanded_prompt || asset.prompt;
  ui.negative.value = asset.negative || "";
  ui.seed.value = asset.seed;
  ui.preset.value = assetPreset(asset);
  ui.customWidth.value = asset.width;
  ui.customHeight.value = asset.height;
  syncCustomSize();
  if (asset.expander_model && [...ui.model.options].some(option => option.value === asset.expander_model)) ui.model.value = asset.expander_model;
  state.expanderModel = asset.expander_model || null;
  state.promptMode = asset.prompt_mode || "edited";
  updatePromptViews();
  window.scrollTo({top: 0, behavior: "smooth"});
  notify("Settings restored to the workbench.");
}

ui.raw.addEventListener("input", updatePromptViews);
ui.referenceInput.addEventListener("change", uploadReference);
ui.removeReference.addEventListener("click", () => { setReference(null); setAction("Reference removed — text-to-image mode."); });
ui.expanded.addEventListener("input", () => { state.promptMode = "edited"; updatePromptViews(); });
ui.model.addEventListener("change", () => { localStorage.setItem("qwenDeskModel", ui.model.value); updateModelNote(); });
ui.preset.addEventListener("change", syncCustomSize);
ui.expand.addEventListener("click", expandPrompt);
ui.reexpand.addEventListener("click", expandPrompt);
ui.rawBtn.addEventListener("click", useRawPrompt);
ui.randomSeed.addEventListener("click", randomSeed);
ui.generate.addEventListener("click", () => generate());
ui.reuse.addEventListener("click", () => state.selectedAsset && reuseAsset(state.selectedAsset));
ui.rerun.addEventListener("click", () => state.selectedAsset && generate({
  original_prompt: state.selectedAsset.original_prompt || state.selectedAsset.prompt,
  final_prompt: state.selectedAsset.expanded_prompt || state.selectedAsset.prompt,
  negative: state.selectedAsset.negative || "", expander_model: state.selectedAsset.expander_model,
  prompt_mode: state.selectedAsset.prompt_mode, preset: assetPreset(state.selectedAsset), seed: state.selectedAsset.seed, batch_count: 1,
  custom_width: state.selectedAsset.width, custom_height: state.selectedAsset.height,
  reference_image_id: state.selectedAsset.reference_image?.id || null,
}));
ui.showFolder.addEventListener("click", async () => {
  if (!state.selectedAsset) return;
  ui.showFolder.disabled = true;
  try {
    const result = await api("/api/image-studio/show-output", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({path: state.selectedAsset.absolute_path}),
    });
    notify(result.selected ? "Selected in the system file manager." : "Opened the output folder.");
  } catch (error) {
    notify(error.message, true);
  } finally {
    ui.showFolder.disabled = false;
  }
});
Promise.all([loadModels(), refreshState()]).then(() => setInterval(refreshState, 2500));
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/image-studio/sw.js").catch(() => {});
