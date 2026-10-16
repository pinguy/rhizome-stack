# Known limitations — 0.1.0-alpha.14 candidate

- Full installation and browser acceptance still need testing in disposable
  native Linux and actual WSL2 environments. Static and mocked-provider tests
  do not establish that the complete stack works on those targets.
- OpenClaw 2026.7.1-2 and Open WebUI 0.11.0 remain compatibility pins. Newer
  releases need patch checks and end-to-end testing before adoption.
- WSL GPU acceleration is not configured; the voice profile defaults to CPU.
- Ollama installation is opt-in (`--with-ollama` or the welcome wizard).
  Model weights are not bundled; Ornith downloads need separate confirmation,
  and other models must be pulled or imported explicitly.
- Provider verification checks the selected model catalogue entry. It does not
  perform inference, check billing/quota or prove tool-calling support.
- Skills are available as an opt-in profile. Existing differing local copies
  are preserved rather than automatically merged or overwritten.
- Chatterbox add-on and stack backend service names/ports overlap. They need an
  explicit shared-backend setup; their installers must not be blindly combined.
- JSONL imports stream records; regular JSON loads the document into memory.
  PDF OCR and conversational image/audio interpretation are not included.
- Import text deduplication retains multiple origins, but search normally uses
  the first origin as its canonical citation.
- Reindexing retains complete previous generations and rebuilds embeddings.
  Disk usage grows until the owner reviews/removes old generations.
- The first migration from an archive directory to a generation symlink needs
  services stopped. Restart the gateway after rebuilding its loaded index.
- Existing RhizomeML L12 indexes cannot be queried with L6 just because both are
  384-dimensional. Import text outputs or explicitly configure the matching model.
- Open WebUI tool registration needs a locally created admin and token.
- The packaged Qwen/MiniMax/WAN chat tools coordinate the local Ollama and ComfyUI
  runtimes. Their saved-chat persistence and VRAM hand-off were accepted on the
  reference machine, but still require clean native-Linux and WSL2 acceptance.
- Voice Lab is loopback-only but intentionally writes Chatterbox systemd
  drop-ins when the user selects a default. It verifies and rolls back the
  switch; combining it with another Chatterbox backend owner remains unsupported.
- Three minified Open WebUI frontend changes use exact hash-guarded replacements.
  The MP4 renderer is tied to Open WebUI 0.11.0's generated frontend chunk and
  must be re-derived and browser-tested before any Open WebUI update.
- The Jupyter image omits the reference machine's accumulated compilers/caches.
  The packaged service fails fast when that image is absent, while the direct
  Open WebUI wake/retry patch and 30-second idle guard cover cold starts. This
  does not prove arbitrary user notebooks are safe to resume after a crash.
- Base packages have version pins, but the full transitive dependency graph is
  not locked. A clean dependency install remains a required release check.
- The creative profile requires a supported NVIDIA/CUDA setup and substantial
  model storage. Its installer and graphs are checked, but a clean-machine GPU
  generation still needs native Linux and WSL2 acceptance.
- Creative model licences differ from the stack licence. Weights are downloaded
  from their pinned upstream repositories and are never redistributed here.
- Qwen Image Desk, MiniMax Music 3 and WAN Video Desk share one ComfyUI endpoint
  and therefore serialise practical GPU use. Each app may stop only the exact
  ComfyUI process it started.
  Reference editing accepts PNG/JPEG/WebP up to 20 MB; larger presets and all
  clean-machine GPU paths have not received separate quality acceptance.
- MiniLM retrieval is opt-in, loopback-only and advisory. It can return an
  irrelevant support item; final relevance and correctness remain Rhizome's job.
- WAN Video Desk's T2V and I2V paths were accepted on the reference machine,
  but its roughly 28 GB optional model set and clean-machine GPU path still need
  separate native-Linux and WSL2 acceptance on each target.

- The optional GLiNER/Ornith workforce is agent-operated through CLI helpers,
  not automatic browser routing. One reference machine has real shadow-mode and
  worker acceptance evidence, but checkpoint weights are not distributed and a
  new target still needs its own latency, memory and quality checks. The resident
  classifier is staged but disabled by default. There is no durable worker queue,
  server-side cancellation guarantee or automatic semantic acceptance.
