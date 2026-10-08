# Contributing

Run `python3 tools/check.py` before submitting a change. It discovers all
`tests/test_*.py` suites, runs them with the current Python interpreter and
reports every failing suite. Individual test files can still be run directly.
See the README for an isolated test environment using `tests/requirements.txt`.
Flask and Requests support audio/web-search tests, Pillow supports Qwen reference
images, NumPy and FAISS enable the real storage regression, and Node runs the
creative UI rendering check. Do not treat a skipped optional
check as a pass for that feature.

CI runs every suite and builds both ZIP and tar.zst archives twice, comparing
each pair byte-for-byte. Each export also passes the privacy audit, release
allow-list and SHA-256/size verification.

Add distributable source files to `manifests/release-files.json`. Keep Skills
upstream copies byte-identical to their pinned revision and update all checksums
when deliberately refreshing the snapshot. Do not vendor private runtime state.

The optional FAISS storage test uses deterministic vectors and real FAISS I/O;
it is skipped if FAISS is unavailable. It does not test embedding quality or
replace a real model-backed memory search.

Do not contribute credentials, chats, memory indexes, model weights, voice
samples, browser data, databases or machine-specific paths. Preserve upstream
copyright and licence notices when adapting upstream code.
