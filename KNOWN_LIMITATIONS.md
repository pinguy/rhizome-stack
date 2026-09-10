# Known limitations — 0.1.0-alpha.2

- Full installation and browser acceptance still need testing in disposable
  native Linux and actual WSL2 environments. Static and mocked-provider tests
  do not establish that the complete stack works on those targets.
- OpenClaw 2026.7.1-2 and Open WebUI 0.11.0 remain compatibility pins. Newer
  releases need patch checks and end-to-end testing before adoption.
- WSL GPU acceleration is not configured; the voice profile defaults to CPU.
- Ollama itself and LLM weights are not installed or populated.
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
- Three minified Open WebUI frontend changes use exact hash-guarded replacements.
- The Jupyter image omits the reference machine's accumulated compilers/caches.
- Base packages have version pins, but the full transitive dependency graph is
  not locked. A clean dependency install remains a required release check.
