# 16 October 2026 release review

This review records the scope of the 0.1.0-alpha.13 candidate. It carries the
alpha.12 stack capture forward, fixes its Control UI allowance-refresh race and
keeps every earlier version directory immutable.

## Captured downstream state

- Open WebUI remains pinned to 0.11.0. Sixteen live changes were re-derived
  against the pristine wheel: three generated frontend replacements, the
  current router/tool/model/memory/middleware changes, two obsolete Kokoro
  module deletions, and the cold Jupyter service wake/retry patch. The portable
  `main.py` payload changes only the two live database tool IDs to the IDs
  created by this package (`rhizome_web_search` and `minimax_music_3`), avoiding
  a fresh-install registration mismatch without changing the routing contract.
- OpenClaw remains pinned to 2026.7.1-2. Nine live bundle changes were
  re-derived against the pristine npm package. This includes the Control UI
  five-hour/weekly allowance refresh after terminal chat events, the bounded
  rate-limit probe, model catalogue/store handling, dreaming paths, embedded
  agent registration and SQLite memory changes. Alpha.13 delays that refresh,
  preserves the last non-empty allowance snapshot and retries once when the
  provider reports transiently empty windows around a reset.
- The adapter, tool registration and saved-chat attachment flow continue to
  connect Open WebUI to OpenClaw without duplicating OpenClaw's system/tool
  prompt on `openclaw/*` models.

Every patch target is relative and guarded by the exact clean SHA-256 recorded
in its manifest. Applying a set to a different upstream base fails before
replacement.

## Apps, search and Skills

Qwen Image Desk and WAN Video Desk were refreshed from the current accepted
standalone applications. MiniMax Music 3 retains the packaged path and HTTP
hardening while gaining dynamic display of every writer model returned by the
backend and per-track deletion. All three packaged Open WebUI tools remain
registered and share the durable, serialized VRAM hand-off bridge.

The Brave-backed web-search component remains version 1.9.0. Reuters was
already present in the reputable-reporting policy; this release adds a direct
regression proving that a `reuters.com` result is retained and labelled
`credibly_reported` rather than relying on an untested constant.

The package now contains thirteen byte-identical upstream Skill directories at
commit `99e53d4501703a78fb87ad4221512029558802b7`, including the new core
`minimum-sufficient-change` skill, plus two current owner-supplied stack skills
with the reference-machine paths adapted out and both source and packaged
hashes recorded.

## Browser evidence and limits

[The showcase](SHOWCASE.md) contains current, privacy-scrubbed captures of the
three standalone apps and real saved-chat PNG, MP3 and MP4 rendering in Open
WebUI. This is reference-machine acceptance evidence, not clean native Linux or
WSL2 installation acceptance. Private runtime state and generated media remain
outside the distribution allow-list.
