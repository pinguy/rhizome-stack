import type { Asset, Health, Models, Project, ProjectSummary } from "./types";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, options);
  const type = response.headers.get("content-type") ?? "";
  const body = type.includes("application/json")
    ? await response.json()
    : await response.text();
  if (!response.ok) {
    const message = typeof body === "object" && body && "error" in body
      ? String(body.error)
      : String(body || `${response.status} ${response.statusText}`);
    throw new ApiError(response.status, message);
  }
  return body as T;
}

export const api = {
  health: () => request<Health>("/api/health"),
  models: () => request<Models>("/api/models"),
  projects: async () => (await request<{ projects: ProjectSummary[] }>("/api/projects")).projects,
  project: (id: string) => request<Project>(`/api/project/${encodeURIComponent(id)}`),
  createProject: (name: string, file: File) => request<Project>("/api/projects/new", {
    method: "POST",
    headers: {
      "Content-Type": file.type || "application/octet-stream",
      "X-Filename": encodeURIComponent(file.name),
      "X-Project-Name": encodeURIComponent(name),
    },
    body: file,
  }),
  analyse: (projectId: string) => request<Project>(`/api/project/${encodeURIComponent(projectId)}/analyse`, { method: "POST" }),
  director: (projectId: string, body: { model: string; brief: string; lyrics: string }) => request<Project>(
    `/api/project/${encodeURIComponent(projectId)}/director`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) },
  ),
  save: (project: Project) => request<Project>(`/api/project/${encodeURIComponent(project.id)}/save`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(project),
  }),
  render: (projectId: string, preset: "480p" | "720p") => request<Record<string, unknown>>(
    `/api/project/${encodeURIComponent(projectId)}/render`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ preset }),
    },
  ),
  expandImage: (model: string, prompt: string) => request<{ model: string; expanded_prompt: string }>("/api/image-studio/expand", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model, prompt }),
  }),
  queue: (projectId: string, body: Record<string, unknown>) => request<{ jobs: Array<Record<string, unknown>> }>(
    `/api/project/${encodeURIComponent(projectId)}/queue`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) },
  ),
  queueAction: (action: string, jobId?: string) => request<NonNullable<Health["queue"]>>("/api/queue/action", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, job_id: jobId ?? null }),
  }),
  takeState: (projectId: string, takeId: string, state: string) => request<Project>(
    `/api/project/${encodeURIComponent(projectId)}/take/${encodeURIComponent(takeId)}/state`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ state }) },
  ),
  assetState: (projectId: string, assetId: string, body: Record<string, unknown>) => request<Project>(
    `/api/project/${encodeURIComponent(projectId)}/asset/${encodeURIComponent(assetId)}/state`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) },
  ),
  uploadAsset: (projectId: string, file: File, kind: string, shotId?: string) => request<Asset>(
    `/api/project/${encodeURIComponent(projectId)}/asset/upload`,
    {
      method: "POST",
      headers: {
        "Content-Type": file.type || "application/octet-stream",
        "X-Filename": encodeURIComponent(file.name),
        "X-Asset-Kind": kind,
        "X-Shot-Id": shotId ?? "",
      },
      body: file,
    },
  ),
};

export function mediaUrl(projectId: string, path?: string | null): string | null {
  if (!path) return null;
  return `/media/${encodeURIComponent(projectId)}/${path.split("/").map(encodeURIComponent).join("/")}`;
}
