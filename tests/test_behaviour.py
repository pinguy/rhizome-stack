"""Regression tests for the user-facing import, setup and installation paths."""

from __future__ import annotations

import gzip
import contextlib
import io
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import import_formats
import import_owner_data as importer
import install as installer
import skills
import welcome
import privacy_audit


class FormatsTest(unittest.TestCase):
    def test_real_chatgpt_export_preserves_branch_and_timestamp(self):
        payload = [{"id": "conversation-1", "title": "Demo", "mapping": {
            "root": {"message": None, "parent": None},
            "one": {"parent": "root", "message": {
                "id": "message-1", "author": {"role": "user"}, "create_time": 0,
                "content": {"content_type": "multimodal_text", "parts": [
                    "Keep this text", {"type": "image", "asset_pointer": "private-image"},
                ]}}},
            "two": {"parent": "one", "message": {
                "author": {"role": "assistant"}, "content": {"parts": ["An answer"]}}},
        }}]
        rows = list(import_formats.records(payload))
        self.assertEqual([text for text, _ in rows], ["user: Keep this text", "assistant: An answer"])
        self.assertEqual(rows[0][1]["timestamp"], 0)
        self.assertEqual(rows[1][1]["parent_id"], "one")
        self.assertEqual(rows[0][1]["conversation_id"], "conversation-1")

    def test_claude_uses_text_blocks_once(self):
        rows = list(import_formats.records([{"uuid": "c1", "chat_messages": [{
            "uuid": "m1", "sender": "human", "created_at": "2026-01-01T00:00:00Z",
            "text": "Hello", "content": [{"type": "text", "text": "Hello"},
                                       {"type": "tool_use", "name": "ignore"}],
        }]}]))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "human: Hello")
        self.assertEqual(rows[0][1]["message_id"], "m1")

    def test_rhizomeml_pairs_pages_and_compact_rows(self):
        payload = [
            {"user": "Question", "assistant": "Answer", "text": "duplicate training text",
             "source_metadata": {"themes": ["engineering"]}, "quality_metrics": {"quality_score": 0.8}},
            {"filename": "manual.pdf", "total_text": "duplicate", "pages": [{"page": 3, "text": "Page content"}]},
            {"text": "<|user|>Question<|assistant|>Answer", "source_metadata": {"source": "conversation"}},
        ]
        rows = list(import_formats.records(payload))
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0][1]["themes"], ["engineering"])
        self.assertEqual(rows[0][1]["quality_metrics"]["quality_score"], 0.8)
        self.assertEqual(rows[2][1]["page"], 3)
        self.assertNotIn("duplicate", " ".join(text for text, _ in rows))


class ImportTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.corpus = self.root / "stack/memory/owner-imports"
        self.scope = patch.multiple(importer, ROOT=self.corpus.parent, CORPUS=self.corpus,
                                    ARCHIVE=self.corpus.parent / "archive")
        self.scope.start()
        self.addCleanup(self.scope.stop)

    def test_gzip_preview_and_duplicate_provenance(self):
        source = self.root / "memory.jsonl.gz"
        with gzip.open(source, "wt") as stream:
            for conversation in ("first", "second"):
                stream.write(json.dumps({"user": "Same text", "source_metadata": {
                    "conversation_id": conversation, "source": "conversation"}}) + "\n")
        self.assertEqual(importer.import_source(source, "rhizomeml", True), 1)
        self.assertFalse(self.corpus.exists())
        self.assertEqual(importer.import_source(source, "rhizomeml"), 1)
        self.assertEqual(importer.import_source(source, "rhizomeml"), 0)
        saved = json.loads(next(self.corpus.glob("*.json")).read_text())
        self.assertEqual(len(saved["origins"]), 2)
        self.assertEqual(next(self.corpus.glob("*.json")).stat().st_mode & 0o777, 0o600)

    def test_zip_traversal_rejected(self):
        source = self.root / "export.zip"
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("../escape.txt", "must not escape")
        with self.assertRaisesRegex(RuntimeError, "unsafe path"):
            importer.import_source(source, "auto")
        self.assertFalse((self.root / "escape.txt").exists())

    def test_bad_jsonl_reports_line(self):
        source = self.root / "bad.jsonl"
        source.write_text('{"user":"valid"}\n{invalid}\n')
        with self.assertRaisesRegex(ValueError, "line 2"):
            list(import_formats.structured_records(source))

    def test_cli_dry_run_uses_explicit_stack_root_without_writes(self):
        source = self.root / "note.md"
        source.write_text("A note for a preview.")
        destination = self.root / "new-stack"
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools/import_owner_data.py"), str(source), "--dry-run"],
            env={**os.environ, "RHIZOME_STACK_ROOT": str(destination)}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("would import 1", result.stdout)
        self.assertFalse(destination.exists())

    @unittest.skipUnless(importlib.util.find_spec("faiss"), "optional FAISS generation check: install memory dependencies")
    def test_index_generation_preserves_ids_and_previous_snapshot(self):
        import faiss
        import numpy as np
        # Deterministic vectors exercise real FAISS persistence without a model
        # download. This verifies storage, not embedding quality.
        class Encoder:
            def __init__(self, *args, **kwargs):
                pass
            def encode(self, texts, **kwargs):
                vectors = np.zeros((len(texts), 384), dtype="float32")
                vectors[:, 0] = 1
                return vectors
        source = self.root / "first.txt"
        source.write_text("First stored memory")
        importer.import_source(source, "documents")
        with patch.dict(sys.modules, {"sentence_transformers": types.SimpleNamespace(SentenceTransformer=Encoder)}):
            self.assertEqual(importer.build_index(), 1)
            old = importer.ARCHIVE.resolve()
            import pickle
            old_meta = pickle.loads((old / "memory_metadata.pkl").read_bytes())
            (old / "memory_manual_adjustments.json").write_text('{"0": 0.5}')
            source.write_text("Second stored memory")
            importer.import_source(source, "documents")
            self.assertEqual(importer.build_index(), 2)
            new = importer.ARCHIVE.resolve()
            self.assertNotEqual(old, new)
            self.assertEqual(faiss.read_index(str(old / "memory.index")).ntotal, 1)
            self.assertEqual(faiss.read_index(str(new / "memory.index")).ntotal, 2)
            self.assertEqual(pickle.loads((new / "memory_metadata.pkl").read_bytes())[0]["id"], old_meta[0]["id"])
            self.assertEqual(json.loads((new / "memory_manual_adjustments.json").read_text()), {"0": 0.5})
            # A failed embedding cannot replace a working generation.
            with patch.object(Encoder, "encode", side_effect=RuntimeError("encoding failed")):
                with self.assertRaises(RuntimeError):
                    importer.build_index()
            self.assertEqual(importer.ARCHIVE.resolve(), new)


class SetupTest(unittest.TestCase):
    def test_release_allow_list_excludes_unlisted_private_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            (source / "tools").mkdir(parents=True)
            (source / "manifests").mkdir()
            approved = ["tools/privacy_audit.py", "tools/verify_release.py",
                        "manifests/release-files.json", "approved.txt"]
            for name in approved[:2]:
                shutil.copy2(ROOT / name, source / name)
            (source / "manifests/release-files.json").write_text(json.dumps({"schema": 1, "files": approved}))
            (source / "approved.txt").write_text("Public documentation")
            (source / "unlisted-private.txt").write_text("sk-" + "x" * 30)
            output = root / "release"
            result = subprocess.run(
                [sys.executable, str(ROOT / "tools/export_release.py"),
                 "--source-root", str(source), "--output", str(output)], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((output / "approved.txt").exists())
            self.assertFalse((output / "unlisted-private.txt").exists())

    def test_public_repo_attribution_does_not_hide_private_paths_or_keys(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            example = root / "example.md"
            owner = "ping" + "uy"
            example.write_text(f'{{"repository":"https://github.com/{owner}/Skills"}}')
            self.assertEqual(privacy_audit.audit(root), [])
            example.write_text(f"https://github.com/{owner}/Skills\n/home/{owner}/private\n")
            self.assertTrue(any("reference home path" in item for item in privacy_audit.audit(root)))
            example.write_text(f"https://github.com/{owner}/Skills\n" + "sk-" + "x" * 30)
            self.assertTrue(any("OpenAI-style key" in item for item in privacy_audit.audit(root)))

    def test_installed_cli_and_optional_installer_have_their_resources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stack = root / "stack"
            with patch.object(installer, "STACK_ROOT", stack), contextlib.redirect_stdout(io.StringIO()):
                installer.install_components(installer.Runner(False))
            env = {**os.environ, "RHIZOME_STACK_ROOT": str(stack), "XDG_CONFIG_HOME": str(root / "config")}
            listed = subprocess.run(["bash", str(stack / "bin/rhizome-stack"), "skills", "list"],
                                    env=env, text=True, capture_output=True)
            self.assertEqual(listed.returncode, 0, listed.stderr)
            self.assertIn("session-handover", listed.stdout)
            optional = subprocess.run(
                [sys.executable, str(stack / "tools/install.py"), "--target", "linux",
                 "--skip-runtime", "--skip-packages", "--dry-run", "--with-skills"],
                env=env, text=True, capture_output=True)
            self.assertEqual(optional.returncode, 0, optional.stderr)
            self.assertIn("installation staged successfully", optional.stdout)

    def test_model_probe_rejects_wrong_model_and_empty_catalogue(self):
        with patch.object(welcome, "request_json", return_value={"models": [{"name": "chosen:latest"}]}):
            self.assertTrue(welcome.verify("ollama", "http://localhost", "", "chosen")[0])
            self.assertFalse(welcome.verify("ollama", "http://localhost", "", "missing")[0])
        with patch.object(welcome, "request_json", return_value={"data": []}):
            self.assertFalse(welcome.verify("compatible", "http://localhost/v1", "test", "chosen")[0])

    def test_selected_ollama_endpoint_is_saved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "openclaw.json"
            config.write_text('{"models":{"providers":{}}}')
            with patch.object(welcome, "OPENCLAW_CONFIG", config), patch.object(welcome, "set_env") as env:
                welcome.update_openclaw("ollama", "model:tag", "http://localhost:12345", "")
            saved = json.loads(config.read_text())
            self.assertEqual(saved["models"]["providers"]["ollama"]["baseUrl"], "http://localhost:12345")
            self.assertEqual(saved["agents"]["defaults"]["model"]["primary"], "ollama/model:tag")
            env.assert_called_once()

    def test_reinstall_refreshes_code_and_preserves_workspace(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, target = root / "source", root / "target"
            source.mkdir()
            target.mkdir()
            (source / "example.py").write_text("new code")
            (target / "example.py").write_text("old code")
            runner = installer.Runner(False)
            runner.deploy_tree(source, target)
            self.assertEqual((target / "example.py").read_text(), "new code")
            self.assertEqual((target / "example.py.before-rhizome-stack").read_text(), "old code")
            (target / "example.py").write_text("owner note")
            runner.copy_tree(source, target)
            self.assertEqual((target / "example.py").read_text(), "owner note")

    def test_complete_skill_install_and_customisation_preserved(self):
        manifest = json.loads((ROOT / "manifests/skills.json").read_text())
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "skills"
            self.assertEqual(skills.install(["blackboard"], target, manifest, True), 0)
            self.assertFalse(target.exists())
            self.assertEqual(skills.install(["blackboard"], target, manifest), 0)
            self.assertTrue((target / "blackboard/scripts/blackboard.py").is_file())
            custom = target / "blackboard/SKILL.md"
            custom.write_text("owner's customised instructions")
            self.assertEqual(skills.install(["blackboard"], target, manifest), 1)
            self.assertEqual(custom.read_text(), "owner's customised instructions")


if __name__ == "__main__":
    unittest.main()
