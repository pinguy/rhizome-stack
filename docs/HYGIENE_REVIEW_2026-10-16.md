# Hygiene follow-up — 16 October 2026

Reviewed the supplied alpha.13 tar.zst and prepared the alpha.14 candidate.
The original archive is the baseline. This pass preserves the alpha.13 quota
fix, upstream patch payloads, compatibility/model pins, bundled Skills and
creative generation graphs.

## Reproduced failures and corrections

| Finding | Before | Correction and evidence |
| --- | --- | --- |
| Patch failure changes installed code | A corrupt second replacement left the first installed file changed and the second corrupt before the final hash check failed. | Apply the whole set in staging, verify every result, then install. Corrupt replacements and malformed diffs leave the installation unchanged, including when a preceding entry deletes a file. |
| Replacement loses executable permission | A synthetic mode-0755 target became 0644. | Preserve file metadata and use unique, atomic sibling replacements. Regression checks both mode and contents, original backups and repeat application. |
| ComfyUI ownership uses substring matching | All three apps accepted port 81880 for 8188, a `main.py.other` script and unrelated processes carrying matching text in arguments. | Read NUL-separated process arguments and match the script position and complete port pair. Synthetic positives and negatives cover Qwen, MiniMax and WAN. |
| Qwen accepts incomplete JSON requests | Closing a connection after a valid JSON prefix, but before the declared length, still called prompt expansion and returned 200. | Require exactly the declared number of bytes before JSON parsing. A loopback HTTP regression expects 400 and proves the helper was not called. |

Patch paths are additionally confined to their declared roots, and duplicate
entries and unknown actions are rejected. The clean upstream SHA-256 checks
remain mandatory. A simulated second-file write failure proves the first file
is restored with its original executable mode. Rollback does not intentionally
overwrite files that no longer match this run's replacements.

## Verification

The initial default interpreter lacked test dependencies. After installing the
exact `tests/requirements.txt` pins in an isolated Python 3.12 environment, the
unchanged baseline passed all 14 suites with no skips. The new failure cases
were then run against the original implementations and failed as described.

Final verification:

- All **14 suites passed**: **165 unittest cases**, including one explicitly
  skipped live-process canary, plus static checks and creative graph checks.
- The real FAISS storage regression ran with deterministic vectors. This checks
  storage behaviour, not embedding quality.
- Privacy audit, release allow-list, SHA-256/size verification and whitespace
  checks passed. Two independent tar.zst builds matched byte-for-byte; the two
  ZIP builds also matched.
- Upstream patch payloads, compatibility/model pins, configuration and bundled
  Skills were compared against the uploaded baseline and remain unchanged.

Reproduce from the source root with an isolated environment containing
`tests/requirements.txt`:

```bash
python3 tools/check.py
git diff --check
python3 tools/build_release.py --output-root /tmp/rhizome-alpha14-a
python3 tools/build_release.py --output-root /tmp/rhizome-alpha14-b
cmp /tmp/rhizome-alpha14-a/0.1.0-alpha.14/rhizome-stack.tar.zst /tmp/rhizome-alpha14-b/0.1.0-alpha.14/rhizome-stack.tar.zst
cmp /tmp/rhizome-alpha14-a/0.1.0-alpha.14/rhizome-stack.zip /tmp/rhizome-alpha14-b/0.1.0-alpha.14/rhizome-stack.zip
```

## Boundaries and recovery

This is a source review and isolated regression run. It does not establish
native Linux/WSL2 installation, a real provider chat, GPU generation, browser
integration, audio quality or full runtime dependency compatibility. The known
acceptance gaps remain in `KNOWN_LIMITATIONS.md`.

The environment exposes a `/proc` PID namespace different from Python's process
IDs. The added real-process ownership/stop canary explicitly skips in that
condition; argument-level regressions still execute. Run that canary on a normal
Linux target before treating live process stopping as accepted.

No installed stack, provider account, model weights or remote repository was
modified. The original upload remains the rollback baseline for this review.
Patch staging handles validation errors and ordinary write failures, but does
not make a multi-file install atomic across power loss or process termination.
See `MAINTENANCE.md` for retained-backup recovery and service-stop requirements.

## Repository integration

The GitHub base was alpha.11 at commit
`becb0b4c2bfd6942283541daaf54386774084506`. This update also brings in the
alpha.12/13 changes already present in the supplied archive. The repository's
portable `ornith-research-workforce/references/stack-workforce.md` is retained
byte-for-byte: the workspace template still points to it. Its checksum and
release allow-list entry are restored alongside the refreshed skill snapshot.
No existing repository-only source file is deleted. Generated release manifests
remain build outputs rather than tracked source.

Git whitespace checks treat `.patch` files as exact diff payloads: trailing
whitespace and the required space-before-tab context prefixes within them are
excluded from that check using `.gitattributes`.
This preserves required context markers and the recorded upstream hashes;
normal source and documentation whitespace checks remain enabled.
