# Research job and result contract

Use this template for non-trivial delegation. Replace placeholders before dispatch. For a small job use the same fields in compact text; do not introduce a separate orchestration system just to satisfy the format.

## Job prepared by Rhizome

```yaml
job_id: <stable task identifier>
job_revision: <revision>
schema_version: 1
question: <one concrete question>
acceptance: <what evidence would answer it>
exclusions: []
model_id: <observed exact local identifier>
input_manifest_fingerprint: <hash of canonical manifest>
snapshots:
  - source: <approved source without credentials>
    identity: <full commit or content hash>
    acquired_at: <ISO 8601 with offset>
coverage_unit: <file, commit, record, or other explicit unit>
manifest:
  - item_id: <stable unique ID>
    locator: <path or supplied document identifier>
    content_identity: <hash or immutable revision>
    required_chunks: [<chunk IDs if split>]
classification_labels: [<task-specific labels>]
read_scope: [<exact roots or supplied item IDs>]
fetch_scope: []  # No worker network access by default.
output_directory: <absolute isolated path, or null for text-only>
tools: []  # No tools unless enforceably constrained.
budgets:
  input_tokens_per_batch: <measured safe limit>
  output_tokens_per_batch: <bounded limit>
  wall_seconds: <limit>
  fetch_requests: <limit, zero if none>
  output_bytes: <limit>
  retries_per_batch: <limit>
checkpoint_every: <one bounded batch>
retention: <task-defined policy for its own artifacts>
stop_conditions: [<budget reached, missing input, boundary breach, etc.>]
```

Include non-secret inference settings and deterministic batch assignments with the job. Store the manifest fingerprint separately from the manifest content being hashed. In text-only mode Rhizome handles file reads, checkpoints and all output writes.

## Worker result

```yaml
job_id: <exact job ID>
job_revision: <exact revision>
schema_version: 1
input_manifest_fingerprint: <unchanged fingerprint>
status: <COMPLETE, INCOMPLETE, or BLOCKED>
coverage:
  total: <manifest size>
  pending: <count>
  reviewed: <count>
  skipped: <count>
  failed: <count>
items:
  - item_id: <one entry for every manifest ID>
    status: <pending, reviewed, skipped, or failed>
    completed_chunks: []
    reason: <required for skipped or failed>
    evidence_locator: <required for reviewed, including negative results>
    inspection_summary: <what was checked and its scope, not just no issues>
findings:
  - finding_id: <stable ID>
    item_id: <manifest item ID>
    classification: <allowed label>
    claim: <specific claim>
    evidence_locator: <snapshot, path, symbol/line or page/record>
    evidence_excerpt: <short sanitised evidence actually inspected>
    observation: <what the source directly shows>
    inference: <what is inferred, if anything>
    uncertainty: <limits or conflicting evidence>
    next_verification: <falsifiable check>
unresolved: []
limitations: []
checkpoint: <last complete batch or null>
```

Check unique IDs and their exact membership as well as the count equation. Preserve pending entries for unfinished batches. Do not use unresolved findings as an additional coverage count: an inspected item may still raise an unresolved question.

Rhizome appends an independent verification record: claims relied upon, primary sources reopened, negative-result sample, errors found, resulting coverage limits and final decision. Keep it distinct from the worker's result.
