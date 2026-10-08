# Optional GLiNER advice and Ornith workforce

Rhizome owns orchestration, permissions, tools, verification and the final
answer. GLiNER2.5-Decide supplies optional classification signals. Ornith is a
bounded local text worker. Neither component receives authority to change the
stack.

| Layer | Responsibility | Authority |
| --- | --- | --- |
| Owner | Goals, corrections and priorities | Defines scope and permissions |
| Rhizome | Context, tools, dispatch and verification | Supervises the job |
| GLiNER2.5-Decide | Optional narrow task-category hints | Advisory only |
| Ornith | Bounded work on supplied text | Tool-free worker |
| Stronger configured models | Difficult reasoning, coding and consequential judgement | Work under Rhizome's control |

## Implemented boundary

`rhizome-stack workforce route` reads one JSON request from stdin. In `shadow`
mode it returns a structured proposal while the effective route remains
`rhizome`. Deterministic callers can supply an explicit route. Invalid,
uncertain, overlong or unavailable classification abstains.

`rhizome-stack workforce run` submits one bounded job to one exact loopback
model with no tools. It uses a single local lock and no automatic retries. A
normal response is `AWAITING_VERIFICATION`; model substitution and tool calls
are rejected. A client timeout is `UNKNOWN`, because the server may still be
working. Job and attempt IDs are correlation receipts, not a durable queue.

The optional resident classifier is a loopback-only helper, not a dispatcher.
It owns a single process lock and serialises inference through a bounded queue.
Background shadow submissions return immediately and skip when the queue is
full. Assisted jobs have a short classification budget and fall back to the
structured unassisted prompt when classification is unavailable.

There is no automatic browser routing, gateway interception, autonomous
dispatcher or automatic semantic acceptance. The normal Open WebUI → adapter →
OpenClaw path is unchanged.

## Install and configure

Preview the optional routing environment first:

```bash
./install-linux.sh --dry-run --with-routing
./install-linux.sh --with-routing
```

This installs CPU PyTorch and the pinned reviewed GLiNER2 source into
`venvs/routing`. It does not fetch checkpoint weights, enable routing, start a
service or configure CUDA. `--skip-runtime` skips this environment.

Copy the example private configuration after installation:

```bash
mkdir -p ~/.config/rhizome-stack
cp -n ~/.local/share/rhizome-stack/config/workforce.example.json \
  ~/.config/rhizome-stack/workforce.json
chmod 600 ~/.config/rhizome-stack/workforce.json
```

The example starts with `mode: "off"`. Set the exact local Ornith model ID and
measured limits. Only HTTP loopback IP endpoints are accepted; credentials,
redirects and inherited HTTP proxies are refused. Ollama and model weights are
installed separately.

The verified profiles in the example are specific to `ornith-1.5:35b` on the
reference machine: 8,192 context / batch 512 for ordinary jobs and 131,072 /
batch 1,024 for long jobs, with a 163,840 hard ceiling. They are evidence, not
universal defaults for another model or machine.

## GLiNER modes

Stage a complete local snapshot of
[`fastino/GLiNER2.5-Decide`](https://huggingface.co/fastino/GLiNER2.5-Decide),
including encoder and tokenizer assets. Set `gliner.model_path` and
`gliner.python` to absolute local paths. Loading is forced offline; missing
assets cause abstention rather than a download.

`device` may be `cpu` or `cuda`. For one-shot CUDA classification,
`cuda_visible_devices` selects the physical GPU exposed to the isolated child.
The bundled routing environment is CPU-only. A CUDA deployment needs a separate
compatible Python environment and, for the resident service, a systemd
`ExecStart` override pointing at that environment.

Use `mode: "shadow"` first. The default `narrow_categories_v1` scheme classifies
only extraction, summarisation, reformatting, comparison and other/uncertain.
Rhizome supplies observed context separately. Tools, difficult reasoning,
coding, vision, consequential work and missing material bypass classification.
Scores are uncalibrated support values, not probabilities or permissions.

For warm bounded experiments, set `resident_enabled: true`, then start the
staged service explicitly:

```bash
systemctl --user daemon-reload
systemctl --user start rhizome-gliner-resident.service
```

The installer does not enable or start it. The service refuses non-loopback
binding, uses a single-instance lock and obeys the configured CPU/CUDA device
selection before loading the model.

## Worker jobs

Send a synthetic canary through stdin:

```bash
rhizome-stack workforce run <<'JSON'
{"job_id":"canary-1","attempt_id":"canary-1-a1","task":"Summarise in one sentence.","acceptance":"Preserve the supplied fact without adding claims.","input":"The adapter preserves the selected model during retries."}
JSON
```

`context_profile` may be `auto`, `default` or `long`; explicit job limits can
only reduce the configured ceilings. Oversized inputs fail rather than being
silently truncated. Changing context allocation may reload an Ollama runner, so
callers should avoid arbitrary sizes.

`prompt_mode` may be `existing`, `structured`, experimental `gliner_assisted`,
`retrieval_assisted`, or `combined_assisted`. Assistance contains only category hints and separately
labelled Rhizome-observed context. Original request and supplied material are
always retained.

Ollama jobs may supply a bounded `output_schema`; the helper sends it through
the runtime's JSON Schema `format` field and validates the returned structure.
Optional deterministic assembly can preserve exact strings while retaining the
raw worker claim separately. Structural success never establishes semantic
correctness or marks the job accepted.

After a client timeout the helper writes an unresolved marker and blocks later
jobs. Reconcile or explicitly stop the exact backend runner before clearing only
that marker. Do not infer cancellation from the timeout.

## Reference acceptance and limits

The reference-machine trial used checkpoint revision
`5a7adf72a23b4d311abae6ce050d7f0012bb3416`; its 1,945,828,140-byte weights file
matched SHA-256
`40a5a23ff860dc3dff426cecd1048cacdd29c648c96db209dad818e9686dc997`.

A small held-out routing trial scored 23/24 exact for the narrow flow versus
17/24 for the older mixed taxonomy. Six direct, difficult or missing-context
cases bypassed GLiNER. The sample was small and hand-authored, so this supports
continued shadow evaluation, not production dispatch.

The resident GTX 1660 trial loaded in roughly 11–12 seconds, used about 2 GiB of
VRAM and completed subsequent classifications in roughly 76–696 ms. A separate
eight-case worker trial found no completion-quality gain from GLiNER assistance
over the structured wrapper alone. Resident assistance therefore remains an
explicit experiment, disabled by default.

Repository tests use mocks and local HTTP fixtures. They verify lifecycle,
abstention, exact model identity, tool rejection, timeout quarantine, structural
checks, packaging and preservation; they do not establish model quality on a
new target.

```bash
python3 tests/test_static.py
python3 tests/test_behaviour.py
python3 tests/test_workforce.py
```

Rollback is immediate: set `mode` to `off`, stop
`rhizome-gliner-resident.service`, and stop invoking `workforce run`. Existing
browser and provider routing remain available.

## Optional MiniLM support retrieval

`--with-retrieval` installs CPU PyTorch and
`sentence-transformers/all-MiniLM-L6-v2` at exact revision
`1110a243fdf4706b3f48f1d95db1a4f5529b4d41`. It enables a loopback-only
service in the private workforce configuration but does not start it:

```bash
./install-linux.sh --dry-run --with-retrieval
./install-linux.sh --with-retrieval
systemctl --user start rhizome-workforce-retrieval.service
```

The service uses 384-dimensional, L2-normalised embeddings on CPU with four
threads. Its corpus is public, versioned stack guidance only. Current requests
and supplied material remain authoritative. TF-IDF and hybrid experiments are
deliberately not shipped because they did not beat the simpler MiniLM path.
