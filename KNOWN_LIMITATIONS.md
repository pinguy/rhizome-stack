# Known limitations — 0.1.0-alpha.1

- Linux static checks and dry-run installation pass on the CachyOS reference
  host. A complete install has not yet been run in a disposable native VM.
- The WSL2 path has distro/preflight coverage and a dedicated launcher, but has
  not yet been executed inside an actual WSL2 Ubuntu instance.
- WSL GPU acceleration is not enabled. The voice profile defaults to CPU.
- Ollama itself is not installed or model-populated. The stack can use an
  existing loopback Ollama service or remote models configured through
  `openclaw configure`.
- Open WebUI tool registration requires creation of the first local admin and a
  local API token; personal users or tokens are never seeded.
- Open WebUI's three minified frontend modifications are shipped as audited
  textual replacements guarded by exact upstream and result hashes.
- The code-interpreter image is intentionally smaller than the reference
  machine's accumulated development image. Its security boundary and base
  notebook path are preserved, but extra project-specific compilers and caches
  are not bundled.
- No public licence has been selected for the original packaging/glue code yet.
  Do not publish the candidate until that human decision and upstream notice
  review are complete.

