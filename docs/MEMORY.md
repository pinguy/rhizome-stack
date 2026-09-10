# Private memory and RhizomeML

Install the memory profile first:

```bash
./install-linux.sh --with-memory
```

The stack uses CPU MiniLM embeddings with FAISS retrieval and lexical matching.
This is retrieval over supplied material; importing documents does not fine-tune
the language model.

## Supported input

| Input | What is preserved |
| --- | --- |
| ChatGPT `conversations.json` | Nested author roles, conversation/message IDs, timestamps, parent IDs and all exported branches |
| Claude exports | Conversation/message UUIDs, sender, time and text blocks |
| Generic `messages` arrays | Roles, text and available IDs |
| RhizomeML detailed JSONL | User/assistant pairs, source metadata, themes and quality metadata |
| RhizomeML compact JSONL | Training text and source metadata |
| RhizomeML `pdf_texts.json` | Filename and individual page text; duplicate total text is skipped |
| JSONL.GZ or JSON.GZ | The same records, read through gzip |
| PDF, DOCX, TXT, MD, RST, CSV | Extracted text; PDF page numbers |
| ZIP exports | Supported files only, with temporary extraction and path checks |

PDFs must contain extractable text; OCR is not included. Images, audio and tool
blocks in conversation content are skipped. Unknown structured JSON is not
silently indexed as a Python representation. Use `--type documents` deliberately
if you want literal JSON text.

## Preview, import and rebuild

```bash
rhizome-stack import ~/Downloads/conversations.json --type chatgpt --dry-run
rhizome-stack import ~/Downloads/conversations.json --type chatgpt
rhizome-stack import ~/Downloads/memory.jsonl.gz --type rhizomeml
rhizome-stack import ~/RhizomeML/pdf_texts.json --type rhizomeml

# Stage text without downloading an embedding model or rebuilding.
rhizome-stack import ~/Documents --no-index

# Build from material already staged.
rhizome-stack import --reindex
```

Preview parses and counts new text without creating runtime files or downloading
models. JSONL is processed one line at a time. Ordinary JSON exports are loaded
as a document. ZIP input has a 2 GiB total unpacked limit; larger exports should
be unpacked separately and selected files imported.

Imports are serialised by a local lock. Duplicate text is stored once; all
distinct origins remain attached to it. The first origin is the canonical
citation. A malformed later record stops the import with an error; earlier
successfully staged chunks remain available for a corrected rerun.

## Index consistency and rollback

The importer records its embedding model in `manifest.json` and builds a complete
index generation before switching `memory/archive` to it. Old generations are
retained. Existing row IDs keep their order; new records are appended so manual
ranking adjustments keep referring to the same memories.

On the first rebuild, an old directory-shaped archive is retained as a
`*-previous` directory. The directory-to-link conversion is not a single atomic
operation; subsequent generation switches are atomic. Stop the core services
before the first migration or when preserving live ranking statistics:

```bash
rhizome-stack stop
rhizome-stack import --reindex
rhizome-stack start
```

A running OpenClaw helper holds its loaded index. Restart `openclaw-gateway`
after imports to use the new generation. Query readers resolve a single snapshot
so index, texts and metadata come from the same generation.

To roll back, stop the services, inspect the previous generation's manifest,
and repoint `memory/archive` to that directory. Restart and run a known memory
query. Keep the owner-import corpus for future rebuilds; rolling back the index
does not undo staged imports. Old generations use disk space and are not
automatically deleted.

## Existing RhizomeML binary archives

Prefer importing RhizomeML's JSON/JSONL/PDF text outputs and rebuilding with the
stack's selected embedder. RhizomeML's reviewed batch embedder defaults to
**all-MiniLM-L12-v2**; this stack defaults to **all-MiniLM-L6-v2**. They both emit
384-dimensional vectors, but their embedding spaces are different. Matching
dimensions alone does not make an index compatible.

The importer refuses to overwrite a nonempty archive it does not recognise as
its own. It does not ingest third-party pickle or NPY files. Existing query
components use trusted, locally produced pickle/NPY metadata; do not point them
at untrusted downloaded binaries.

Private state defaults to `~/.local/share/rhizome-stack/memory/`. A
`RHIZOME_STACK_ROOT` override moves the importer there; configure consumer paths
consistently when customising an existing installation.
