"""Text-only readers for conversation exports and RhizomeML interchange files.

Formats checked against RhizomeML batch_embedder.py, pdf_to_json.py and
data_formatter.py at 746223badfa946f15dd955c03616624e5a31026b.
No training code, binary index or pickled input is executed by these readers.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path


def text_content(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n".join(part for item in value if (part := text_content(item)))
    if isinstance(value, dict):
        # Ignore image/audio/tool blocks rather than indexing their Python repr.
        if value.get("type") not in {None, "text", "input_text", "output_text"}:
            return ""
        return text_content(value.get("parts", value.get("text", "")))
    return ""


def records(value: object, record: str = "", context: dict | None = None):
    context = dict(context or {})
    if isinstance(value, list):
        for number, item in enumerate(value):
            yield from records(item, f"{record}/{number}", context)
        return
    if not isinstance(value, dict):
        return

    # Exported conversations have a stable ID above the individual messages.
    if any(key in value for key in ("mapping", "messages", "chat_messages")):
        context.update({
            "source": "conversation",
            "conversation_id": value.get("conversation_id") or value.get("uuid") or value.get("id") or record,
            "title": value.get("title") or value.get("name") or "",
        })
        if isinstance(value.get("mapping"), dict):
            # Keep every exported branch, with parent IDs, rather than silently
            # discarding alternative replies or pretending they were one chain.
            for node_id, node in value["mapping"].items():
                if isinstance(node, dict) and isinstance(node.get("message"), dict):
                    yield from records(node["message"], f"{record}/mapping/{node_id}", {
                        **context, "message_id": node_id, "parent_id": node.get("parent"),
                    })
        else:
            yield from records(value.get("chat_messages", value.get("messages")), record + "/messages", context)
        return

    # RhizomeML PDF output provides per-page text as well as a duplicate total.
    if "filename" in value and any(key in value for key in ("pages", "total_text", "text")):
        metadata = {**context, "source": "pdf", "filename": value["filename"],
                    "document_id": value.get("document_id") or value["filename"]}
        pages = value.get("pages")
        if isinstance(pages, list) and pages:
            for number, page in enumerate(pages, 1):
                if isinstance(page, dict) and (text := text_content(page.get("text"))):
                    yield text, {**metadata, "page": page.get("page", number), "record": record}
        elif text := text_content(value.get("total_text", value.get("text"))):
            yield text, {**metadata, "record": record}
        return

    metadata = {**context, "record": record}
    if isinstance(value.get("source_metadata"), dict):
        metadata.update(value["source_metadata"])
    if isinstance(value.get("quality_metrics"), dict):
        metadata["quality_metrics"] = value["quality_metrics"]
    # Detailed RhizomeML rows contain both roles plus a duplicate training text.
    if "user" in value or "assistant" in value:
        for role in ("user", "assistant"):
            if text := text_content(value.get(role)):
                yield f"{role}: {text}", {**metadata, "source": metadata.get("source", "conversation"),
                                         "role": role, "author": role}
        return
    # Compact training rows: text + source_metadata, preserving special tokens.
    if "source_metadata" in value and (text := text_content(value.get("text"))):
        yield text, metadata
        return

    author = value.get("author")
    role = value.get("role") or value.get("sender") or (author.get("role") if isinstance(author, dict) else author)
    if role:
        content = text_content(value.get("content")) or text_content(value.get("text"))
        if content:
            role = str(role)
            timestamp = next((value[key] for key in ("create_time", "created_at", "timestamp", "time")
                              if value.get(key) is not None), None)
            yield f"{role}: {content}", {
                **metadata, "source": "conversation", "role": role, "author": role,
                "message_id": value.get("id") or value.get("uuid") or metadata.get("message_id", record),
                "timestamp": timestamp,
            }
        return
    for key, item in value.items():
        if isinstance(item, (dict, list)):
            yield from records(item, f"{record}/{key}", context)


def structured_records(path: Path):
    opener = gzip.open if path.suffix.lower() == ".gz" else open
    suffix = Path(path.stem).suffix.lower() if path.suffix.lower() == ".gz" else path.suffix.lower()
    with opener(path, "rt", encoding="utf-8-sig") as stream:
        if suffix == ".jsonl":
            for number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path.name}: invalid JSONL at line {number}") from exc
                yield from records(value, f"/line/{number}")
        else:
            yield from records(json.load(stream))
