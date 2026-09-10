"""Read-only Open WebUI tools for Rhizome memory and local book archives.

Install beside ``query_rhizomeml_archive.py`` (the improved hybrid query script)
or set RHIZOME_QUERY_SCRIPT to its absolute path.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any


TOOL_VERSION = "2.0.0"
DEFAULT_PYTHON = str(Path.home() / ".local/share/rhizome-stack/venvs/memory/bin/python")
DEFAULT_QUERY_SCRIPT = str(Path.home() / ".local/share/rhizome-stack/components/query_memory_archive.py")
CACHE_TTL_SECONDS = 180
MAX_STDERR_CHARS = 3000


class Tools:
    # Rhizome URIs and snippets are more useful than Open WebUI citation overlays.
    citation = False

    def __init__(self) -> None:
        self._cache: dict[tuple[str, ...], tuple[float, str]] = {}
        self._cache_lock = threading.Lock()

    @staticmethod
    def _python_path() -> str:
        configured = os.environ.get("RHIZOME_PYTHON", DEFAULT_PYTHON)
        return configured if Path(configured).exists() else "python3"

    @staticmethod
    def _query_script() -> str:
        return os.environ.get("RHIZOME_QUERY_SCRIPT", DEFAULT_QUERY_SCRIPT)

    def _cached(self, key: tuple[str, ...]) -> str | None:
        now = time.monotonic()
        with self._cache_lock:
            item = self._cache.get(key)
            if not item:
                return None
            created, payload = item
            if now - created > CACHE_TTL_SECONDS:
                self._cache.pop(key, None)
                return None
            return payload

    def _store_cache(self, key: tuple[str, ...], payload: str) -> None:
        with self._cache_lock:
            self._cache[key] = (time.monotonic(), payload)
            if len(self._cache) > 64:
                oldest = min(self._cache, key=lambda item: self._cache[item][0])
                self._cache.pop(oldest, None)

    @staticmethod
    def _normalise_payload(payload: dict[str, Any], archive: str) -> dict[str, Any]:
        payload = dict(payload)
        payload["openwebui_tool_version"] = TOOL_VERSION
        payload["requested_archive"] = archive
        payload["model_use_policy"] = {
            "memory_evidence": (
                "Treat a returned snippet as evidence of what was written or remembered, "
                "not independent proof that every claim inside it is factually correct."
            ),
            "conflicts": (
                "When retrieved memories disagree, show the disagreement and prefer a newer "
                "explicit correction over an older assumption."
            ),
            "context": (
                "Read adjacent_context before interpreting a clipped quote, especially where "
                "negation, sarcasm, attribution, or a later correction may change its meaning."
            ),
            "scope": (
                "Curated workspace memory is best for durable preferences and decisions; "
                "RhizomeML is best for historical conversation recall; book RAG is evidence "
                "from the local library rather than personal memory."
            ),
            "attribution": (
                "Never attribute a statement to a document's author (or any person) solely because "
                "it appears in that document. Use each result's provenance.text_type and "
                "provenance.attribution_risk. Treat 'narration' as presumptively authorial (may "
                "attribute, subject to context). 'quotation' and 'dialogue' are elevated risk — "
                "resolve the quoted speaker before attributing (dialogue can still be the author, e.g. "
                "an interview or letter). 'generated_or_simulated' is high risk — never attribute to "
                "the document author without explicit surrounding confirmation. Verify any strong "
                "attribution ('X argues Y') survives adjacent_context expansion before asserting it."
            ),
        }
        return payload

    def _run_archive_query(
        self,
        archive: str,
        query: str,
        *,
        k: int = 6,
        source: str = "all",
        author: str = "all",
        prefer_recent: bool = False,
        context_chunks: int = 1,
        snippet_chars: int = 1100,
        conversation_id: str | None = None,
    ) -> str:
        cleaned_query = " ".join(str(query or "").split())
        if not cleaned_query:
            return json.dumps(
                {
                    "ok": False,
                    "openwebui_tool_version": TOOL_VERSION,
                    "error": "empty query",
                },
                ensure_ascii=False,
            )

        safe_k = max(1, min(int(k or 8), 20))
        safe_context = max(0, min(int(context_chunks or 0), 2))
        safe_snippet = max(300, min(int(snippet_chars or 1100), 2200))
        command = [
            self._python_path(),
            self._query_script(),
            cleaned_query,
            "--archive", archive,
            "--source", source,
            "--author", author,
            "-k", str(safe_k),
            "--snippet-chars", str(safe_snippet),
            "--context-chunks", str(safe_context),
            "--max-per-parent", str(safe_k if conversation_id else 2),
            "--lexical", "auto",
        ]
        if prefer_recent:
            command.append("--prefer-recent")
        if conversation_id:
            command.extend(("--conversation-id", str(conversation_id)))

        cache_key = tuple(command)
        cached = self._cached(cache_key)
        if cached is not None:
            return cached

        try:
            run = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return json.dumps(
                {
                    "ok": False,
                    "openwebui_tool_version": TOOL_VERSION,
                    "archive": archive,
                    "error": "archive query timed out",
                    "timeout_seconds": 120,
                    "stderr": (exc.stderr or "")[-MAX_STDERR_CHARS:],
                },
                ensure_ascii=False,
            )
        except OSError as exc:
            return json.dumps(
                {
                    "ok": False,
                    "openwebui_tool_version": TOOL_VERSION,
                    "archive": archive,
                    "error": "archive query could not start",
                    "detail": str(exc),
                    "python": command[0],
                    "script": command[1],
                },
                ensure_ascii=False,
            )

        try:
            payload = json.loads(run.stdout)
        except (json.JSONDecodeError, TypeError):
            payload = {
                "ok": False,
                "error": "archive query returned invalid JSON",
                "returncode": run.returncode,
                "stdout_tail": (run.stdout or "")[-4000:],
                "stderr_tail": (run.stderr or "")[-MAX_STDERR_CHARS:],
            }
        if run.returncode != 0 and payload.get("ok") is not False:
            payload["ok"] = False
            payload["error"] = payload.get("error") or "archive query failed"
        if run.stderr:
            payload.setdefault("diagnostics", {})["stderr_tail"] = run.stderr[-MAX_STDERR_CHARS:]

        normalised = self._normalise_payload(payload, archive)
        result = json.dumps(normalised, ensure_ascii=False, indent=2)
        if normalised.get("ok"):
            self._store_cache(cache_key, result)
        return result

    def search_rhizome_memory(
        self,
        query: str,
        k: int = 6,
        source_kind: str = "all",
        prefer_recent: bool = False,
    ) -> str:
        """
        Search curated Rhizome workspace memory using hybrid semantic and exact-text retrieval.

        Use this first for durable preferences, prior decisions, local setup details,
        current project state, SESSION_NOTES, USER.md, MEMORY.md, and dated memory notes.
        Results include memory:// provenance and neighbouring context where available.

        source_kind may be all, long_term, workspace_context, daily_note,
        memory_note, or note. Set prefer_recent only when the user asks for the
        latest/current version of a remembered decision or setup.
        """
        allowed = {"all", "long_term", "workspace_context", "daily_note", "memory_note", "note"}
        if source_kind not in allowed:
            source_kind = "all"
        return self._run_archive_query(
            "workspace",
            query,
            k=k,
            source=source_kind,
            prefer_recent=prefer_recent,
            context_chunks=1,
            snippet_chars=1100,
        )

    def search_rhizomeml_archive(
        self,
        query: str,
        k: int = 6,
        source: str = "all",
        author: str = "all",
        prefer_recent: bool = False,
        conversation_id: str = "",
    ) -> str:
        """
        Search the large protected RhizomeML conversation/PDF archive.

        Use this for old conversations, exact past wording, prior model replies,
        historical project discussions, or proof that a particular memory chunk
        exists. Hybrid retrieval favours exact names/quotes without losing semantic
        matches and reconstructs adjacent chunks around the result.

        source may be all, conversation, or pdf. author may be all, user,
        assistant, or system. conversation_id can constrain a follow-up search to
        one previously returned conversation.
        """
        if source not in {"all", "conversation", "pdf"}:
            source = "all"
        if author not in {"all", "user", "assistant", "system"}:
            author = "all"
        return self._run_archive_query(
            "rhizomeml",
            query,
            k=k,
            source=source,
            author=author,
            prefer_recent=prefer_recent,
            context_chunks=1,
            snippet_chars=1300,
            conversation_id=conversation_id or None,
        )

    def search_book_rag(self, query: str, k: int = 8) -> str:
        """
        Search the local books/ethics archive with hybrid semantic and lexical retrieval.

        Use this for evidence or ideas grounded in books under the local RAG library,
        including Hofstadter, Shannon, McCulloch, Wiener, Feynman, Orwell, Sagan,
        cognition, ethics, cybernetics, information theory, and consciousness.
        These results are book evidence, not personal-memory claims. For broad or
        exploratory questions, use up to 20 results and make additional focused
        searches when one query does not cover enough distinct books or viewpoints.

        ATTRIBUTION: a passage appearing in a book does NOT mean its author endorses
        it. Use each result's provenance.text_type and attribution_risk. 'narration'
        is presumptively authorial; 'quotation'/'dialogue' are elevated risk (resolve
        the quoted speaker first — dialogue can still be the author, e.g. an interview);
        'generated_or_simulated' is high risk (never attribute to the author without
        surrounding confirmation). Confirm any "author argues X" against adjacent_context
        before stating it.
        """
        return self._run_archive_query(
            "books",
            query,
            k=k,
            source="all",
            author="all",
            prefer_recent=False,
            context_chunks=1,
            snippet_chars=1500,
        )
