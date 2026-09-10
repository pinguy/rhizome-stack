---
name: "local-model-runtime-profiler"
description: "Benchmark and validate local-model runtime profiles for real workloads with reproducible receipts and lifecycle states."
---

# Local Model Runtime Profiler

## Purpose

Find the best **proven** way to run an installed local model on the current machine for a named workload.

Do not assume that Ollama, llama.cpp, a particular context size, GPU layout, or aggressive tuning is best. Benchmark the real model on the real box, verify the real workload, and preserve enough evidence for another agent to reproduce the result later.

The result is not:

> fastest settings I happened to try

It is:

> **best validated profile for a named workload on the current hardware/software state**

A model may legitimately have multiple profiles, such as interactive chat, long-context work, coding/tool use, or background jobs.

## Core rules

### Quality before speed

**Never promote a profile from throughput alone.**

A profile is `KNOWN_GOOD` only when it:

- passes the workload quality/format gate;
- passes all hard operational constraints;
- genuinely proves the required context;
- survives repeated comparable runs;
- has measured performance/resource data;
- completes the real workload path;
- cleans up correctly; and
- has reproducible receipts.

A valid profile does **not** have to beat the incumbent to be `KNOWN_GOOD`. Validation and selection are separate.

### Evidence before labels

Separate evidence into:

```text
process evidence:
  what was actually run and measured

constraint evidence:
  no OOM/crash/truncation
  context/resource/ownership limits satisfied
  cleanup succeeded

outcome evidence:
  the real task passed its quality/format/behaviour gate
```

A passed procedure is not proof of a passed workload.

**Do not write unverified success into durable memory.**

### Allocation is not capability

“32K context allocated” does not prove “32K context works.”

A context claim is proven only when a prompt at or near that target is actually processed and the relevant workload checks pass without truncation or runtime failure.

### No hidden machine mutation

Do not silently kill processes, unload another workload, restart services, change drivers, alter system-wide configuration, or perform privileged operations.

If another workload occupies meaningful resources, mark `environment_state: CONSTRAINED` or clear it only through the normal ownership/approval path.

## Trigger

Use this skill when asked to find the best settings for a local model, benchmark runtimes, tune context/GPU offload/batching/cache behaviour, choose the best installed model for a real task, create or refresh a reusable runtime profile, or explain why a model is slower or no longer fits.

Do not benchmark generic prose and then claim a coding, tool-use, structured-output, diary, retrieval, or long-context workload is solved.

## Inputs

Identify or derive where possible:

```text
exact model file or Ollama identity
model hash / immutable ID
quantisation / precision
runtime(s)
intended workload
real prompt fixture or representative prompt suite
minimum useful context
reasoning/thinking requirement
sampling/generation settings
latency/throughput priority
allowed GPUs
resource headroom constraints
whether concurrency matters
whether benchmarking may disturb existing runners
benchmark/run budget if constrained
```

If the user already supplied an input, do not ask for it again.

If a field can be discovered safely from the machine, discover it. If it cannot be known, record it as unknown rather than inventing it.

## Phase 0 — Capture live state

Before changing anything, record where available:

```text
timestamp / timezone
hostname
OS / kernel
CPU
RAM
swap/zram
GPU model(s) and VRAM
GPU driver
CUDA/ROCm/runtime version if relevant
current GPU memory/utilisation
temperature / clocks / power state if available
Ollama version
llama.cpp build/version/commit
other runtime version(s)
model identity/path
model size
model hash / immutable ID
currently running model processes
relevant environment variables
```

Use live commands available on the machine.

Do not assume command syntax from memory when the installed runtime can report it. For llama.cpp, inspect the installed binary's `--help` before relying on version-sensitive flags. For Ollama, inspect the installed CLI/API and current model metadata.

### Environment fingerprint

Record a compact fingerprint of materially relevant state:

```text
model digest
runtime build/version
GPU(s)
driver/runtime version
OS/kernel
```

Use it to detect stale profiles. It is not a security identity.

### Foreign workload rule

If another process occupies meaningful GPU/CPU/RAM resources:

1. identify it as far as permissions allow;
2. do not silently kill, pause, unload, or reconfigure it;
3. mark `environment_state: CONSTRAINED`;
4. benchmark that constrained state deliberately, or clear it only through the normal ownership path.

A benchmark taken while an accidental stale/foreign runner owns most of the GPU is not evidence about normal performance.

## Phase 1 — Define the acceptance gate

Write the gate **before tuning**.

Example:

```text
Workload: interactive technical chat
Fixture: <prompt/suite identifier>
Minimum context: 32K actually exercised

Outcome gate:
  - answer complete
  - required constraints preserved
  - requested format valid
  - no invented machine state

Constraint gate:
  - no OOM/crash/hang/truncation
  - context target actually exercised
  - resource/ownership limits respected

Performance gate:
  - competitive with incumbent on the workload's primary metric
  - no unacceptable resource pressure

Operational gate:
  - unload/keep-alive behaviour correct
  - no orphan runner
```

For structured tasks, use deterministic validation where possible:

```text
schema/JSON parsing
compiler/tests
tool-call parser
required-field checks
known-answer checks
retrieval/needle checks
```

For subjective prose, use the same prompt suite across candidates and score only after mechanical failures are removed.

### Keep comparison conditions fixed

For comparable candidates, keep these equivalent:

```text
prompt/system template
sampling settings
output-token limit
reasoning mode
context requirement
concurrency/load
```

Fix the seed when supported and useful. If generation remains stochastic, use repeated prompt-suite runs rather than treating one sample as definitive.

## Phase 2 — Establish a baseline

Run the current/default setup or existing `KNOWN_GOOD` incumbent first unless doing so is impossible or unsafe.

Measure separately:

```text
exact command/API/config
cold load time
prompt-evaluation tokens/sec
generation tokens/sec
time to first generated token
total wall time
peak VRAM
peak system RAM
GPU utilisation
CPU utilisation
output tokens
stop reason
quality/validation result
cleanup/unload result
```

Keep stdout/stderr or equivalent runtime logs as receipts where practical.

For interactive workloads, TTFT may matter more than peak throughput.

For concurrent/batch workloads, also measure when relevant:

```text
requests/sec
concurrency
p50 latency
p95 latency
error rate
```

Do not compare single-user interactive and concurrent-serving results as though they were the same workload.

## Phase 3 — Sweep deliberately

Do not thrash random settings.

Change one meaningful dimension at a time during exploration so cause and effect remain interpretable. After promising values emerge, test the **combined candidate**, because settings can interact.

### Context

Test the smallest context that satisfies the workload first.

Typical candidate ladder:

```text
8K → 16K → 32K → 64K → larger only when needed
```

Do not maximise context merely because the runtime can allocate it. Large KV caches can destroy throughput, latency, and fit.

Every claimed context profile must complete an actual acceptance run at or near that context target.

### GPU placement / offload

Test the simplest useful placement first.

Prefer a single primary compute GPU when the model fits and measured performance/operational simplicity support it.

Test multi-GPU placement when the model does not fit acceptably, required context forces it, concurrency requires it, or measurement shows a real benefit.

Do not assume splitting across a slower/display GPU is automatically faster.

### Batch / micro-batch

Sweep a small number of sensible values around the working point.

Stop increasing when throughput stops improving materially, latency worsens for the workload, resource headroom becomes unsafe, or instability appears.

### CPU threads

When CPU participation matters, test a small number of sensible thread counts. Do not blindly equate logical cores with the optimal setting.

### llama.cpp-specific candidates

Only test flags supported by the installed build. Candidate dimensions can include:

```text
GPU layers / full offload
context
batch / micro-batch
flash attention
KV-cache type/precision/offload
CPU threads
GPU/tensor split
parallel slots / concurrency
```

Do not enable exotic cache/split modes merely to win a synthetic benchmark. They must pass the same workload and stability gate.

### Ollama-specific candidates

Inspect the installed version and supported options first.

Candidate dimensions commonly include:

```text
context
batching
GPU allocation/offload
reasoning/thinking mode if supported
parallelism if exposed
keep-alive / unload behaviour
```

When Ollama does not expose a useful control, record that limitation rather than inventing a hidden setting.

## Phase 4 — Repeatable measurement

For a serious candidate:

1. run one cold test;
2. perform one warm-up run if the runtime needs it, recorded separately;
3. run at least three comparable steady-state tests;
4. record individual values;
5. use the **median** as the primary steady-state figure;
6. record spread/variance.

Run more samples when observed variance is large enough to change the decision.

Do not average cold and warm runs into one flattering number.

### Order and thermal bias

Candidate order can distort results through cache state, GPU boost, thermal throttling, background activity, or compilation/warm-up effects.

For serious finalists, alternate/interleave incumbent and challenger where practical and keep thermal/power conditions comparable.

Rerun suspicious outliers.

A challenger should not win because it happened to run on a cold GPU while the incumbent ran heat-soaked.

## Phase 5 — Quality and context before speed

Reject or downgrade a candidate for:

```text
invalid format
truncation
hallucinated machine state
missed hard constraints
broken tool syntax
unexpected reasoning leakage
material quality regression
context failure
OOM / crash / hung runner
cleanup failure
unauthorised resource interference
```

Keep the failure receipt. Negative evidence is useful evidence.

### Context proof

Record:

```text
configured context
actual input tokens
actual output tokens
stop reason
whether truncation occurred
validator/recall result
```

For long-context retrieval/analysis, use representative content or recall checks, not filler tokens alone.

### Quality proof

Run the real validation defined in Phase 1.

For coding, run tests/compilers where available.

For tool use, validate actual tool syntax/parser behaviour.

For structured output, parse it.

For retrieval, test retrieval.

Do not substitute “looks fine” when a mechanical validator exists.

## Phase 6 — Compare equivalent evidence

An incumbent/challenger comparison is equivalent only when materially relevant conditions match:

```text
model/quant unless model choice itself is under test
prompt fixture
system/template
context requirement
reasoning mode
sampling settings
concurrency/load
hardware availability
foreign workload state
measurement method
quality gate
```

If they do not match, label the comparison non-equivalent and explain why.

### Meaningful advantage

Do not replace an incumbent for a tiny benchmark wiggle.

A challenger provides a meaningful advantage when the improvement:

- exceeds ordinary run-to-run noise;
- matters to the named workload; and
- does not buy speed by violating quality, context, stability, ownership, or operational simplicity.

A slower-throughput profile may still be preferable when it materially improves TTFT, tail latency, context, memory headroom, reliability, or quality.

## Phase 7 — Selection rule

Use this order unless the workload contract explicitly changes it:

```text
1. passes outcome/quality gate
2. passes hard constraints
3. stable and repeatable
4. proves required context
5. obeys resource/ownership limits
6. best primary workload metric
7. better secondary latency/throughput
8. healthier VRAM/RAM headroom
9. simpler operational behaviour
```

Do not hide a trade-off behind a single score.

Keep multiple `KNOWN_GOOD` profiles when they serve genuinely different workloads.

Selection is recorded separately as:

```text
WINNER
INCUMBENT_RETAINED
ALTERNATE
NONE
```

## Phase 8 — Real acceptance run

Before calling a profile `KNOWN_GOOD`, run the **real user-facing workload path**, not only a synthetic benchmark.

Examples:

```text
real chat request
real coding prompt + tests
real diary prompt
real agent/tool-use request
real long-context document
real scheduler/background job
real concurrent request pattern
```

Verify what the user actually experiences.

```text
"server started"   != acceptance
"model loaded"     != acceptance
"allocated 32K"    != context proof
"generated tokens" != quality proof
"one fast run"     != repeatability
```

## Phase 9 — Cleanup check

After each serious test and final acceptance:

- confirm no orphan benchmark process remains;
- confirm intended unload/keep-alive behaviour;
- confirm GPU/RAM returns to the expected state;
- confirm unrelated services/processes remain intact;
- restore temporary changes unless the accepted profile intentionally requires them;
- record anything that could not be restored.

Any privileged restart or service mutation must follow the normal privileged-operations boundary.

A benchmark is not complete if it leaves the machine in a mystery state.

## Lifecycle states

Keep lifecycle, environment, and job outcome separate.

### Validation/lifecycle state

`CANDIDATE`: proposed or promising, but not fully tested.

`PARTIAL`: meaningful evidence exists, but one or more required evidence layers remain incomplete.

`KNOWN_GOOD`: passed real-workload outcome, hard constraints, context proof, repeatability, measurement, and cleanup with reproducible receipts.

`FAILED`: failed a required validation or operational gate. Record why.

`STALE`: previously valid, but the environment/workload changed enough that revalidation is required.

`REGRESSED`: a comparable retest shows a previously known-good profile no longer reproduces its former result.

### Environment state

`NORMAL`: intended baseline machine state.

`CONSTRAINED`: abnormal or deliberately limited resources were present. Do not compare directly with `NORMAL` results without qualification.

A constrained profile can still be `KNOWN_GOOD` for that constrained environment.

### Job outcome

`COMPLETE`: required evidence was collected and a result was reached.

`BLOCKED`: required evidence could not be collected safely or at all.

Do not force environment conditions or job outcomes into the profile validation state.

## Reproducible receipts

Every serious run should record:

```text
run ID
timestamp
environment fingerprint
model identity/digest
runtime version/build
exact command or API request
relevant environment variables
runtime settings
prompt fixture ID/hash
acceptance-gate ID/hash where practical
system/template identity
sampling settings and seed where supported
input/output token counts
timing/resource metrics
stop reason
validator results
exit code
stdout/stderr or log path
cleanup result
```

If receipts contain secrets or private content, redact the sensitive payload while preserving enough metadata/hash information to identify the fixture/configuration.

Do not redact inconvenient failures.

## Runtime profile format

Write a profile only from measured evidence.

Suggested YAML:

```yaml
profile_version: 2

identity:
  profile_id: "<model>__<workload>__<hardware>"
  model_name: "<human name>"
  model_source: "<GGUF path or Ollama identity>"
  model_hash: "<hash or immutable ID>"
  quant: "<quantisation>"
  runtime: "<llama.cpp | ollama | other>"
  runtime_version: "<version/build/commit>"
  created_at: "<ISO timestamp>"
  environment_fingerprint: "<digest or canonical ID>"

hardware:
  cpu: "<CPU>"
  ram_gib: 0
  gpus:
    - gpu: "<GPU>"
      vram_mib: 0
      role: "<compute | display | mixed>"
  driver: "<driver>"
  accelerator_runtime: "<CUDA/ROCm/etc>"

workload:
  name: "<interactive-chat / coding / tool-use / long-context / batch / etc>"
  fixture: "<path or identifier>"
  fixture_hash: "<hash if practical>"
  minimum_context: 0
  context_tested_tokens: 0
  thinking: "<on | off | n/a>"
  acceptance_gate: "<path or short description>"
  primary_metric: "<generation_tps | ttft | p95_latency | requests_per_sec | etc>"
  concurrency: 1

settings:
  context: 0
  batch: null
  micro_batch: null
  gpu_layers: null
  gpu_split: null
  flash_attention: null
  kv_cache: null
  kv_offload: null
  cpu_threads: null
  parallel_slots: null
  sampling: {}
  extra_args: []
  environment: {}

results:
  cold_load_seconds: null
  prompt_tps_runs: []
  prompt_tps_median: null
  generation_tps_runs: []
  generation_tps_median: null
  ttft_seconds_runs: []
  ttft_seconds_median: null
  p50_latency_seconds: null
  p95_latency_seconds: null
  requests_per_second: null
  peak_vram_mib: null
  peak_ram_mib: null
  output_tokens_runs: []
  stop_reasons: []
  process_evidence: "PASS | FAIL"
  constraint_evidence: "PASS | FAIL"
  outcome_evidence: "PASS | FAIL"
  stability: "PASS | FAIL"
  context_proof: "PASS | FAIL"
  cleanup: "PASS | FAIL"

status: "KNOWN_GOOD | CANDIDATE | PARTIAL | FAILED | STALE | REGRESSED"
environment_state: "NORMAL | CONSTRAINED"
selection: "WINNER | INCUMBENT_RETAINED | ALTERNATE | NONE"
job_outcome: "COMPLETE | BLOCKED"

receipts:
  directory: "<path>"
  run_ids: []

notes:
  - "<important trade-offs only>"
```

Leave unknown values `null`/unknown. Do not fill missing evidence with estimates unless explicitly marked as estimated.

## Incumbent/challenger rule

If a `KNOWN_GOOD` profile already exists for the same workload:

1. treat it as the incumbent;
2. reproduce it first when the environment materially changed or its evidence is uncertain;
3. test challengers under equivalent conditions;
4. require challengers to pass the same gate;
5. replace the incumbent only for a meaningful workload advantage.

If the incumbent still passes and the challenger does not materially improve the workload, retain the incumbent.

Fashion is not evidence.

If a comparable retest shows the incumbent no longer reproduces, mark it `REGRESSED`. If changed conditions make the old result non-comparable, mark it `STALE`.

Preserve historical receipts.

## Profile invalidation

Revalidate when materially relevant state changes:

```text
model file/digest/quant
runtime version/build
GPU driver/runtime/hardware
RAM
OS/kernel behaviour
runtime defaults
prompt/template/fixture
acceptance gate
required context
reasoning mode
sampling behaviour
concurrency
power/performance policy
```

A changed environment does not prove the old profile was wrong. It proves the old profile belongs to an older state.

## Search budget and stopping rule

Do not benchmark forever.

Stop when:

```text
a candidate clearly passes and meaningfully beats the incumbent
further changes do not improve beyond observed noise
resource pressure becomes unsafe
remaining dimensions are irrelevant
the agreed run/disturbance budget is exhausted
the job becomes BLOCKED
```

If profiles remain effectively tied, prefer the simpler/safer one and record the tie.

Do not manufacture precision the measurements do not support.

## Final report

A completed profiling job must state:

```text
Model:
Workload:
Environment:
Incumbent:
Selected profile:
Selection outcome:
Runtime:
Exact settings:
Context configured:
Context actually proven:
Primary performance metric:
Median generation speed:
TTFT/latency where relevant:
Peak VRAM/RAM:
Outcome/quality gate:
Constraint gate:
Stability:
Cleanup:
Rejected candidates and why:
Known-good alternates:
Profile written to:
Raw receipts:
Remaining caveats:
```

If no candidate passes, report `FAILED`.

If required evidence cannot be collected, report `BLOCKED`.

Do not choose a winner merely to finish the task.

## Operational principle

The objective is not maximum benchmark theatre.

The objective is a profile another agent can safely reuse later without rediscovering the whole path or inheriting a false success.

**Fast is useful. Proven is reusable. Reproducible is durable.**
