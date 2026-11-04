export type TakeState = "keep" | "salvage" | "bin" | "candidate" | string;

export interface Take {
  id: string;
  path: string;
  prompt?: string;
  seed?: number;
  frames?: number;
  width?: number;
  height?: number;
  backend?: string;
  quant?: string;
  fps?: number;
  mode?: string;
  negative?: string;
  reference_asset_id?: string | null;
  state?: TakeState;
  trim_in?: number;
  trim_out?: number | null;
  qc?: {
    status?: string;
    warnings?: string[];
    metrics?: Record<string, number>;
  };
}

export interface Shot {
  id: string;
  number?: number;
  title?: string;
  start: number;
  end: number;
  duration?: number;
  section?: string;
  framing?: string;
  camera?: string;
  mode?: string;
  prompt?: string;
  negative?: string;
  backend?: string;
  preset?: string;
  seed?: number;
  frames?: number;
  take_count?: number;
  reference_prompt?: string;
  reference_asset_id?: string | null;
  selected_take_id?: string | null;
  transition?: string;
  takes: Take[];
}

export interface Asset {
  id: string;
  path: string;
  kind?: string;
  prompt?: string;
  width?: number;
  height?: number;
  state?: string;
  approved?: boolean;
  favourite?: boolean;
  shot_id?: string | null;
  seed?: number | null;
  model?: string;
  backend?: string;
}

export interface SeedEntry {
  seed: number;
  note?: string;
  favourite?: boolean;
  known_good?: boolean;
  bad?: boolean;
  uses?: number;
  last_used_at?: number;
}

export interface TimelineItem {
  id: string;
  shot_id: string;
  take_id?: string | null;
  start: number;
  end: number;
  trim_in?: number;
  speed?: number;
  reverse?: boolean;
  fit?: "cover" | "contain" | string;
  transition?: "cut" | "fade" | string;
}

export interface TimelineTitle {
  id: string;
  text: string;
  start: number;
  end: number;
  size?: number;
  position?: "upper" | "centre" | "lower" | string;
}

export interface SongSection {
  id?: string;
  name: string;
  start: number;
  end: number;
  energy?: number;
}

export interface Project {
  id: string;
  name: string;
  schema: string;
  revision: number;
  updated_at?: number;
  audio: {
    path: string;
    original_filename?: string;
    duration?: number;
    codec?: string;
    sample_rate?: number;
    channels?: number;
  };
  analysis?: {
    audio?: { duration?: number };
    duration?: number;
    beats?: number[];
    waveform?: [number, number][];
    sections?: SongSection[];
    bpm?: number;
    bars?: number[];
  };
  director?: { brief?: string; lyrics?: string; model?: string; [key: string]: unknown };
  bible?: Record<string, string>;
  settings?: { default_preset?: string; video_backend?: string; fps?: number; [key: string]: unknown };
  seeds?: SeedEntry[];
  shots: Shot[];
  assets: Asset[];
  timeline: {
    snap?: boolean;
    zoom?: number;
    items: TimelineItem[];
    titles?: TimelineTitle[];
  };
  renders?: Array<Record<string, unknown>>;
  render_state?: Record<string, unknown> | null;
  [key: string]: unknown;
}

export interface ProjectSummary {
  id: string;
  name: string;
  updated_at: number;
  duration: number;
  shots: number;
  assets: number;
  cover?: string | null;
}

export interface Health {
  ok: boolean;
  version: string;
  projects: number;
  queue?: {
    jobs?: QueueJob[];
    paused?: boolean;
    engine?: { online?: boolean; owned?: boolean; pid?: number | null };
  };
}

export interface QueueJob {
  id: string;
  project_id?: string;
  shot_id?: string;
  kind?: string;
  status?: string;
  stage?: string;
  seed?: number;
  error?: string;
  created_at?: number;
  started_at?: number;
  finished_at?: number;
}

export interface DirectorModel {
  id: string;
  name: string;
  source?: "local" | "remote" | string;
}

export interface VideoBackend {
  id: string;
  name: string;
  ready: boolean;
  t2v: boolean;
  i2v: boolean;
  fps: number;
  model?: string;
  native_audio?: boolean;
}

export interface ImagePreset {
  id: string;
  label: string;
  width: number;
  height: number;
  shape?: string;
}

export interface Models {
  director_models: DirectorModel[];
  video_backends: VideoBackend[];
  default_video_backend: string;
  presets: Record<string, [number, number]>;
  image_presets: ImagePreset[];
  default_image_preset: string;
  valid_frames: number[];
  valid_frames_by_backend: Record<string, number[]>;
}
