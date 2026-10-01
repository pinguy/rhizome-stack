# Backport record

Use one record per bounded candidate. Fill unknowns explicitly; do not turn placeholders into evidence. Keep scan records short and expand implementation/rollout fields only when that work is in scope. Store completed records only in the designated task output directory.

## Identity and decision

- Candidate ID / observed at (ISO 8601 with offset):
- User objective / authorised mode and scope:
- Primary disposition / additional risk flags:
- Recommendation and concrete benefit:
- Official advisory, issue, commit or release evidence:
- Upstream full commit / tag / retrieval time:
- Recorded downstream base / evidence for ancestry:
- Actual CLI and gateway paths, identities and versions:
- Installed target hashes / local patch inventory reference:
- Known pre-existing failures:

## Applicability and minimum change

- Failure or vulnerability / deployed affected path:
- Exposure status and evidence (confirmed / plausible / unknown / not affected):
- Local equivalent or workaround / proof of equivalence:
- Source files / generated counterparts / runtime-loaded targets:
- Required commits, dependencies, schema and API assumptions:
- Excluded unrelated changes:
- Unknowns that could change the decision:

## Acceptance

| Contract or reproducer | Baseline | Expected after change | Actual result | Evidence |
| --- | --- | --- | --- | --- |
| Fill relevant checks only | PASS / FAIL / NOT RUN / N/A | Falsifiable behaviour | PASS / FAIL / NOT RUN / N/A | Command or observation, timestamp, sanitised output location |

For model checks, record catalogue entry, picker visibility, selected route, actual provider/model and advertised/configured/observed context limits separately. A listed model is not proof of access; a small canary is not proof of the maximum context window.

## Isolated implementation and rollout

- Isolated environment / source snapshot / patch identifier:
- Build or bundle reproduction method:
- Live target list and last-moment hash comparison:
- Backup location / permissions / integrity proof:
- State snapshot consistency / migration and restore proof:
- Treatment of post-snapshot writes / acceptable data loss, if any:
- Atomic or otherwise consistent application sequence:
- Services affected / authorised restart / downtime bound:
- Observation window / abort criteria:
- Offline-capable restoration steps and required access:
- Rollback rehearsal result / post-restoration checks:

## Outcome

- Proposed / implemented in isolation / applied live / verified live / rolled back:
- Passed, failed and unrun acceptance checks:
- Residual risk or blocker / next concrete action:
- Durable operational note updated, if authorised, with actual observed state:
