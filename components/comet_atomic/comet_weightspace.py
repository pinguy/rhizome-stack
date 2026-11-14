#!/usr/bin/env python3
"""Modern COMET-ATOMIC-2020 runtime with a WeightSpace probe."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path


STACK_ROOT = Path(os.environ.get(
    "RHIZOME_STACK_ROOT", Path(__file__).resolve().parents[2]
)).expanduser()
DEFAULT_MODEL_DIR = Path(os.environ.get(
    "COMET_ATOMIC_MODEL_DIR",
    STACK_ROOT / "models/comet-atomic/comet-bart-ai2",
)).expanduser()
WEIGHTS_SHA256 = "068ef0181830c81913f26a84404afa48035d5797c2fc33fd383b2f23251cc5f0"
WEIGHTS_SIZE = 1_625_695_432
RELATIONS = (
    "AtLocation", "CapableOf", "Causes", "CausesDesire", "CreatedBy",
    "DefinedAs", "Desires", "HasA", "HasFirstSubevent", "HasLastSubevent",
    "HasPrerequisite", "HasProperty", "HasSubEvent", "HinderedBy", "IsA",
    "LocatedNear", "MadeOf", "MotivatedByGoal", "NotCapableOf", "NotDesires",
    "NotHasA", "NotHasProperty", "NotIsA", "ObjectUse", "PartOf",
    "ReceivesAction", "RelatedTo", "SymbolOf", "UsedFor", "isAfter",
    "isBefore", "isFilledBy", "oEffect", "oReact", "oWant", "xAttr",
    "xEffect", "xIntent", "xNeed", "xReact", "xReason", "xWant",
)


def require_model(model_dir: Path) -> Path:
    required = ("config.json", "pytorch_model.bin", "vocab.json", "merges.txt", "added_tokens.json")
    missing = [name for name in required if not (model_dir / name).is_file()]
    if missing:
        raise SystemExit(f"model is incomplete at {model_dir}: missing {', '.join(missing)}")
    return model_dir / "pytorch_model.bin"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_model(model_dir: Path, requested: str):
    import torch
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

    require_model(model_dir)
    if requested == "auto":
        requested = "cuda" if torch.cuda.is_available() else "cpu"
    if requested.startswith("cuda") and not torch.cuda.is_available():
        raise SystemExit("CUDA was requested but torch.cuda.is_available() is false")
    tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
    model = AutoModelForSeq2SeqLM.from_pretrained(
        model_dir, local_files_only=True,
        dtype=torch.float16 if requested.startswith("cuda") else torch.float32,
    ).to(requested).eval()
    return model, tokenizer, requested


def generate(model, tokenizer, device: str, event: str, relation: str, count: int) -> list[str]:
    import torch

    if relation not in RELATIONS:
        raise SystemExit(f"unknown relation: {relation}")
    count = max(1, min(int(count), 10))
    batch = tokenizer([f"{event.strip()} {relation} [GEN]"], return_tensors="pt", truncation=True)
    batch = {name: value.to(device) for name, value in batch.items()}
    with torch.inference_mode():
        outputs = model.generate(
            **batch, decoder_start_token_id=model.config.decoder_start_token_id,
            num_beams=count, num_return_sequences=count, max_length=24,
            no_repeat_ngram_size=3, length_penalty=2.0, early_stopping=True,
        )
    return tokenizer.batch_decode(outputs, skip_special_tokens=True,
                                  clean_up_tokenization_spaces=False)


def make_probe(model, tokenizer, device: str):
    import weightspace as wsp

    @wsp.probe(cost=1)
    def comet_generate(event: str, relation: str, num_return_sequences: int = 5):
        """Generate COMET-ATOMIC-2020 tails for one event and relation."""
        return {"query": f"{event.strip()} {relation} [GEN]",
                "tails": generate(model, tokenizer, device, event, relation,
                                  num_return_sequences)}
    return comet_generate


def command_doctor(args) -> int:
    weights = require_model(args.model_dir)
    details = {
        "model_dir": str(args.model_dir), "weights_size": weights.stat().st_size,
        "weightspace": importlib.metadata.version("weightspace"),
        "torch": importlib.metadata.version("torch"),
        "transformers": importlib.metadata.version("transformers"),
    }
    if weights.stat().st_size != WEIGHTS_SIZE:
        raise SystemExit("COMET weight size mismatch")
    if args.checksum:
        details["weights_sha256"] = sha256(weights)
        if details["weights_sha256"] != WEIGHTS_SHA256:
            raise SystemExit("COMET weight SHA-256 mismatch")
    if args.deep:
        import weightspace as wsp
        model, tokenizer, device = load_model(args.model_dir, args.device)
        space = wsp.WeightSpace.from_torch(model)
        details.update(device=device, weightspace_tensors=len(space),
                       weightspace_parameters=space.numel(),
                       probe=make_probe(model, tokenizer, device)(
                           event="PersonX goes to the mall", relation="xIntent",
                           num_return_sequences=2))
    print(json.dumps(details, indent=2))
    return 0


def command_generate(args) -> int:
    model, tokenizer, device = load_model(args.model_dir, args.device)
    print(json.dumps({"query": f"{args.event.strip()} {args.relation} [GEN]", "device": device,
                      "tails": generate(model, tokenizer, device, args.event, args.relation, args.count)}, indent=2))
    return 0


def command_inspect(args) -> int:
    import weightspace as wsp
    weights = require_model(args.model_dir)
    space = wsp.WeightSpace.from_file(str(weights))
    names = space.names(args.pattern)
    for name in names[:args.limit]:
        print(space.describe(name) if args.describe else f"{name} {list(space.shape(name))} {space.dtype(name)}")
    print(f"shown={min(len(names), args.limit)} matched={len(names)} total={len(space)}")
    return 0


def command_weightspace(args) -> int:
    import weightspace as wsp
    model, tokenizer, device = load_model(args.model_dir, args.device)
    result = getattr(wsp, args.mode)(
        model, args.task, llm=args.llm,
        context=(Path(__file__).with_name("weightspace_context.md").read_text()),
        probes=[make_probe(model, tokenizer, device)], forward_budget=args.forward_budget,
        max_steps=args.max_steps, token_budget=args.max_tokens, time_budget=args.max_time,
        thinking=args.thinking, verbose=args.verbose,
    )
    print(result)
    if args.out:
        result.save(args.out)
    if args.save_model:
        destination = args.save_model.resolve()
        if destination == args.model_dir.resolve():
            raise SystemExit("refusing to overwrite the canonical base model")
        if destination.exists() and any(destination.iterdir()):
            raise SystemExit(f"save destination is not empty: {destination}")
        model.save_pretrained(destination, safe_serialization=True)
        tokenizer.save_pretrained(destination)
    return 0 if result.ok else 2


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="comet-atomic")
    root.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    commands = root.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor")
    doctor.add_argument("--checksum", action="store_true"); doctor.add_argument("--deep", action="store_true")
    doctor.add_argument("--device", default="cpu"); doctor.set_defaults(func=command_doctor)
    relations = commands.add_parser("relations"); relations.set_defaults(func=lambda _args: print("\n".join(RELATIONS)) or 0)
    gen = commands.add_parser("generate"); gen.add_argument("event"); gen.add_argument("relation", choices=RELATIONS)
    gen.add_argument("--count", type=int, default=5); gen.add_argument("--device", default="auto"); gen.set_defaults(func=command_generate)
    inspect = commands.add_parser("inspect"); inspect.add_argument("--pattern"); inspect.add_argument("--limit", type=int, default=40)
    inspect.add_argument("--describe", action="store_true"); inspect.set_defaults(func=command_inspect)
    ws = commands.add_parser("weightspace"); ws.add_argument("mode", choices=("read", "fix", "improve")); ws.add_argument("task")
    ws.add_argument("--llm", required=True); ws.add_argument("--device", default="auto"); ws.add_argument("--forward-budget", type=int, default=4)
    ws.add_argument("--max-steps", type=int, default=60); ws.add_argument("--max-tokens", type=int); ws.add_argument("--max-time", type=float)
    ws.add_argument("--thinking", choices=("off", "low", "medium", "high", "xhigh", "max")); ws.add_argument("--out", type=Path)
    ws.add_argument("--save-model", type=Path); ws.add_argument("-v", "--verbose", action="store_true"); ws.set_defaults(func=command_weightspace)
    return root


if __name__ == "__main__":
    args = parser().parse_args()
    raise SystemExit(args.func(args))
