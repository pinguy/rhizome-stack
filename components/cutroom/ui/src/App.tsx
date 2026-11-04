import { useEffect, useMemo, useReducer, useRef, useState } from "react";
import { api, mediaUrl } from "./api";
import {
  activeItemAt,
  findShot,
  findTake,
  formatClock,
  formatDuration,
  moveBoundary,
  projectDuration,
  sortedItems,
  splitItem,
  timelineCoverage,
  updateItem,
  validateTimeline,
} from "./editor";
import { Timeline } from "./components/Timeline";
import { ProductionWorkspace, type Phase } from "./components/ProductionWorkspace";
import type { Health, Models, Project, ProjectSummary, TimelineItem } from "./types";

type LibraryTab = "scenes" | "media" | "references";

interface DocumentState {
  project: Project | null;
  undo: Project[];
  redo: Project[];
  dirty: boolean;
}

type DocumentAction =
  | { type: "load"; project: Project }
  | { type: "edit"; project: Project }
  | { type: "undo" }
  | { type: "redo" }
  | { type: "saved"; project: Project };

const initialDocument: DocumentState = { project: null, undo: [], redo: [], dirty: false };

function documentReducer(state: DocumentState, action: DocumentAction): DocumentState {
  switch (action.type) {
    case "load":
      return { project: action.project, undo: [], redo: [], dirty: false };
    case "edit":
      if (!state.project) return state;
      return {
        project: action.project,
        undo: [...state.undo.slice(-99), structuredClone(state.project)],
        redo: [],
        dirty: true,
      };
    case "undo": {
      if (!state.project || !state.undo.length) return state;
      const previous = state.undo[state.undo.length - 1];
      return {
        project: previous,
        undo: state.undo.slice(0, -1),
        redo: [structuredClone(state.project), ...state.redo].slice(0, 100),
        dirty: true,
      };
    }
    case "redo": {
      if (!state.project || !state.redo.length) return state;
      const next = state.redo[0];
      return {
        project: next,
        undo: [...state.undo, structuredClone(state.project)].slice(-100),
        redo: state.redo.slice(1),
        dirty: true,
      };
    }
    case "saved": {
      const revision = action.project.revision;
      const refreshRevision = (project: Project) => ({ ...project, revision });
      return {
        project: action.project,
        undo: state.undo.map(refreshRevision),
        redo: state.redo.map(refreshRevision),
        dirty: false,
      };
    }
  }
}

function Icon({ name }: { name: "play" | "pause" | "undo" | "redo" | "split" | "save" | "render" | "folder" }) {
  const paths: Record<string, React.ReactNode> = {
    play: <path d="M8 5v14l11-7z" />,
    pause: <><path d="M7 5h4v14H7z" /><path d="M14 5h4v14h-4z" /></>,
    undo: <path d="M9 8H4v-5M4.5 8.5A8 8 0 1 1 6 17" />,
    redo: <path d="M15 8h5v-5m-.5 5.5A8 8 0 1 0 18 17" />,
    split: <><path d="M4 5l16 14M20 5L4 19" /><circle cx="7" cy="8" r="2" /><circle cx="17" cy="8" r="2" /></>,
    save: <><path d="M5 4h12l2 2v14H5z" /><path d="M8 4v6h8V4M8 20v-6h8v6" /></>,
    render: <><path d="M4 6h16v12H4z" /><path d="M10 9l5 3-5 3z" /></>,
    folder: <path d="M3 6h7l2 2h9v11H3z" />,
  };
  return <svg className="icon" viewBox="0 0 24 24" aria-hidden="true">{paths[name]}</svg>;
}

export function App() {
  const [document, dispatch] = useReducer(documentReducer, initialDocument);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [models, setModels] = useState<Models | null>(null);
  const [phase, setPhase] = useState<Phase>("cut");
  const [newProjectOpen, setNewProjectOpen] = useState(false);
  const [queueOpen, setQueueOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [libraryTab, setLibraryTab] = useState<LibraryTab>("scenes");
  const [selectedItemId, setSelectedItemId] = useState<string | null>(null);
  const [playhead, setPlayhead] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [saving, setSaving] = useState(false);
  const [rendering, setRendering] = useState(false);
  const [renderPreset, setRenderPreset] = useState<"480p" | "720p">("720p");
  const [toast, setToast] = useState<{ text: string; error?: boolean } | null>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const animationRef = useRef<number | null>(null);
  const project = document.project;

  const duration = project ? projectDuration(project) : 0;
  const items = project ? sortedItems(project) : [];
  const selectedItem = project?.timeline.items.find((item) => item.id === selectedItemId) ?? null;
  const activeItem = project ? activeItemAt(project, playhead) ?? null : null;
  const activeTake = project ? findTake(project, activeItem?.take_id) : undefined;
  const activeShot = project ? findShot(project, activeItem?.shot_id) : undefined;
  const issues = useMemo(() => project ? validateTimeline(project) : [], [project]);

  useEffect(() => {
    void bootstrap();
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => void refreshHealth().catch(() => undefined), 3000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    function beforeUnload(event: BeforeUnloadEvent) {
      if (!document.dirty) return;
      event.preventDefault();
      event.returnValue = "";
    }
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [document.dirty]);

  useEffect(() => {
    function keyDown(event: KeyboardEvent) {
      if ((event.target as HTMLElement)?.matches("input, textarea, select")) return;
      if (event.code === "Space") {
        event.preventDefault();
        void togglePlayback();
      } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
        event.preventDefault();
        dispatch({ type: event.shiftKey ? "redo" : "undo" });
      } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "y") {
        event.preventDefault();
        dispatch({ type: "redo" });
      } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        void saveProject();
      } else if (event.key.toLowerCase() === "s" && selectedItemId) {
        event.preventDefault();
        splitSelected();
      }
    }
    window.addEventListener("keydown", keyDown);
    return () => window.removeEventListener("keydown", keyDown);
  });

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 3600);
    return () => window.clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    if (!playing) {
      if (animationRef.current) cancelAnimationFrame(animationRef.current);
      animationRef.current = null;
      return;
    }
    const update = () => {
      const audio = audioRef.current;
      if (audio) setPlayhead(audio.currentTime);
      animationRef.current = requestAnimationFrame(update);
    };
    animationRef.current = requestAnimationFrame(update);
    return () => {
      if (animationRef.current) cancelAnimationFrame(animationRef.current);
    };
  }, [playing]);

  useEffect(() => {
    syncVideo(true);
  }, [activeItem?.id, activeTake?.id]);

  useEffect(() => {
    if (!playing) syncVideo(false);
  }, [playhead]);

  useEffect(() => {
    if (!project || !selectedItemId) return;
    if (project.timeline.items.some((item) => item.id === selectedItemId)) return;
    const replacement = activeItemAt(project, playhead) ?? sortedItems(project)[0];
    setSelectedItemId(replacement?.id ?? null);
  }, [project, selectedItemId, playhead]);

  async function bootstrap() {
    setLoading(true);
    setError(null);
    try {
      const [projectList, healthState, modelState] = await Promise.all([api.projects(), api.health(), api.models()]);
      setProjects(projectList);
      setHealth(healthState);
      setModels(modelState);
      const remembered = localStorage.getItem("cutroom-project") ?? localStorage.getItem("cutroom-next-project");
      const initial = projectList.find((candidate) => candidate.id === remembered)
        ?? projectList.find((candidate) => candidate.id.includes("slice-2a-canary"))
        ?? projectList[0];
      if (initial) await loadProject(initial.id, false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setLoading(false);
    }
  }

  async function refreshProjects() {
    setProjects(await api.projects());
  }

  async function refreshHealth() {
    setHealth(await api.health());
  }

  async function loadProject(id: string, guard = true) {
    if (guard && document.dirty && !window.confirm("Discard the unsaved timeline changes?")) return;
    setError(null);
    setPlaying(false);
    audioRef.current?.pause();
    try {
      const loaded = await api.project(id);
      dispatch({ type: "load", project: loaded });
      setSelectedItemId(sortedItems(loaded)[0]?.id ?? null);
      setPlayhead(0);
      setZoom(Number(loaded.timeline?.zoom ?? 1));
      localStorage.setItem("cutroom-project", id);
    } catch (reason) {
      showToast(reason instanceof Error ? reason.message : String(reason), true);
    }
  }

  function showToast(text: string, isError = false) {
    setToast({ text, error: isError });
  }

  function edit(next: Project) {
    dispatch({ type: "edit", project: next });
  }

  async function saveProject(): Promise<Project | null> {
    if (!document.project || saving) return document.project;
    setSaving(true);
    try {
      const saved = await api.save(document.project);
      dispatch({ type: "saved", project: saved });
      await refreshProjects();
      showToast(`Saved revision ${saved.revision}`);
      return saved;
    } catch (reason) {
      showToast(reason instanceof Error ? reason.message : String(reason), true);
      return null;
    } finally {
      setSaving(false);
    }
  }

  function seek(time: number) {
    const next = Math.max(0, Math.min(duration, time));
    setPlayhead(next);
    if (audioRef.current) audioRef.current.currentTime = next;
    requestAnimationFrame(() => syncVideo(false));
  }

  async function togglePlayback() {
    const audio = audioRef.current;
    if (!audio) return;
    if (playing) {
      audio.pause();
      videoRef.current?.pause();
      setPlaying(false);
      return;
    }
    if (audio.currentTime >= duration - 0.02) seek(0);
    try {
      await audio.play();
      await videoRef.current?.play().catch(() => undefined);
      setPlaying(true);
    } catch (reason) {
      showToast(reason instanceof Error ? reason.message : "Playback failed", true);
    }
  }

  function syncVideo(force: boolean) {
    if (!project || !activeItem || !activeTake || !videoRef.current) return;
    const video = videoRef.current;
    const elapsed = Math.max(0, playhead - activeItem.start);
    const speed = Number(activeItem.speed ?? 1);
    const target = Number(activeItem.trim_in ?? 0) + (
      activeItem.reverse ? Math.max(0, activeItem.end - activeItem.start - elapsed) * speed : elapsed * speed
    );
    video.playbackRate = activeItem.reverse ? 1 : speed;
    if (force || Math.abs(video.currentTime - target) > 0.14) {
      try { video.currentTime = target; } catch { /* metadata is not ready yet */ }
    }
    if (playing && video.paused) void video.play().catch(() => undefined);
  }

  function changeSelected(patch: Partial<TimelineItem>) {
    if (!project || !selectedItem) return;
    edit(updateItem(project, selectedItem.id, patch));
  }

  function splitSelected() {
    if (!project || !selectedItem) return;
    const next = splitItem(project, selectedItem.id, playhead);
    if (next === project) {
      showToast("Put the playhead inside the selected clip before splitting.", true);
      return;
    }
    edit(next);
    const split = sortedItems(next).find((item) => Math.abs(item.start - playhead) < 0.002);
    setSelectedItemId(split?.id ?? null);
    showToast("Clip split at the song clock");
  }

  async function startRender(preset: "480p" | "720p" = renderPreset) {
    if (!project || rendering) return;
    if (issues.length) {
      showToast("Fix the delivery check before rendering.", true);
      return;
    }
    setRendering(true);
    try {
      const saved = document.dirty ? await saveProject() : project;
      if (!saved) return;
      await api.render(saved.id, preset);
      showToast(`${preset} render started in the existing Cutroom renderer`);
      await pollRender(saved.id);
    } catch (reason) {
      showToast(reason instanceof Error ? reason.message : String(reason), true);
    } finally {
      setRendering(false);
    }
  }

  async function pollRender(projectId: string) {
    for (let attempt = 0; attempt < 360; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 2000));
      const current = await api.project(projectId);
      const status = String((current.render_state as { status?: string } | undefined)?.status ?? "");
      if (status === "complete" || status === "failed") {
        dispatch({ type: "saved", project: current });
        showToast(status === "complete" ? "Render complete" : `Render failed: ${String((current.render_state as { error?: string }).error ?? "unknown error")}`, status === "failed");
        return;
      }
    }
    showToast("Render is still running; Cutroom will keep it going in the background.");
  }

  async function createProject(name: string, file: File) {
    try {
      const created = await api.createProject(name || file.name.replace(/\.[^.]+$/, ""), file);
      showToast("Song imported. Analysing the master clock…");
      const analysed = await api.analyse(created.id);
      dispatch({ type: "load", project: analysed });
      setSelectedItemId(sortedItems(analysed)[0]?.id ?? null);
      setPlayhead(0);
      setPhase("direct");
      setNewProjectOpen(false);
      localStorage.setItem("cutroom-project", analysed.id);
      await refreshProjects();
      showToast(`Analysed ${analysed.shots.length} proposed shots.`);
    } catch (reason) {
      showToast(reason instanceof Error ? reason.message : String(reason), true);
      throw reason;
    }
  }

  if (loading) return <div className="boot-screen"><Brand /><div className="boot-line"><i />Loading the edit room…</div></div>;
  if (error && !project) return <div className="boot-screen"><Brand /><div className="fatal"><strong>Cutroom backend is unavailable</strong><span>{error}</span><button onClick={() => void bootstrap()}>Try again</button></div></div>;
  if (!project) return <div className="boot-screen"><Brand /><p>No Cutroom projects were found.</p><button className="primary-action" onClick={() => setNewProjectOpen(true)}>Start with a finished song</button>{newProjectOpen && <NewProjectModal onClose={() => setNewProjectOpen(false)} onCreate={createProject} />}</div>;

  const monitorSource = mediaUrl(project.id, activeTake?.path);
  const audioSource = mediaUrl(project.id, project.audio.path);

  return (
    <div className={`app-shell phase-${phase}`}>
      <header className="titlebar">
        <Brand compact />
        <div className="project-switcher">
          <small>PROJECT</small>
          <select value={project.id} onChange={(event) => void loadProject(event.target.value)} aria-label="Open project">
            {projects.map((candidate) => <option key={candidate.id} value={candidate.id}>{candidate.name}</option>)}
          </select>
          <button className="new-project-button" onClick={() => setNewProjectOpen(true)} aria-label="New project">＋</button>
        </div>
        <nav className="phase-nav" aria-label="Production stages">
          {[
            ["01", "Direct"], ["02", "Build"], ["03", "Shoot"], ["04", "Cut"], ["05", "Finish"],
          ].map(([number, label]) => (
            <button
              className={phase === label.toLowerCase() ? "active" : ""}
              key={label}
              aria-label={label}
              onClick={() => setPhase(label.toLowerCase() as Phase)}
            ><span>{number}</span>{label}</button>
          ))}
        </nav>
        <div className="document-actions">
          <button className={`queue-button ${queueOpen ? "active" : ""}`} onClick={() => setQueueOpen((open) => !open)}>Queue <b>{health?.queue?.jobs?.filter((job) => job.status === "queued" || job.status === "running").length ?? 0}</b></button>
          <button className="icon-button" disabled={!document.undo.length} onClick={() => dispatch({ type: "undo" })} title="Undo (Ctrl+Z)"><Icon name="undo" /></button>
          <button className="icon-button" disabled={!document.redo.length} onClick={() => dispatch({ type: "redo" })} title="Redo (Ctrl+Y)"><Icon name="redo" /></button>
          <button className={`save-button ${document.dirty ? "dirty" : ""}`} disabled={saving || !document.dirty} onClick={() => void saveProject()}><Icon name="save" />{saving ? "Saving…" : document.dirty ? "Save changes" : `Saved r${project.revision}`}</button>
        </div>
      </header>

      {phase === "cut" ? <>
      <main className="editor-grid">
        <aside className="library-pane">
          <div className="pane-tabs" role="tablist">
            {(["scenes", "media", "references"] as LibraryTab[]).map((tab) => <button role="tab" aria-selected={libraryTab === tab} className={libraryTab === tab ? "active" : ""} key={tab} onClick={() => setLibraryTab(tab)}>{tab}</button>)}
          </div>
          <Library project={project} tab={libraryTab} selectedItemId={selectedItemId} onSelectItem={(item) => { setSelectedItemId(item.id); seek(item.start); }} />
        </aside>

        <section className="programme-pane">
          <div className={`programme-monitor ${activeItem?.fit === "contain" ? "contain" : "cover"}`}>
            {monitorSource ? (
              <video
                ref={videoRef}
                key={monitorSource}
                src={monitorSource}
                muted
                playsInline
                preload="auto"
                onLoadedMetadata={() => syncVideo(true)}
                onError={() => showToast("The selected take could not be decoded for preview.", true)}
              />
            ) : <div className="missing-picture"><span>NO PICTURE</span><strong>{activeShot?.framing ?? "Uncovered song time"}</strong><small>Add or select a kept take.</small></div>}
            <div className="monitor-shade" />
            <div className="monitor-label"><span>{activeShot?.section ?? "SONG"}</span><strong>{activeShot?.framing ?? "No active shot"}</strong></div>
            <div className="safe-frame" />
          </div>
          <div className="transport">
            <button className="transport-play" onClick={() => void togglePlayback()} aria-label={playing ? "Pause" : "Play"}><Icon name={playing ? "pause" : "play"} /></button>
            <button onClick={() => seek(Math.max(0, playhead - 1))} aria-label="Back one second">−1s</button>
            <strong>{formatClock(playhead)}</strong>
            <span>/ {formatClock(duration)}</span>
            <button onClick={() => seek(Math.min(duration, playhead + 1))} aria-label="Forward one second">+1s</button>
            <div className="transport-spacer" />
            <span className={`engine-state ${health?.queue?.engine?.online ? "online" : ""}`}><i />{health?.queue?.engine?.online ? "Generator occupied" : "Generators idle"}</span>
            <button className="split-button" disabled={!selectedItem} onClick={splitSelected}><Icon name="split" />Split <kbd>S</kbd></button>
          </div>
          <audio ref={audioRef} src={audioSource ?? undefined} preload="auto" onEnded={() => setPlaying(false)} />
        </section>

        <aside className="inspector-pane">
          <Inspector
            project={project}
            selectedItem={selectedItem}
            issues={issues}
            onChange={changeSelected}
            onSelectIssue={(id) => {
              const item = project.timeline.items.find((candidate) => candidate.id === id);
              if (item) { setSelectedItemId(item.id); seek(item.start); }
            }}
          />
        </aside>
      </main>

      <Timeline
        project={project}
        playhead={playhead}
        selectedItemId={selectedItemId}
        zoom={zoom}
        onZoom={setZoom}
        onSeek={seek}
        onSelect={setSelectedItemId}
        onMoveBoundary={(itemId, time) => edit(moveBoundary(project, itemId, time))}
      />

      <footer className="delivery-bar">
        <div className="coverage-meter"><span>SONG COVERAGE</span><strong>{timelineCoverage(project).toFixed(1)}%</strong><i><b style={{ width: `${timelineCoverage(project)}%` }} /></i></div>
        <div className="delivery-status"><i className={issues.length ? "warn" : "pass"} />{issues.length ? `${issues.length} delivery issue${issues.length === 1 ? "" : "s"}` : "Timeline ready to render"}</div>
        <div className="render-controls">
          <select value={renderPreset} onChange={(event) => setRenderPreset(event.target.value as "480p" | "720p")} aria-label="Render resolution"><option value="720p">1280 × 720 master</option><option value="480p">854 × 480 proof</option></select>
          <button disabled={rendering || issues.length > 0} onClick={() => void startRender()}><Icon name="render" />{rendering ? "Rendering…" : "Render video"}</button>
        </div>
      </footer>
      </> : <ProductionWorkspace
        phase={phase}
        project={project}
        models={models}
        health={health}
        onEdit={edit}
        onReplace={(next) => dispatch({ type: "load", project: next })}
        onPersist={saveProject}
        onRefreshHealth={refreshHealth}
        onToast={showToast}
        onRender={startRender}
        rendering={rendering}
      />}

      <QueueDrawer health={health} open={queueOpen} onClose={() => setQueueOpen(false)} onAction={async (action, jobId) => {
        try { setHealth({ ...(health ?? { ok: true, version: "", projects: projects.length }), queue: await api.queueAction(action, jobId) }); }
        catch (reason) { showToast(reason instanceof Error ? reason.message : String(reason), true); }
      }} />

      {newProjectOpen && <NewProjectModal onClose={() => setNewProjectOpen(false)} onCreate={createProject} />}

      {toast && <div className={`toast ${toast.error ? "error" : ""}`}>{toast.text}</div>}
    </div>
  );
}

function Brand({ compact = false }: { compact?: boolean }) {
  return <div className={`brand ${compact ? "compact" : ""}`}><i><b /><b /><b /></i><div><strong>CUTROOM</strong><span>LOCAL PRODUCTION STUDIO</span></div></div>;
}

function Library({ project, tab, selectedItemId, onSelectItem }: { project: Project; tab: LibraryTab; selectedItemId: string | null; onSelectItem: (item: TimelineItem) => void }) {
  const items = sortedItems(project);
  if (tab === "scenes") {
    return <div className="scene-list">{project.shots.map((shot, index) => {
      const item = items.find((candidate) => candidate.shot_id === shot.id);
      const take = findTake(project, item?.take_id ?? shot.selected_take_id);
      return <button className={item?.id === selectedItemId ? "active" : ""} key={shot.id} onClick={() => item && onSelectItem(item)}>
        <span className="scene-number">{String(shot.number ?? index + 1).padStart(2, "0")}</span>
        <div><strong>{shot.framing || shot.title || `Shot ${index + 1}`}</strong><small>{formatDuration(shot.end - shot.start)} · {shot.section ?? "unmapped"}</small></div>
        <i className={take?.state === "keep" ? "kept" : take ? "candidate" : "missing"} title={take ? take.state ?? "candidate" : "No take"} />
      </button>;
    })}</div>;
  }
  if (tab === "references") {
    return <div className="asset-grid">{project.assets.length ? project.assets.map((asset) => {
      const source = mediaUrl(project.id, asset.path);
      return <article key={asset.id}>{source && <img src={source} alt="" loading="lazy" />}<div><strong>{asset.kind ?? "Reference"}</strong><small>{asset.width && asset.height ? `${asset.width}×${asset.height}` : asset.state ?? "Saved"}</small></div></article>;
    }) : <EmptyLibrary title="No references" copy="Build references in Cutroom, then they appear here." />}</div>;
  }
  const takes = project.shots.flatMap((shot) => shot.takes.map((take) => ({ take, shot })));
  return <div className="media-list">{takes.length ? takes.map(({ take, shot }) => <article key={take.id}>
    <div className="media-preview"><video src={mediaUrl(project.id, take.path) ?? undefined} muted preload="metadata" /></div>
    <div><strong>{shot.framing ?? `Shot ${shot.number ?? ""}`}</strong><small>{take.backend ?? "Generated"} · seed {take.seed ?? "—"}</small></div>
    <span className={`take-state ${take.state ?? "candidate"}`}>{take.state ?? "candidate"}</span>
  </article>) : <EmptyLibrary title="No generated media" copy="Generate takes in Shoot, then cut them here." />}</div>;
}

function EmptyLibrary({ title, copy }: { title: string; copy: string }) {
  return <div className="empty-library"><Icon name="folder" /><strong>{title}</strong><span>{copy}</span></div>;
}

function QueueDrawer({ health, open, onClose, onAction }: {
  health: Health | null;
  open: boolean;
  onClose: () => void;
  onAction: (action: string, jobId?: string) => Promise<void>;
}) {
  const jobs = [...(health?.queue?.jobs ?? [])].reverse();
  return <aside className={`queue-drawer ${open ? "open" : ""}`} aria-hidden={!open}>
    <header><div><span>UNATTENDED RUN</span><h2>Generation queue</h2></div><button onClick={onClose} aria-label="Close queue">×</button></header>
    <div className="queue-controls"><button onClick={() => void onAction("pause_after_current")}>Pause after current</button><button onClick={() => void onAction("resume")}>Resume</button></div>
    <div className="queue-list">{jobs.length ? jobs.map((job) => <article key={job.id} className={job.status ?? "queued"}>
      <header><b>{job.kind === "art" ? "Reference" : `Shot ${job.shot_id ?? ""}`}</b><em>{job.status ?? "queued"}</em></header>
      <small>{job.stage ?? "waiting"} · seed {job.seed ?? "random"}</small>
      <i><b style={{ width: job.status === "complete" ? "100%" : job.status === "running" ? "48%" : "0%" }} /></i>
      {job.error && <p>{job.error}</p>}
      {job.status === "queued" && <button onClick={() => void onAction("cancel", job.id)}>Cancel queued item</button>}
      {(job.status === "failed" || job.status === "cancelled") && <button onClick={() => void onAction("retry", job.id)}>Retry</button>}
    </article>) : <div className="queue-empty"><strong>Queue is clear</strong><span>Generated references and motion takes will appear here.</span></div>}</div>
  </aside>;
}

function NewProjectModal({ onClose, onCreate }: { onClose: () => void; onCreate: (name: string, file: File) => Promise<void> }) {
  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [working, setWorking] = useState(false);

  function choose(next?: File) {
    if (!next) return;
    setFile(next);
    if (!name) setName(next.name.replace(/\.[^.]+$/, ""));
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!file || working) return;
    setWorking(true);
    try { await onCreate(name.trim(), file); }
    finally { setWorking(false); }
  }

  return <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="New Cutroom project" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <form className="project-modal" onSubmit={(event) => void submit(event)}>
      <button type="button" className="modal-close" onClick={onClose}>×</button>
      <span>NEW PRODUCTION</span><h1>Start with the master song.</h1>
      <p>The original stays untouched. Cutroom copies it into a recoverable project and builds the first timing map.</p>
      <label>Project name<input value={name} onChange={(event) => setName(event.target.value)} placeholder="Untitled music video" /></label>
      <label className="song-drop" onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); choose(event.dataTransfer.files[0]); }}>
        <input type="file" accept="audio/*,.mp3,.wav,.flac,.m4a,.ogg" onChange={(event) => choose(event.target.files?.[0])} />
        <b>Drop MP3, WAV or audio here</b><span>or click to choose a file</span><em>{file ? `${file.name} · ${(file.size / 1024 / 1024).toFixed(1)} MB` : "No song selected"}</em>
      </label>
      <button className="primary-action" disabled={!file || working}>{working ? "Importing and analysing…" : "Import and analyse song"}</button>
    </form>
  </div>;
}

function Inspector({ project, selectedItem, issues, onChange, onSelectIssue }: {
  project: Project;
  selectedItem: TimelineItem | null;
  issues: ReturnType<typeof validateTimeline>;
  onChange: (patch: Partial<TimelineItem>) => void;
  onSelectIssue: (id: string) => void;
}) {
  if (!selectedItem) {
    return <div className="inspector-empty"><span>EDIT INSPECTOR</span><strong>Select a clip</strong><p>Choose a shot on the timeline to change its take, timing and presentation.</p></div>;
  }
  const shot = findShot(project, selectedItem.shot_id);
  const take = findTake(project, selectedItem.take_id);
  const clipIssues = issues.filter((issue) => issue.itemId === selectedItem.id);
  return <>
    <header className="inspector-header"><span>CLIP INSPECTOR</span><strong>{shot?.framing ?? "Timeline clip"}</strong><small>{formatClock(selectedItem.start)} → {formatClock(selectedItem.end)}</small></header>
    <div className="inspector-scroll">
      <fieldset>
        <legend>Source</legend>
        <label><span>Take</span><select value={selectedItem.take_id ?? ""} onChange={(event) => onChange({ take_id: event.target.value || null })}><option value="">No picture</option>{shot?.takes.map((candidate) => <option key={candidate.id} value={candidate.id}>{candidate.state?.toUpperCase() ?? "TAKE"} · {candidate.backend ?? "Generated"} · {candidate.seed ?? "no seed"}</option>)}</select></label>
        <label><span>Trim in</span><div className="unit-input"><input type="number" min="0" step="0.042" value={Number(selectedItem.trim_in ?? 0).toFixed(3)} onChange={(event) => onChange({ trim_in: Math.max(0, Number(event.target.value)) })} /><b>s</b></div></label>
        <label><span>Speed</span><div className="slider-input"><input type="range" min="0.1" max="4" step="0.01" value={selectedItem.speed ?? 1} onChange={(event) => onChange({ speed: Number(event.target.value) })} /><output>{Math.round(Number(selectedItem.speed ?? 1) * 100)}%</output></div></label>
        <label className="switch-row"><span>Reverse source</span><input type="checkbox" checked={Boolean(selectedItem.reverse)} onChange={(event) => onChange({ reverse: event.target.checked })} /></label>
      </fieldset>
      <fieldset>
        <legend>Picture</legend>
        <div className="segmented"><button className={(selectedItem.fit ?? "cover") === "cover" ? "active" : ""} onClick={() => onChange({ fit: "cover" })}>Fill frame</button><button className={selectedItem.fit === "contain" ? "active" : ""} onClick={() => onChange({ fit: "contain" })}>Show all</button></div>
        <label><span>Transition</span><select value={selectedItem.transition ?? "cut"} onChange={(event) => onChange({ transition: event.target.value })}><option value="cut">Hard cut</option><option value="fade">Fade through black</option></select></label>
      </fieldset>
      <fieldset>
        <legend>Provenance</legend>
        <dl className="provenance"><dt>Backend</dt><dd>{take?.backend ?? "No take"}</dd><dt>Seed</dt><dd>{take?.seed ?? "—"}</dd><dt>Source</dt><dd>{take?.width && take?.height ? `${take.width} × ${take.height}` : "—"}</dd><dt>QC</dt><dd className={take?.qc?.status === "pass" ? "good" : ""}>{take?.qc?.status ?? "Not checked"}</dd></dl>
      </fieldset>
      <fieldset className="delivery-check">
        <legend>Delivery check</legend>
        {!issues.length && <div className="check-pass"><i />Full song covered. Sources resolve.</div>}
        {issues.map((issue, index) => <button key={`${issue.kind}-${index}`} className={clipIssues.includes(issue) ? "current" : ""} onClick={() => issue.itemId && onSelectIssue(issue.itemId)}><i />{issue.message}</button>)}
      </fieldset>
    </div>
  </>;
}
