import { useEffect, useMemo, useRef, useState } from "react";
import { api, mediaUrl } from "../api";
import { formatClock, timelineCoverage, validateTimeline } from "../editor";
import type { Asset, Health, Models, Project, Shot, Take } from "../types";

export type Phase = "direct" | "build" | "shoot" | "cut" | "finish";

interface Props {
  phase: Exclude<Phase, "cut">;
  project: Project;
  models: Models | null;
  health: Health | null;
  onEdit: (project: Project) => void;
  onReplace: (project: Project) => void;
  onPersist: () => Promise<Project | null>;
  onRefreshHealth: () => Promise<void>;
  onToast: (message: string, error?: boolean) => void;
  onRender: (preset: "480p" | "720p") => Promise<void>;
  rendering: boolean;
}

const BIBLE_FIELDS: Array<[string, string]> = [
  ["core_concept", "Core concept"], ["overall_look", "Overall look"],
  ["colour_language", "Colour language"], ["lighting_language", "Lighting language"],
  ["character", "Character"], ["wardrobe", "Wardrobe"],
  ["camera_language", "Camera language"], ["recurring_motifs", "Recurring motifs"],
  ["visual_rules", "Visual rules"], ["negative_guidance", "Negative guidance"],
];

function clone(project: Project): Project {
  return structuredClone(project);
}

function randomSeed(): number {
  const values = new Uint32Array(2);
  window.crypto.getRandomValues(values);
  return (values[0] & 0x1fffff) * 4294967296 + values[1];
}

function shotStatus(shot: Shot): "kept" | "review" | "unshot" {
  if (shot.selected_take_id || shot.takes.some((take) => take.state === "keep")) return "kept";
  if (shot.takes.length) return "review";
  return "unshot";
}

function updateShot(project: Project, shotId: string, patch: Partial<Shot>): Project {
  const next = clone(project);
  const shot = next.shots.find((candidate) => candidate.id === shotId);
  if (shot) Object.assign(shot, patch);
  return next;
}

export function ProductionWorkspace(props: Props) {
  if (props.phase === "direct") return <DirectSpace {...props} />;
  if (props.phase === "build") return <BuildSpace {...props} />;
  if (props.phase === "shoot") return <ShootSpace {...props} />;
  return <FinishSpace {...props} />;
}

function DirectSpace({ project, models, onEdit, onReplace, onToast }: Props) {
  const [brief, setBrief] = useState(project.director?.brief ?? "");
  const [lyrics, setLyrics] = useState(project.director?.lyrics ?? "");
  const preferred = models?.director_models.find((model) => model.id === project.director?.model)
    ?? models?.director_models.find((model) => model.id === "openclaw/openai/gpt-5.6-sol")
    ?? models?.director_models[0];
  const [model, setModel] = useState(preferred?.id ?? "");
  const [working, setWorking] = useState<"director" | "analyse" | null>(null);

  useEffect(() => {
    setBrief(project.director?.brief ?? "");
    setLyrics(project.director?.lyrics ?? "");
  }, [project.id, project.revision]);

  async function runDirector() {
    if (!model) return onToast("No Director model is available.", true);
    setWorking("director");
    try {
      const result = await api.director(project.id, { model, brief, lyrics });
      onReplace(result);
      onToast("Director proposal applied. Every field remains editable.");
    } catch (reason) {
      onToast(reason instanceof Error ? reason.message : String(reason), true);
    } finally {
      setWorking(null);
    }
  }

  async function reanalyse() {
    setWorking("analyse");
    try {
      const result = await api.analyse(project.id);
      onReplace(result);
      onToast(`Rebuilt ${result.shots.length} proposed shots.`);
    } catch (reason) {
      onToast(reason instanceof Error ? reason.message : String(reason), true);
    } finally {
      setWorking(null);
    }
  }

  const sections = project.analysis?.sections ?? [];
  return <main className="production-grid" data-phase="direct">
    <aside className="workspace-library">
      <PaneTitle eyebrow="Song map" title={`${sections.length} regions`} />
      <div className="workspace-list section-browser">
        {sections.map((section, index) => <article key={section.id ?? `${section.name}-${index}`}>
          <span>{String(index + 1).padStart(2, "0")}</span>
          <div><strong>{section.name}</strong><small>{formatClock(section.start)} → {formatClock(section.end)}</small></div>
          <i style={{ "--energy": `${Math.round((section.energy ?? 0) * 100)}%` } as React.CSSProperties} />
        </article>)}
      </div>
    </aside>

    <section className="workspace-canvas scroll-canvas">
      <header className="canvas-heading">
        <div><span>DIRECTOR</span><h1>Read the track. Choose the world.</h1></div>
        <button className="quiet-button" disabled={Boolean(working)} onClick={() => void reanalyse()}>{working === "analyse" ? "Analysing…" : "Re-analyse song"}</button>
      </header>
      <div className="metric-strip">
        <Metric value={project.analysis?.bpm ? project.analysis.bpm.toFixed(1) : "—"} label="BPM" />
        <Metric value={formatClock(project.audio.duration ?? project.analysis?.duration ?? 0)} label="Master" />
        <Metric value={String(project.shots.length)} label="Shots" />
        <Metric value={`${timelineCoverage(project).toFixed(0)}%`} label="Coverage" />
      </div>
      <article className="command-card">
        <header><div><span>AI DIRECTOR</span><h2>Creative brief</h2></div>
          <select aria-label="Director model" value={model} onChange={(event) => setModel(event.target.value)}>
            {(models?.director_models ?? []).map((candidate) => <option key={candidate.id} value={candidate.id}>{candidate.source === "local" ? "Local · " : "Remote · "}{candidate.name}</option>)}
          </select>
        </header>
        <textarea aria-label="Creative brief" rows={5} value={brief} onChange={(event) => setBrief(event.target.value)} placeholder="One visual world, recurring forms, a camera language…" />
        <details><summary>Lyrics / spoken text</summary><textarea aria-label="Lyrics" rows={6} value={lyrics} onChange={(event) => setLyrics(event.target.value)} /></details>
        <button className="primary-action" disabled={Boolean(working)} onClick={() => void runDirector()}>{working === "director" ? "Planning coherent coverage…" : "Propose concept and shot language"}</button>
      </article>
      <article className="shot-board">
        <header><div><span>PROPOSED COVERAGE</span><h2>Shot plan</h2></div><b>{project.shots.length} shots</b></header>
        {project.shots.map((shot, index) => <div className="shot-plan-row" key={shot.id}>
          <b>{String(shot.number ?? index + 1).padStart(3, "0")}</b>
          <small>{formatClock(shot.start)}<br />{(shot.end - shot.start).toFixed(2)} sec</small>
          <div><strong>{shot.section ?? "Sequence"}</strong><textarea aria-label={`Prompt for shot ${shot.number ?? index + 1}`} value={shot.prompt ?? ""} onChange={(event) => onEdit(updateShot(project, shot.id, { prompt: event.target.value }))} /></div>
          <span>{shot.framing ?? "shot"}<br /><small>{shot.camera ?? "camera open"}</small></span>
        </div>)}
      </article>
    </section>

    <aside className="workspace-inspector">
      <PaneTitle eyebrow="Continuity" title="Visual bible" />
      <div className="inspector-form">
        {BIBLE_FIELDS.map(([key, label]) => <label key={key}><span>{label}</span><textarea rows={key === "core_concept" ? 4 : 2} value={project.bible?.[key] ?? ""} onChange={(event) => {
          const next = clone(project); next.bible = { ...(next.bible ?? {}), [key]: event.target.value }; onEdit(next);
        }} /></label>)}
      </div>
    </aside>
  </main>;
}

function BuildSpace({ project, models, onReplace, onRefreshHealth, onToast }: Props) {
  const [selectedId, setSelectedId] = useState(project.assets[0]?.id ?? null);
  const [filter, setFilter] = useState<"all" | "approved" | "favourite" | "salvage">("all");
  const [prompt, setPrompt] = useState("");
  const [negative, setNegative] = useState("");
  const [kind, setKind] = useState("character reference");
  const [shotId, setShotId] = useState("");
  const [model, setModel] = useState(models?.director_models.find((item) => item.id === "openclaw/openai/gpt-5.6-sol")?.id ?? models?.director_models[0]?.id ?? "");
  const [preset, setPreset] = useState(models?.default_image_preset ?? "landscape-standard");
  const [seed, setSeed] = useState(420251006);
  const [variants, setVariants] = useState(1);
  const [working, setWorking] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const assets = project.assets.filter((asset) => filter === "all" || (filter === "approved" ? asset.approved || asset.state === "approved" : filter === "favourite" ? asset.favourite : asset.state === "salvage"));
  const selected = project.assets.find((asset) => asset.id === selectedId) ?? assets[0];

  useEffect(() => {
    if (selected && selected.id !== selectedId) setSelectedId(selected.id);
  }, [selected?.id, selectedId]);

  async function mutateAsset(asset: Asset, action: "approve" | "favourite" | "salvage") {
    const body = action === "approve"
      ? { approved: !asset.approved, state: asset.approved ? "candidate" : "approved" }
      : action === "favourite" ? { favourite: !asset.favourite } : { state: "salvage", approved: false };
    try { onReplace(await api.assetState(project.id, asset.id, body)); }
    catch (reason) { onToast(reason instanceof Error ? reason.message : String(reason), true); }
  }

  async function importAsset(file?: File) {
    if (!file) return;
    setWorking(true);
    try {
      const asset = await api.uploadAsset(project.id, file, kind, shotId || undefined);
      onReplace(await api.project(project.id));
      setSelectedId(asset.id);
      onToast("Reference imported and approved.");
    } catch (reason) { onToast(reason instanceof Error ? reason.message : String(reason), true); }
    finally { setWorking(false); if (fileRef.current) fileRef.current.value = ""; }
  }

  async function generateAsset() {
    if (!prompt.trim()) return onToast("Write the reference prompt first.", true);
    if (!model) return onToast("Choose a prompt model.", true);
    const dimensions = models?.image_presets.find((item) => item.id === preset);
    setWorking(true);
    try {
      const expanded = await api.expandImage(model, prompt.trim());
      const result = await api.queue(project.id, {
        kind: "art", prompt: expanded.expanded_prompt, negative: negative.trim(),
        original_prompt: prompt.trim(), expanded_prompt: expanded.expanded_prompt,
        expander_model: expanded.model, prompt_mode: "expanded", seed,
        take_count: variants, image_preset: preset, width: dimensions?.width,
        height: dimensions?.height, asset_kind: kind, shot_id: shotId || null,
      });
      await onRefreshHealth();
      onToast(`Queued ${result.jobs.length} reference ${result.jobs.length === 1 ? "take" : "takes"}.`);
    } catch (reason) { onToast(reason instanceof Error ? reason.message : String(reason), true); }
    finally { setWorking(false); }
  }

  return <main className="production-grid" data-phase="build">
    <aside className="workspace-library">
      <div className="pane-tabs compact-tabs">{(["all", "approved", "favourite", "salvage"] as const).map((value) => <button key={value} className={filter === value ? "active" : ""} onClick={() => setFilter(value)}>{value}</button>)}</div>
      <div className="workspace-list asset-browser">
        {assets.map((asset) => <button key={asset.id} className={selected?.id === asset.id ? "active" : ""} onClick={() => setSelectedId(asset.id)}>
          <img src={mediaUrl(project.id, asset.path) ?? undefined} alt="" />
          <div><strong>{asset.kind ?? "Reference"}</strong><small>{asset.state ?? "candidate"}{asset.favourite ? " · ★" : ""}</small></div>
        </button>)}
        {!assets.length && <EmptyState title="No references here" copy="Import one or generate a visual anchor." />}
      </div>
      <button className="library-add" onClick={() => fileRef.current?.click()}>＋ Import reference</button>
      <input ref={fileRef} hidden type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => void importAsset(event.target.files?.[0])} />
    </aside>

    <section className="workspace-canvas asset-stage">
      {selected ? <>
        <div className="asset-hero"><img src={mediaUrl(project.id, selected.path) ?? undefined} alt={selected.kind ?? "Reference"} /></div>
        <div className="asset-caption"><div><span>{selected.kind ?? "REFERENCE"}</span><h1>{selected.prompt || "Imported reference"}</h1></div><small>{selected.width ?? "?"} × {selected.height ?? "?"}<br />{selected.backend ?? selected.model ?? "file"}</small></div>
        <div className="asset-action-row"><button onClick={() => void mutateAsset(selected, "approve")}>{selected.approved ? "Approved ✓" : "Approve"}</button><button onClick={() => void mutateAsset(selected, "favourite")}>{selected.favourite ? "Favourite ★" : "Favourite"}</button><button className="danger-text" onClick={() => void mutateAsset(selected, "salvage")}>Move to salvage</button></div>
      </> : <EmptyStage eyebrow="ART DEPARTMENT" title="Make anchors, not random pictures." copy="Import a reference or use the maker to establish the production's visual continuity." />}
    </section>

    <aside className="workspace-inspector">
      <PaneTitle eyebrow="Reference maker" title="New visual anchor" />
      <div className="inspector-form">
        <label><span>Use</span><select value={kind} onChange={(event) => setKind(event.target.value)}><option>character reference</option><option>wardrobe</option><option>location</option><option>prop</option><option>shot reference</option><option>first frame</option><option>title art</option><option>texture</option></select></label>
        <label><span>Attach to shot</span><select value={shotId} onChange={(event) => setShotId(event.target.value)}><option value="">Project-wide</option>{project.shots.map((shot) => <option key={shot.id} value={shot.id}>{String(shot.number).padStart(3, "0")} · {shot.section}</option>)}</select></label>
        <label><span>Prompt</span><textarea rows={6} value={prompt} onChange={(event) => setPrompt(event.target.value)} /></label>
        <label><span>Negative guidance</span><textarea rows={3} value={negative} onChange={(event) => setNegative(event.target.value)} /></label>
        <label><span>Prompt model</span><select value={model} onChange={(event) => setModel(event.target.value)}>{(models?.director_models ?? []).map((item) => <option key={item.id} value={item.id}>{item.source === "local" ? "Local · " : "Remote · "}{item.name}</option>)}</select></label>
        <label><span>Resolution</span><select value={preset} onChange={(event) => setPreset(event.target.value)}>{(models?.image_presets ?? []).map((item) => <option key={item.id} value={item.id}>{item.label} · {item.width}×{item.height}</option>)}</select></label>
        <div className="form-pair"><label><span>Seed</span><input type="number" value={seed} onChange={(event) => setSeed(Number(event.target.value))} /></label><button title="Random seed" onClick={() => setSeed(randomSeed())}>↻</button><label><span>Variants</span><input type="number" min="1" max="8" value={variants} onChange={(event) => setVariants(Math.max(1, Math.min(8, Number(event.target.value))))} /></label></div>
        <button className="primary-action" disabled={working} onClick={() => void generateAsset()}>{working ? "Preparing reference…" : "Generate reference"}</button>
      </div>
    </aside>
  </main>;
}

function ShootSpace({ project, models, onEdit, onReplace, onPersist, onRefreshHealth, onToast }: Props) {
  const [selectedShotId, setSelectedShotId] = useState(project.shots[0]?.id ?? "");
  const selectedShot = project.shots.find((shot) => shot.id === selectedShotId) ?? project.shots[0];
  const [selectedTakeId, setSelectedTakeId] = useState(selectedShot?.selected_take_id ?? selectedShot?.takes[0]?.id ?? "");
  const selectedTake = selectedShot?.takes.find((take) => take.id === selectedTakeId) ?? selectedShot?.takes[0];
  const [filter, setFilter] = useState<"all" | "unshot" | "review" | "kept">("all");
  const [working, setWorking] = useState(false);
  const backends = models?.video_backends.filter((backend) => backend.ready) ?? [];
  const backend = backends.find((item) => item.id === selectedShot?.backend) ?? backends[0];
  const mode = selectedShot?.mode ?? "t2v";
  const activeMode: "t2v" | "i2v" = mode === "i2v" && backend?.i2v ? "i2v" : "t2v";
  const frames = models?.valid_frames_by_backend[backend?.id ?? ""] ?? models?.valid_frames ?? [17, 33, 49, 65, 81];
  const references = project.assets.filter((asset) => asset.approved || asset.state === "approved");
  const visibleShots = project.shots.filter((shot) => filter === "all" || shotStatus(shot) === filter);

  useEffect(() => {
    setSelectedTakeId(selectedShot?.selected_take_id ?? selectedShot?.takes[0]?.id ?? "");
  }, [selectedShot?.id, selectedShot?.selected_take_id, selectedShot?.takes.length]);

  function patchShot(patch: Partial<Shot>) {
    if (selectedShot) onEdit(updateShot(project, selectedShot.id, patch));
  }

  async function queueShot() {
    if (!selectedShot || !backend) return onToast("No ready video backend is available.", true);
    if (activeMode === "i2v" && !selectedShot.reference_asset_id) return onToast("Choose an approved reference for Image input.", true);
    setWorking(true);
    try {
      const saved = await onPersist();
      if (!saved) return;
      const preset = selectedShot.preset ?? saved.settings?.default_preset ?? "compatibility";
      const size = models?.presets[preset] ?? [768, 448];
      const result = await api.queue(saved.id, {
        kind: "video", backend: backend.id, mode: activeMode, shot_id: selectedShot.id,
        reference_asset_id: activeMode === "i2v" ? selectedShot.reference_asset_id : null,
        prompt: selectedShot.prompt ?? "", negative: selectedShot.negative ?? saved.bible?.negative_guidance ?? "",
        seed: selectedShot.seed ?? 420251006, frames: selectedShot.frames ?? frames[0],
        width: size[0], height: size[1], take_count: selectedShot.take_count ?? 1,
      });
      await onRefreshHealth();
      onToast(`Queued ${result.jobs.length} motion ${result.jobs.length === 1 ? "take" : "takes"}.`);
    } catch (reason) { onToast(reason instanceof Error ? reason.message : String(reason), true); }
    finally { setWorking(false); }
  }

  async function setTakeState(take: Take, state: "keep" | "salvage" | "bin") {
    setWorking(true);
    try {
      onReplace(await api.takeState(project.id, take.id, state));
      onToast(state === "keep" ? "Take kept and sent to the timeline." : state === "salvage" ? "Take moved to salvage." : "Take binned without deleting its source file.");
    } catch (reason) { onToast(reason instanceof Error ? reason.message : String(reason), true); }
    finally { setWorking(false); }
  }

  return <main className="production-grid" data-phase="shoot">
    <aside className="workspace-library">
      <div className="pane-tabs compact-tabs">{(["all", "unshot", "review", "kept"] as const).map((value) => <button key={value} className={filter === value ? "active" : ""} onClick={() => setFilter(value)}>{value}</button>)}</div>
      <div className="workspace-list shot-browser">{visibleShots.map((shot, index) => <button key={shot.id} className={selectedShot?.id === shot.id ? "active" : ""} onClick={() => setSelectedShotId(shot.id)}>
        <span>{String(shot.number ?? index + 1).padStart(2, "0")}</span><div><strong>{shot.framing ?? shot.section ?? "Shot"}</strong><small>{formatClock(shot.start)} · {shot.takes.length} takes</small></div><i className={shotStatus(shot)} />
      </button>)}</div>
    </aside>

    <section className="workspace-canvas take-stage">
      {selectedTake ? <>
        <div className="take-monitor"><video key={selectedTake.id} src={mediaUrl(project.id, selectedTake.path) ?? undefined} controls playsInline preload="metadata" /></div>
        <div className="take-title"><div><span>SHOT {String(selectedShot?.number ?? 0).padStart(3, "0")} · {(selectedTake.state ?? "candidate").toUpperCase()}</span><h1>{selectedShot?.framing ?? selectedShot?.section ?? "Motion take"}</h1></div><small>{selectedTake.width}×{selectedTake.height} · {selectedTake.frames}f<br />seed {selectedTake.seed ?? "—"}</small></div>
        <div className="take-strip">{selectedShot?.takes.map((take, index) => <button key={take.id} className={selectedTake.id === take.id ? "active" : ""} onClick={() => setSelectedTakeId(take.id)}><video src={mediaUrl(project.id, take.path) ?? undefined} muted preload="metadata" /><span>{index + 1}</span><small>{take.state ?? "candidate"}</small></button>)}</div>
        <div className="take-action-row"><button className="keep" disabled={working} onClick={() => void setTakeState(selectedTake, "keep")}>Keep take</button><button disabled={working} onClick={() => void setTakeState(selectedTake, "salvage")}>Salvage</button><button className="danger-text" disabled={working} onClick={() => void setTakeState(selectedTake, "bin")}>Bin</button></div>
      </> : <EmptyStage eyebrow="CAMERA DEPARTMENT" title="Shoot short. Judge motion." copy="Choose a shot, configure the local backend and generate takes. Always judge the moving clip." />}
    </section>

    <aside className="workspace-inspector">
      <PaneTitle eyebrow="Shot setup" title={selectedShot?.section ?? "No shot"} />
      {selectedShot && <div className="inspector-form">
        <label><span>Prompt</span><textarea rows={6} value={selectedShot.prompt ?? ""} onChange={(event) => patchShot({ prompt: event.target.value })} /></label>
        <label><span>Negative guidance</span><textarea rows={3} value={selectedShot.negative ?? project.bible?.negative_guidance ?? ""} onChange={(event) => patchShot({ negative: event.target.value })} /></label>
        <label><span>Backend</span><select value={backend?.id ?? ""} onChange={(event) => { const next = backends.find((item) => item.id === event.target.value); patchShot({ backend: event.target.value, mode: next?.[mode as "t2v" | "i2v"] ? mode : "t2v", frames: models?.valid_frames_by_backend[event.target.value]?.[0] }); }}>
          {backends.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label><span>Input</span><select value={activeMode} onChange={(event) => patchShot({ mode: event.target.value })}><option value="t2v">Text</option><option value="i2v" disabled={!backend?.i2v}>Image</option></select></label>
        {activeMode === "i2v" && <label><span>Reference</span><select value={selectedShot.reference_asset_id ?? ""} onChange={(event) => patchShot({ reference_asset_id: event.target.value || null })}><option value="">Choose approved reference</option>{references.map((asset) => <option key={asset.id} value={asset.id}>{asset.kind} · {asset.id.slice(-6)}</option>)}</select></label>}
        <label><span>Generated length</span><select value={selectedShot.frames ?? frames[0]} onChange={(event) => patchShot({ frames: Number(event.target.value) })}>{frames.map((value) => <option key={value} value={value}>{value} frames · {((value - 1) / (backend?.fps ?? 24)).toFixed(2)} sec</option>)}</select></label>
        <label><span>Resolution</span><select value={selectedShot.preset ?? "compatibility"} onChange={(event) => patchShot({ preset: event.target.value })}>{Object.entries(models?.presets ?? {}).map(([key, size]) => <option key={key} value={key}>{key} · {size[0]}×{size[1]}</option>)}</select></label>
        <div className="form-pair"><label><span>Seed</span><input type="number" value={selectedShot.seed ?? 420251006} onChange={(event) => patchShot({ seed: Number(event.target.value) })} /></label><button title="Random seed" onClick={() => patchShot({ seed: randomSeed() })}>↻</button><label><span>Takes</span><input type="number" min="1" max="12" value={selectedShot.take_count ?? 1} onChange={(event) => patchShot({ take_count: Math.max(1, Math.min(12, Number(event.target.value))) })} /></label></div>
        <button className="primary-action" disabled={working} onClick={() => void queueShot()}>{working ? "Preparing take…" : `Generate ${activeMode === "i2v" ? "reference-led" : "text-led"} takes`}</button>
      </div>}
    </aside>
  </main>;
}

function FinishSpace({ project, rendering, onRender }: Props) {
  const [preset, setPreset] = useState<"480p" | "720p">("720p");
  const issues = validateTimeline(project);
  const renders = project.renders ?? [];
  const latest = renders[renders.length - 1] as Record<string, unknown> | undefined;
  const latestPath = typeof latest?.path === "string" ? latest.path : null;
  const renderState = project.render_state as { status?: string; error?: string } | null | undefined;
  return <main className="production-grid" data-phase="finish">
    <aside className="workspace-library delivery-library">
      <PaneTitle eyebrow="Delivery" title={issues.length ? `${issues.length} issues` : "Ready"} />
      <div className="delivery-score"><b>{timelineCoverage(project).toFixed(1)}%</b><span>song coverage</span><i><em style={{ width: `${timelineCoverage(project)}%` }} /></i></div>
      <ul className="package-list"><li>Synchronised MP4</li><li>Project manifest and timeline</li><li>Shot list, prompts and seeds</li><li>Reference provenance</li><li>FFmpeg render log</li></ul>
      {issues.map((issue, index) => <div className="issue-row" key={`${issue.kind}-${index}`}>{issue.message}</div>)}
    </aside>
    <section className="workspace-canvas finish-stage">
      <header><span>FINAL ASSEMBLY</span><h1>One master clock.<br />One finished film.</h1><p>Cutroom normalises every kept take, applies the edit, and muxes the untouched source song to exact project duration.</p></header>
      {latestPath ? <video className="render-preview" src={mediaUrl(project.id, latestPath) ?? undefined} controls playsInline preload="metadata" /> : <div className="render-placeholder"><b>NO MASTER YET</b><span>The first completed render will appear here.</span></div>}
      <div className="render-history"><h2>Render history</h2>{renders.length ? [...renders].reverse().map((render, index) => {
        const row = render as Record<string, unknown>;
        return <article key={String(row.id ?? index)}><div><strong>{String(row.preset ?? row.width ?? "Master")}</strong><small>{String(row.status ?? "complete")} · {String(row.path ?? "")}</small></div>{typeof row.path === "string" && <a href={mediaUrl(project.id, row.path) ?? undefined} target="_blank" rel="noreferrer">Open MP4</a>}</article>;
      }) : <p>No delivery masters yet.</p>}</div>
    </section>
    <aside className="workspace-inspector">
      <PaneTitle eyebrow="Export" title="Delivery master" />
      <div className="delivery-options">
        <button className={preset === "720p" ? "active" : ""} onClick={() => setPreset("720p")}><b>1280 × 720</b><span>Quality master · H.264 / AAC</span></button>
        <button className={preset === "480p" ? "active" : ""} onClick={() => setPreset("480p")}><b>854 × 480</b><span>Fast proof · H.264 / AAC</span></button>
        <button className="primary-action" disabled={rendering || issues.length > 0} onClick={() => void onRender(preset)}>{rendering || renderState?.status === "running" ? "Rendering…" : "Render music video"}</button>
        {renderState?.error && <p className="inline-error">{renderState.error}</p>}
      </div>
    </aside>
  </main>;
}

function PaneTitle({ eyebrow, title }: { eyebrow: string; title: string }) {
  return <header className="pane-title"><span>{eyebrow}</span><strong>{title}</strong></header>;
}

function Metric({ value, label }: { value: string; label: string }) {
  return <div><b>{value}</b><span>{label}</span></div>;
}

function EmptyState({ title, copy }: { title: string; copy: string }) {
  return <div className="workspace-empty"><strong>{title}</strong><span>{copy}</span></div>;
}

function EmptyStage({ eyebrow, title, copy }: { eyebrow: string; title: string; copy: string }) {
  return <div className="empty-stage"><span>{eyebrow}</span><h1>{title}</h1><p>{copy}</p></div>;
}
