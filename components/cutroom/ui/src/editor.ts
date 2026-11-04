import type { Project, Shot, Take, TimelineItem } from "./types";

export const FPS = 24;

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export function projectDuration(project: Project): number {
  return Number(
    project.analysis?.audio?.duration
      ?? project.analysis?.duration
      ?? project.audio?.duration
      ?? 0,
  );
}

export function sortedItems(project: Project): TimelineItem[] {
  return [...(project.timeline?.items ?? [])].sort((a, b) => a.start - b.start);
}

export function findShot(project: Project, shotId?: string | null): Shot | undefined {
  return project.shots.find((shot) => shot.id === shotId);
}

export function findTake(project: Project, takeId?: string | null): Take | undefined {
  if (!takeId) return undefined;
  for (const shot of project.shots) {
    const take = shot.takes?.find((candidate) => candidate.id === takeId);
    if (take) return take;
  }
  return undefined;
}

export function activeItemAt(project: Project, time: number): TimelineItem | undefined {
  const items = sortedItems(project);
  return items.find((item, index) => time >= item.start && (
    time < item.end || (index === items.length - 1 && time <= item.end)
  ));
}

export function formatClock(seconds: number): string {
  const safe = Math.max(0, Number(seconds) || 0);
  const hours = Math.floor(safe / 3600);
  const minutes = Math.floor((safe % 3600) / 60);
  const secs = Math.floor(safe % 60);
  const frames = Math.min(FPS - 1, Math.floor((safe % 1) * FPS));
  const prefix = hours ? `${String(hours).padStart(2, "0")}:` : "";
  return `${prefix}${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}:${String(frames).padStart(2, "0")}`;
}

export function formatDuration(seconds: number): string {
  const safe = Math.max(0, Number(seconds) || 0);
  const minutes = Math.floor(safe / 60);
  const secs = Math.floor(safe % 60);
  return `${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

export function updateItem(project: Project, itemId: string, patch: Partial<TimelineItem>): Project {
  return {
    ...project,
    timeline: {
      ...project.timeline,
      items: project.timeline.items.map((item) => item.id === itemId ? { ...item, ...patch } : item),
    },
  };
}

export function moveBoundary(project: Project, leftItemId: string, proposed: number): Project {
  const items = sortedItems(project);
  const index = items.findIndex((item) => item.id === leftItemId);
  if (index < 0 || index >= items.length - 1) return project;
  const left = items[index];
  const right = items[index + 1];
  const minimumLength = 1 / FPS;
  const boundary = clamp(proposed, left.start + minimumLength, right.end - minimumLength);
  const changed = items.map((item) => {
    if (item.id === left.id) return { ...item, end: boundary };
    if (item.id === right.id) return { ...item, start: boundary };
    return item;
  });
  return { ...project, timeline: { ...project.timeline, items: changed } };
}

export function splitItem(project: Project, itemId: string, at: number): Project {
  const items = sortedItems(project);
  const index = items.findIndex((item) => item.id === itemId);
  if (index < 0) return project;
  const item = items[index];
  const minimumLength = 1 / FPS;
  if (at <= item.start + minimumLength || at >= item.end - minimumLength) return project;
  const token = Math.round(at * 1000).toString(36);
  const first = { ...item, id: `${item.id}-a-${token}`, end: at };
  const second = {
    ...item,
    id: `${item.id}-b-${token}`,
    start: at,
    trim_in: Number(item.trim_in ?? 0) + (at - item.start) * Number(item.speed ?? 1),
    transition: "cut",
  };
  items.splice(index, 1, first, second);
  return { ...project, timeline: { ...project.timeline, items } };
}

export interface TimelineIssue {
  kind: "gap" | "overlap" | "range" | "missing-take" | "empty";
  message: string;
  itemId?: string;
}

export function validateTimeline(project: Project): TimelineIssue[] {
  const duration = projectDuration(project);
  const items = sortedItems(project);
  if (!items.length) return [{ kind: "empty", message: "No shots are on the timeline." }];
  const issues: TimelineIssue[] = [];
  const epsilon = 0.002;
  if (Math.abs(items[0].start) > epsilon) {
    issues.push({ kind: "gap", message: `Timeline begins at ${formatClock(items[0].start)}, not zero.`, itemId: items[0].id });
  }
  items.forEach((item, index) => {
    if (item.start < 0 || item.end > duration + epsilon || item.end <= item.start) {
      issues.push({ kind: "range", message: "A clip is outside the song clock.", itemId: item.id });
    }
    if (item.take_id && !findTake(project, item.take_id)) {
      issues.push({ kind: "missing-take", message: "A clip points to a missing take.", itemId: item.id });
    }
    const next = items[index + 1];
    if (!next) return;
    const difference = next.start - item.end;
    if (difference > epsilon) {
      issues.push({ kind: "gap", message: `${difference.toFixed(3)} second gap after clip ${index + 1}.`, itemId: item.id });
    } else if (difference < -epsilon) {
      issues.push({ kind: "overlap", message: `${Math.abs(difference).toFixed(3)} second overlap after clip ${index + 1}.`, itemId: item.id });
    }
  });
  const tail = duration - items[items.length - 1].end;
  if (tail > epsilon) {
    issues.push({ kind: "gap", message: `${tail.toFixed(3)} seconds uncovered at the end.`, itemId: items[items.length - 1].id });
  }
  return issues;
}

export function timelineCoverage(project: Project): number {
  const duration = projectDuration(project);
  if (!duration) return 0;
  const covered = sortedItems(project).reduce((sum, item) => sum + Math.max(0, item.end - item.start), 0);
  return clamp((covered / duration) * 100, 0, 100);
}
