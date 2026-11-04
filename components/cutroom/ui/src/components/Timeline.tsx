import { useMemo, useRef, useState } from "react";
import { findShot, findTake, formatClock, projectDuration, sortedItems } from "../editor";
import type { Project } from "../types";

interface TimelineProps {
  project: Project;
  playhead: number;
  selectedItemId: string | null;
  zoom: number;
  onZoom: (zoom: number) => void;
  onSeek: (time: number) => void;
  onSelect: (id: string) => void;
  onMoveBoundary: (leftItemId: string, time: number) => void;
}

function sectionColour(index: number): string {
  return ["#174f63", "#5a3f78", "#76521d", "#1c5b4d", "#633847"][index % 5];
}

export function Timeline({ project, playhead, selectedItemId, zoom, onZoom, onSeek, onSelect, onMoveBoundary }: TimelineProps) {
  const duration = projectDuration(project);
  const pixelsPerSecond = 54 * zoom;
  const width = Math.max(900, duration * pixelsPerSecond);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<{ itemId: string; time: number } | null>(null);
  const items = sortedItems(project);
  const sections = project.analysis?.sections ?? [];
  const beats = project.analysis?.beats ?? [];
  const waveform = project.analysis?.waveform ?? [];
  const tickStep = useMemo(() => {
    if (pixelsPerSecond >= 90) return 1;
    if (pixelsPerSecond >= 42) return 5;
    return 10;
  }, [pixelsPerSecond]);
  const ticks = useMemo(() => Array.from({ length: Math.floor(duration / tickStep) + 1 }, (_, index) => index * tickStep), [duration, tickStep]);
  const waveformLines = useMemo(() => {
    if (!waveform.length) return [];
    const maxLines = Math.min(1200, Math.max(300, Math.floor(width / 2)));
    const step = Math.max(1, Math.ceil(waveform.length / maxLines));
    const lines: Array<{ x: number; y1: number; y2: number }> = [];
    for (let index = 0; index < waveform.length; index += step) {
      const [low, high] = waveform[index];
      lines.push({
        x: (index / Math.max(1, waveform.length - 1)) * width,
        y1: 26 - Math.max(-1, Math.min(1, high)) * 22,
        y2: 26 - Math.max(-1, Math.min(1, low)) * 22,
      });
    }
    return lines;
  }, [waveform, width]);

  function timeFromPointer(clientX: number): number {
    const rect = scrollRef.current?.getBoundingClientRect();
    const scrollLeft = scrollRef.current?.scrollLeft ?? 0;
    if (!rect) return 0;
    return Math.max(0, Math.min(duration, (clientX - rect.left + scrollLeft - 88) / pixelsPerSecond));
  }

  function seekFromPointer(event: React.PointerEvent) {
    if ((event.target as HTMLElement).closest("[data-no-seek]")) return;
    onSeek(timeFromPointer(event.clientX));
  }

  function startBoundaryDrag(event: React.PointerEvent, itemId: string) {
    event.preventDefault();
    event.stopPropagation();
    const target = event.currentTarget as HTMLElement;
    target.setPointerCapture(event.pointerId);
    setDrag({ itemId, time: timeFromPointer(event.clientX) });
  }

  function updateBoundaryDrag(event: React.PointerEvent) {
    if (!drag) return;
    setDrag({ ...drag, time: timeFromPointer(event.clientX) });
  }

  function finishBoundaryDrag(event: React.PointerEvent) {
    if (!drag) return;
    (event.currentTarget as HTMLElement).releasePointerCapture(event.pointerId);
    onMoveBoundary(drag.itemId, drag.time);
    setDrag(null);
  }

  return (
    <section className="timeline-shell" aria-label="Song-locked timeline">
      <header className="timeline-toolbar">
        <div>
          <strong>Timeline</strong>
          <span>{formatClock(playhead)}</span>
          <small>{FPS_LABEL}</small>
        </div>
        <label className="zoom-control">
          <span>Zoom</span>
          <input aria-label="Timeline zoom" type="range" min="0.55" max="3" step="0.05" value={zoom} onChange={(event) => onZoom(Number(event.target.value))} />
        </label>
      </header>
      <div className="timeline-scroll" ref={scrollRef} onPointerDown={seekFromPointer}>
        <div className="timeline-canvas" style={{ width: width + 88 }}>
          <div className="track-gutter ruler-gutter">CLOCK</div>
          <div className="ruler" style={{ width }}>
            {ticks.map((tick) => <div className="ruler-tick" key={tick} style={{ left: tick * pixelsPerSecond }}><i /><span>{formatClock(tick).replace(/:\d\d$/, "")}</span></div>)}
          </div>

          <div className="track-gutter structure-gutter">SONG</div>
          <div className="structure-track" style={{ width }}>
            {sections.map((section, index) => (
              <div className="song-section" key={section.id ?? `${section.name}-${section.start}`} style={{ left: section.start * pixelsPerSecond, width: Math.max(2, (section.end - section.start) * pixelsPerSecond), background: sectionColour(index) }}>
                <strong>{section.name}</strong><small>{Math.round((section.energy ?? 0) * 100)}%</small>
              </div>
            ))}
          </div>

          <div className="track-gutter video-gutter"><b>V1</b><span>Shots</span></div>
          <div className="video-track" style={{ width }}>
            {beats.map((beat) => <i className="beat-line" key={beat} style={{ left: beat * pixelsPerSecond }} />)}
            {items.map((item, index) => {
              const shot = findShot(project, item.shot_id);
              const take = findTake(project, item.take_id);
              return (
                <button
                  type="button"
                  data-no-seek
                  className={`timeline-clip ${selectedItemId === item.id ? "selected" : ""} ${take ? "has-take" : "missing-take"}`}
                  key={item.id}
                  style={{ left: item.start * pixelsPerSecond, width: Math.max(3, (item.end - item.start) * pixelsPerSecond) }}
                  onClick={() => { onSelect(item.id); onSeek(item.start); }}
                >
                  <span className="clip-index">{String(index + 1).padStart(2, "0")}</span>
                  <span className="clip-copy"><strong>{shot?.framing || shot?.title || `Shot ${index + 1}`}</strong><small>{take?.backend ?? "No take"}</small></span>
                  {index < items.length - 1 && (
                    <i
                      className="boundary-handle"
                      aria-label={`Move boundary after clip ${index + 1}`}
                      onPointerDown={(event) => startBoundaryDrag(event, item.id)}
                      onPointerMove={updateBoundaryDrag}
                      onPointerUp={finishBoundaryDrag}
                    />
                  )}
                </button>
              );
            })}
            {drag && <div className="drag-guide" style={{ left: drag.time * pixelsPerSecond }}><span>{formatClock(drag.time)}</span></div>}
          </div>

          <div className="track-gutter audio-gutter"><b>A1</b><span>Master</span></div>
          <div className="audio-track" style={{ width }}>
            <svg width={width} height="52" preserveAspectRatio="none" aria-hidden="true">
              {waveformLines.map((line, index) => <line key={index} x1={line.x} x2={line.x} y1={line.y1} y2={line.y2} />)}
            </svg>
          </div>

          <div className="timeline-playhead" style={{ left: 88 + playhead * pixelsPerSecond }}><i /><span>{formatClock(playhead)}</span></div>
        </div>
      </div>
    </section>
  );
}

const FPS_LABEL = "24 fps";
