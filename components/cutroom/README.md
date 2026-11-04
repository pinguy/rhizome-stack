# Cutroom companion

Cutroom is the optional music-first production workspace shipped with Rhizome
Stack. The source song is the absolute clock: shot boundaries, trims, playback
and the final FFmpeg render stay tied to that timeline.

This package contains both parts needed by the application:

- `backend/`: the loopback Python API, project store, analysis, generation
  queue, media streaming and deterministic renderer;
- `ui/`: the React/TypeScript production workspace and its loopback proxy.

The creative installer builds the UI with the pinned `package-lock.json`.
Model weights, projects, source songs, generated media, logs and browser state
are deliberately absent. Runtime state defaults to
`$RHIZOME_STACK_ROOT/creative/state/cutroom`.

## Start

Install with the creative profile, then start Cutroom:

```bash
./install-linux.sh --with-creative
rhizome-stack creative cutroom
```

The UI listens on `127.0.0.1:8842` and its internal backend on
`127.0.0.1:8843`. These ports avoid the standalone Qwen Image Desk and Video
Desk ports. All services share the same ComfyUI endpoint, so do not run two
generations at once; each queue refuses to take over an engine it does not own.

For source development:

```bash
cd components/cutroom/ui
npm ci
npm test
npm run build
RHIZOME_STACK_ROOT="$HOME/.local/share/rhizome-stack" python3 server.py
```

Run the backend separately from `components/cutroom/backend/app.py`, setting
`STUDIO_ROOT`, `STUDIO_PORT`, `COMFY_DIR` and the optional model variables in
`config/stack.env.example`.

The interface was informed by studying Slopus as a product reference. No
Slopus source or assets are included. Cutroom's code in this distribution is
original MIT-licensed Rhizome Stack material.

## Render failure and storage safety

Each render uses a unique output name and its own temporary segment directory.
Segments and concat intermediates are removed after success or a handled failure;
finished MP4 files, JSON manifests and diagnostic logs are kept. A failed
partial MP4 is removed rather than published. A hard power loss or SIGKILL can
still leave scratch data under `timeline/render-work/`; review that directory
only while the renderer is stopped. The renderer refuses to read song or take
paths outside the individual project, including symlinks that escape it.

An invalid preset or missing project fails before the render lock is entrusted
to a worker. Browser byte-range requests support prefix, bounded and suffix
ranges; unsatisfiable ranges return HTTP 416.
