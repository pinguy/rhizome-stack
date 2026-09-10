# Contributing

Run `python3 tests/test_static.py` and `python3 tests/test_behaviour.py` before submitting a change. A release must
also pass `tools/privacy_audit.py`, manifest verification and the deterministic
two-build comparison.

Add distributable source files to `manifests/release-files.json`. Keep Skills
copies byte-identical to their pinned upstream revision and update all checksums
when deliberately refreshing the snapshot. Do not vendor private runtime state.

The optional FAISS storage test uses deterministic vectors and real FAISS I/O;
it is skipped if FAISS is unavailable. It does not test embedding quality or
replace a real model-backed memory search.

Do not contribute credentials, chats, memory indexes, model weights, voice
samples, browser data, databases or machine-specific paths. Preserve upstream
copyright and licence notices when adapting upstream code.
