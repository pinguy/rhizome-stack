---
name: risk-aware-retry
description: "Execute tasks reliably under transient failures without duplicating side effects or hiding risk. Use when network calls, package operations, APIs, locks, rate limits, eventual consistency, or flaky services fail and the agent must decide whether to retry, reconcile state, resume, change tactic, escalate, or stop."
---

# Risk-Aware Retry

Default to **completion, not first-attempt success** — but never confuse a transient-looking error with permission to repeat an operation blindly.

The retry decision has four independent questions:

1. **What kind of failure occurred?**
2. **Is repeating this operation safe?**
3. **Did the previous attempt commit?**
4. **What is the blast radius if we are wrong?**

A timeout after a read is usually cheap to retry.  
A timeout after sending, creating, publishing, charging, deleting, appending, or enqueueing may have succeeded even when the response was lost.

## Core rule

**Retry transient failures automatically only when repetition is known to be safe. If commit state is uncertain, reconcile actual state before replaying any non-idempotent operation. Stop retrying when the evidence points to a persistent failure, the risk class changes, the retry budget is exhausted, or repeated attempts stop producing new information.**

Use this loop:

**classify failure → classify repeat safety → determine commit state → assess action risk → retry / reconcile / resume / change tactic → verify real outcome → report DONE or BLOCKED**

## Trigger

Use this skill when a task is being disrupted by flaky transport, rate limits, temporary locks, eventual consistency, resumable work, or an uncertain result from a prior attempt.

Do not use retry logic to paper over a deterministic bug, invalid input, missing permission, violated invariant, unsupported operation, or other failure that requires a changed precondition rather than another replay.

---

## 1. Decision model

Do not collapse different kinds of uncertainty into one label.

Treat these as separate dimensions.

### A. Failure class

- `TRANSIENT`
- `PERSISTENT`
- `UNKNOWN`

### B. Repeat-safety class

- `READ_ONLY`
- `IDEMPOTENT`
- `DEDUPLICATED`
- `NON_IDEMPOTENT`

### C. Commit state

- `NOT_APPLICABLE`
- `COMMITTED`
- `NOT_COMMITTED`
- `UNKNOWN`

### D. Action risk

- `LOW`
- `MEDIUM`
- `HIGH`

The important distinction is this:

> **Ambiguous commit is not an operation type. It is a state of knowledge about what happened.**

A non-idempotent operation can have `COMMITTED`, `NOT_COMMITTED`, or `UNKNOWN` commit state.  
So can an idempotent operation. The response to uncertainty depends on both dimensions.

---

## 2. Classify the failure first

Identify the most likely class from direct evidence.

### Usually transient

Examples:

- `ECONNRESET`
- `ETIMEDOUT`
- temporary DNS resolution failure
- interrupted download
- connection refused during a known service restart
- HTTP `408`, `429`, `502`, `503`, `504`
- temporary file or package-manager lock
- short-lived eventual-consistency miss
- brief dependency outage

These are **retry candidates**, not automatic permission to retry.

### Usually persistent until something changes

Examples:

- invalid command syntax
- malformed request
- missing executable
- wrong path
- failed schema or validation
- unsupported runtime flag
- deterministic test failure
- HTTP `400`, `401`, `403`, most `404`
- authentication or authorisation failure
- disk full
- incompatible version
- corrupt input
- violated invariant

Do not burn retry budget replaying the same deterministic failure.

### Context-dependent cases

Treat status codes and errors by semantics, not number alone.

- `401` / `403` → repair authentication or permission; do not blindly retry.
- `404` → usually persistent, but may be transient after creation or replication; verify the consistency model.
- `409` → inspect conflict state; retry only when the conflict is expected to clear or the request is designed to reconcile it.
- `423` → may be retryable when a lock is expected to expire or be released.
- `425` → follow protocol/provider guidance before replay.
- `429` → honour `Retry-After` or reset guidance where available.
- `5xx` → often transient, but repeated identical failures may indicate a persistent upstream fault.
- connection loss → classify commit state separately; transport failure alone does not tell you whether the operation committed.

### If evidence is weak

Use `UNKNOWN`, not wishful thinking.

When failure class is unknown:

1. gather one or two high-value diagnostics;
2. avoid state-changing replay until repeat safety is known;
3. reclassify based on evidence;
4. stop if more retries would add no information.

---

## 3. Classify repeat safety

Before retrying any operation that can change state, classify the operation itself.

### READ_ONLY

The operation observes state and has no material side effect.

Examples:

- `GET` request
- metadata query
- status check
- health check
- package index lookup
- read-only database query

**Default:** safe to retry within budget.

Classify the operation by its real semantics, not its verb or command name. A nominal `GET` endpoint can still have broken side effects, and commands such as `git fetch` mutate local repository metadata even though they are normally safe to repeat.

Still consider cost, rate limits, load, local state changes, and provider guidance.

### IDEMPOTENT

Repeating the operation produces the same intended state.

Examples:

- ensure directory exists
- set a configuration field to a specific value
- upload identical content to a content-addressed key
- atomically replace a known file with the same validated content
- true replacement-style `PUT`
- declarative "ensure desired state" operations

**Default:** retry only after confirming the operation is genuinely idempotent in the current system.

Do not assume idempotence merely because an HTTP method or SDK call is *named* idempotent.

Check for hidden side effects such as:

- audit events
- billing
- notifications
- version increments
- timestamps
- generated IDs
- hooks
- duplicate downstream work

### DEDUPLICATED

The operation may have side effects, but the system supports a stable idempotency key, transaction ID, job key, request ID, or equivalent deduplication mechanism.

**Default:** retry the same logical operation with the **same deduplication identity**.

Never generate a fresh idempotency key merely because the transport attempt is new.

A new key means a new logical operation.

### NON_IDEMPOTENT

Repeating may duplicate or compound side effects.

Examples:

- send email or message
- publish post or comment
- create order, account, ticket, or job without deduplication
- append data
- increment counters
- trigger payment
- enqueue work
- destructive mutation
- invoke an external action whose duplicate effect matters

**Default:** do not replay unless evidence proves the previous attempt did **not** commit.

---

## 4. Determine commit state

Commit state is separate from failure class and repeat safety.

### NOT_APPLICABLE

Use for operations where commit state is irrelevant, usually read-only actions.

### COMMITTED

Evidence shows the intended effect already exists.

Examples:

- resource exists under the expected ID
- message appears once in sent history
- job exists with the expected request key
- transaction record confirms success
- Git ref points to the intended commit
- file exists with the expected hash

**Action:** do not replay. Continue from the committed state and verify the real outcome.

### NOT_COMMITTED

Evidence shows the effect did not occur.

**Action:** retry when failure class, risk, authority, and budget permit.

### UNKNOWN

The caller cannot reliably determine whether the operation committed.

Examples:

- connection dropped after request body transmission began
- timeout while waiting for a create/send response
- tool process died after invoking an external action
- upstream returned no usable acknowledgement
- response was lost after server-side work may have completed

**Action:** reconcile before replaying a non-idempotent operation.

For proven `IDEMPOTENT` or `DEDUPLICATED` operations, a retry may still be safe, but preserve the same logical identity and verify afterwards.

> **Unknown commit state outranks apparent transport transience for non-idempotent operations.**

---

## 5. Use request phase to estimate commit uncertainty

When possible, record how far the failed attempt got.

Useful phases:

- `BEFORE_SEND`
- `CONNECTING`
- `SENDING`
- `SENT_WAITING_RESPONSE`
- `RESPONSE_PARTIAL`
- `ACKNOWLEDGED`

Interpretation:

- failure before any request bytes were sent usually supports `NOT_COMMITTED`;
- failure after transmission began may imply `UNKNOWN`;
- application acknowledgement may support `COMMITTED`, but still verify the actual intended state when material;
- a transport success does not guarantee application success.

Do not claim precision the protocol does not provide.

---

## 6. Reconcile ambiguous commit state

When commit state is `UNKNOWN`:

1. stop blind replay;
2. identify the logical operation's durable identity;
3. inspect actual remote or local state;
4. determine whether the intended effect exists;
5. classify state as `COMMITTED`, `NOT_COMMITTED`, or still `UNKNOWN`;
6. retry only when the resulting state and repeat-safety class make replay safe.

Useful reconciliation evidence includes:

- stable request or idempotency key
- preallocated or returned object ID
- remote resource listing
- message or draft lookup
- job queue status
- transaction record
- filesystem existence plus content hash
- Git ref and commit state
- package-manager database state
- service logs tied to request ID
- API audit or event history
- provider operation-status endpoint

### Reconciliation outcomes

#### COMMITTED

The first attempt succeeded.

Do not retry.

Verify that the intended effect exists **once** and is usable.

#### NOT_COMMITTED

Evidence shows the effect did not occur.

Retry if authority, risk, and budget permit.

#### UNKNOWN

State cannot be established reliably.

Treat this as risk escalation.

Do not guess and replay a meaningful non-idempotent operation.

---

## 7. Classify action risk

Repeat safety answers **"can this be repeated safely?"**

Risk answers **"what happens if our classification is wrong?"**

These are different.

### LOW

Examples:

- read-only requests
- resumable downloads
- package metadata fetch
- expected temporary locks
- idempotent local operations with verified rollback
- transient upstream errors with no meaningful committed side effect

Action:

- retry automatically within budget;
- follow provider guidance;
- change tactic when evidence stalls;
- continue until success, persistent failure, exhausted budget, or risk change.

### MEDIUM

Examples:

- reversible config mutation
- service restart with expected temporary disruption
- retry of a long-running job whose state is known
- operation that may duplicate low-impact work
- action with moderate resource, cost, or availability impact

Action:

1. inspect current state;
2. establish repeat safety;
3. preserve rollback or recovery path;
4. proceed only within existing authority;
5. verify afterwards.

### HIGH

Examples:

- destructive mutation
- security boundary change
- public post or message
- email to a third party
- payment or purchase
- irreversible external effect
- retry with unknown commit state and meaningful side effects
- unclear blast radius

Action:

1. stop automatic replay;
2. reconcile state where possible;
3. preserve the safest known-good state;
4. obey the normal approval and authority boundary;
5. surface the safest concrete action.

Retry logic never grants authority the original action did not have.

---

## 8. Decision table

Use this as the fast path.

| Repeat safety | Commit state | Typical action |
|---|---|---|
| `READ_ONLY` | `NOT_APPLICABLE` | Retry transient failures within budget |
| `IDEMPOTENT` | `NOT_COMMITTED` | Retry within budget |
| `IDEMPOTENT` | `COMMITTED` | Do not replay; verify desired state |
| `IDEMPOTENT` | `UNKNOWN` | Reconcile when practical; otherwise retry only if idempotence is proven |
| `DEDUPLICATED` | `NOT_COMMITTED` | Retry with same deduplication identity |
| `DEDUPLICATED` | `COMMITTED` | Do not create a new logical operation; verify |
| `DEDUPLICATED` | `UNKNOWN` | Reconcile or retry with the same deduplication identity |
| `NON_IDEMPOTENT` | `NOT_COMMITTED` | Retry only when failure/risk/budget permit |
| `NON_IDEMPOTENT` | `COMMITTED` | Do not retry |
| `NON_IDEMPOTENT` | `UNKNOWN` | Reconcile; if unresolved, stop |

High-risk actions may still require an approval boundary even when technically safe to repeat.

---

## 9. Use provider and protocol guidance first

When the failing system exposes retry instructions, prefer them over generic backoff.

Use, where available:

- `Retry-After`
- rate-limit reset timestamps
- documented retryable status/error codes
- idempotency-key semantics
- resumable-transfer offsets
- lock lease or expiry times
- operation-status endpoints
- API request IDs
- service-specific retry budgets
- server-provided backoff hints

Do not hammer a service with exponential retries when it has already told you when to try again.

Do not retry faster than the documented limit.

---

## 10. Retry budget

Use a **budget**, not an infinite loop.

Prefer, in order:

1. provider retry policy;
2. explicit task deadline;
3. elapsed retry budget;
4. fallback attempt ladder.

### Default fallback

When no better guidance exists:

- maximum attempts: `8`
- delays: `2s, 4s, 8s, 15s, 25s, 40s, 60s, 90s`
- jitter: approximately `±20%`
- per-attempt timeout: explicit and appropriate to the operation

The eight-attempt ladder is a fallback, not doctrine.

Changing endpoint, transport, worker, or tactic does **not** silently reset the task-wide retry budget. If a provider defines a per-operation or per-endpoint budget, record that distinction explicitly.

Stop earlier when:

- the error becomes clearly persistent;
- repeat safety is no longer established;
- commit state becomes dangerously ambiguous;
- the task deadline is exceeded;
- provider guidance says not to continue;
- resource pressure becomes unsafe;
- the failure crosses an authority boundary;
- retries stop producing new evidence.

### Reassessment trigger

If the same materially identical failure occurs **three times without new evidence**, stop replaying mechanically and reassess the hypothesis.

Three failures do not prove permanence. They do prove that "try exactly the same thing again" is no longer learning much.

---

## 11. Change tactic when evidence stalls

A tactic change must follow from a changed hypothesis.

Do not change tactics merely because the current attempt is annoying.

Ask:

- Is the failure actually transient?
- Is the network path failing, or only one endpoint?
- Is the request malformed?
- Has authentication expired?
- Is the resource locked by a live owner?
- Did an earlier attempt already commit?
- Is the API or version assumption stale?
- Can the operation resume rather than restart?
- Is there a lower-risk equivalent path?
- Is concurrency causing duplicate work or conflicts?

### Git / network

Instead of endlessly repeating:

```sh
git fetch
```

consider:

- confirm DNS and reachability;
- inspect the remote URL;
- distinguish authentication from transport failure;
- retry using the normal supported transport;
- reduce unnecessary refs or tags only when justified;
- verify local repository state before changing strategy.

### Download

Prefer:

- resume when supported;
- verify final size or hash;
- restart only when partial state is unusable;
- avoid redownloading known-good chunks.

### HTTP `429`

Prefer:

- honour `Retry-After`;
- reduce avoidable concurrency;
- suppress incidental calls;
- preserve the same idempotency identity for the same logical mutation.

### Temporary lock

Prefer:

- identify the lock owner;
- establish whether it is active, expired, or stale;
- wait for a live expected owner;
- respect lease semantics;
- do not delete a lock merely because progress is inconvenient.

---

## 12. Control concurrent retries

Retries can become unsafe when multiple workers act on the same logical operation.

When concurrency is possible:

- use a stable logical operation ID;
- use single-flight, lease, lock, transaction, or provider deduplication where available;
- ensure retries from different workers share the same idempotency identity;
- avoid one worker "recovering" while another is still committing;
- inspect ownership before clearing locks;
- verify that recovery did not create duplicate downstream work.

A safe retry policy executed concurrently without coordination can still duplicate effects.

---

## 13. Preserve partial progress

Do not discard useful work merely because the overall operation failed.

When safe:

- resume partial downloads;
- preserve completed independent build artefacts;
- keep successful independent substeps;
- record created IDs;
- reuse successful cached results;
- continue from a known checkpoint.

Classify interrupted partial state as:

- `KNOWN_GOOD`
- `RESUMABLE`
- `DISPOSABLE`
- `UNKNOWN`

`UNKNOWN` partial state must be inspected before reuse.

Never promote unknown or corrupt partial state to known-good merely to avoid repeating work.

---

## 14. Verify the real outcome

Transport success is not task completion.

Verify the property the user actually needed.

Weak:

> Request returned HTTP 200.

Better:

> The requested object exists once, has the expected state, and the consuming path can use it.

Weak:

> Download command exited 0.

Better:

> Final file size or hash matches the expected object and the file opens successfully.

Weak:

> Service restart command succeeded.

Better:

> The service is active and the real request path works.

For state-changing work, verify both:

1. the intended effect occurred;
2. retries did not create duplicate or unintended side effects.

When possible, verify through an independent read path rather than trusting only the write response.

---

## 15. Progress signalling

Do not spam the user with every safe transient retry.

Normally stay quiet during low-risk retries.

Send an update when:

- risk class changes;
- commit state becomes `UNKNOWN`;
- retries require a materially different tactic;
- authority or approval is needed;
- the operation becomes meaningfully prolonged;
- the task becomes blocked;
- the user asks for status.

A useful update explains what changed in the model of the problem.

Bad:

> Retry 4 failed. Trying again.

Better:

> The transport error is repeating, so I’m no longer treating this as a simple transient failure. The operation is read-only, so there’s no side-effect risk; I’m checking endpoint reachability before spending more retry budget.

---

## 16. Interaction with stronger safety workflows

Retry behaviour does not override stronger constraints.

When another workflow applies:

- protected targets remain protected;
- privileged actions keep their normal approval boundary;
- destructive operations still require explicit authority;
- known-good state must be preserved;
- retries must not weaken invariants;
- user-visible external effects must not be duplicated merely to obtain a success response.

If a retry would cross a new boundary, stop and reclassify before acting.

---

## 17. Reference algorithm

```text
while task is not terminal:
    observe current state and latest failure

    failure_class = classify_failure(error, context)
    repeat_safety = classify_repeat_safety(operation)
    commit_state = determine_commit_state(operation, attempt, evidence)
    risk = classify_action_risk(operation, blast_radius)

    if failure_class == PERSISTENT:
        if no safe corrective action or changed precondition is available:
            BLOCKED
        apply_or_request_the_corrective_action_within_existing_authority()
        re-observe state
        continue

    if repeat_safety == NON_IDEMPOTENT and commit_state == UNKNOWN:
        commit_state = reconcile_state()

        if commit_state == COMMITTED:
            verify_real_outcome()
            verify_no_duplicate_side_effects()
            DONE

        if commit_state == UNKNOWN:
            BLOCKED

    if risk == HIGH and normal_authority_boundary_is_not_satisfied():
        BLOCKED

    if retry_budget_exhausted():
        BLOCKED

    if same_failure_three_times_without_new_evidence():
        reassess_hypothesis()
        if no evidence-backed tactic change is available:
            BLOCKED
        change_tactic_without_resetting_task_wide_budget()
        re-observe state
        continue

    result = retry_or_resume_using_provider_guidance()

    if result failed:
        re-observe state
        continue

    verify_real_outcome()
    verify_no_duplicate_side_effects()
    DONE
```

This is a decision skeleton, not permission to ignore system-specific semantics. The important control-flow rule is that a corrective action, tactic change, or failed retry returns to observation and classification rather than falling through on stale assumptions.

---

## 18. Completion contract

Report one of two terminal outcomes.

### DONE

Use only when the requested outcome has actually been verified.

Include proportionately:

```text
Result: DONE
Recovered from:
Failure class:
Repeat-safety class:
Attempts / retry window:
Commit state:
Tactic changes:
Verification:
Notable side effects: none | <details>
```

Do not report routine retry noise unless it matters.

### BLOCKED

Use when continuing would be unsafe, pointless, unauthorised, or unsupported by evidence.

```text
Result: BLOCKED
Failure class:
Repeat-safety class:
Commit state: COMMITTED | NOT_COMMITTED | UNKNOWN | NOT_APPLICABLE
Risk class:
Attempts made:
Evidence:
Why retry stopped:
Current safe state:
Next concrete action:
```

`BLOCKED` is better than duplicating a side effect, weakening an invariant, or hiding uncertainty.

---

## 19. Anti-patterns

Do not:

- retry a deterministic validation error;
- treat every `5xx` as indefinitely transient;
- create a new idempotency key for the same logical retry;
- infer `NOT_COMMITTED` merely because no response arrived;
- delete a lock without checking ownership or lease state;
- restart a resumable transfer from zero without reason;
- report success because the final transport attempt returned `200`;
- let multiple workers independently retry the same logical mutation without coordination;
- keep retrying because the budget has attempts left;
- hide a risky retry behind "automatic recovery";
- use retry logic to cross an approval or authority boundary.

---

## Operating rules

- **Completion matters more than first-attempt success.**
- **Transient does not mean safe to replay.**
- **Failure class, repeat safety, commit state, and action risk are separate dimensions.**
- **Classify repeat safety before replaying mutations.**
- **Unknown commit means reconcile before replaying non-idempotent work.**
- **Use the same idempotency identity for the same logical operation.**
- **Provider guidance outranks generic backoff.**
- **Retry budgets are finite.**
- **Three identical failures without new evidence trigger reassessment.**
- **Change tactic only when the hypothesis changes.**
- **Coordinate concurrent retries.**
- **Preserve useful partial progress, but inspect unknown partial state.**
- **Retry logic never grants new authority.**
- **Configured, acknowledged, or HTTP-successful is not the same as working.**
- **Verify the real outcome and check for duplicate side effects.**
- **Never hide risky operations behind automatic retry.**
