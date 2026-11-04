import { describe, expect, it } from "vitest";
import { activeItemAt, formatClock, moveBoundary, projectDuration, splitItem, validateTimeline } from "./editor";
import type { Project } from "./types";

const project: Project = {
  id: "p",
  name: "Test",
  schema: "music-video-studio.project/v1",
  revision: 1,
  audio: { path: "audio/source.wav", duration: 10 },
  analysis: { audio: { duration: 10 }, beats: [0, 1], waveform: [], sections: [] },
  assets: [],
  shots: [
    { id: "s1", start: 0, end: 5, selected_take_id: "t1", takes: [{ id: "t1", path: "a.mp4" }] },
    { id: "s2", start: 5, end: 10, selected_take_id: "t2", takes: [{ id: "t2", path: "b.mp4" }] },
  ],
  timeline: {
    items: [
      { id: "i1", shot_id: "s1", take_id: "t1", start: 0, end: 5, trim_in: 0, speed: 1 },
      { id: "i2", shot_id: "s2", take_id: "t2", start: 5, end: 10, trim_in: 0, speed: 1 },
    ],
    titles: [],
  },
};

describe("editor model", () => {
  it("uses analysed audio as the clock", () => {
    expect(projectDuration(project)).toBe(10);
    expect(formatClock(65.5)).toBe("01:05:12");
  });

  it("finds the active item at exact boundaries", () => {
    expect(activeItemAt(project, 4.99)?.id).toBe("i1");
    expect(activeItemAt(project, 5)?.id).toBe("i2");
    expect(activeItemAt(project, 10)?.id).toBe("i2");
  });

  it("moves a shared boundary without creating a gap", () => {
    const changed = moveBoundary(project, "i1", 6.25);
    expect(changed.timeline.items[0].end).toBe(6.25);
    expect(changed.timeline.items[1].start).toBe(6.25);
    expect(validateTimeline(changed)).toEqual([]);
  });

  it("splits a clip and advances source trim", () => {
    const changed = splitItem(project, "i1", 2);
    expect(changed.timeline.items).toHaveLength(3);
    expect(changed.timeline.items[1].trim_in).toBe(2);
    expect(validateTimeline(changed)).toEqual([]);
  });
});
