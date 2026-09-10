#!/usr/bin/env python3
"""Create a valid empty FAISS memory set without importing anyone's content."""

import pickle
from pathlib import Path

import faiss
import numpy as np


root = Path.home() / ".local/share/rhizome-stack/memory/archive"
root.mkdir(parents=True, exist_ok=True)
paths = [root / "memory.index", root / "memory_texts.npy", root / "memory_metadata.pkl"]
if any(path.exists() for path in paths):
    if all(path.exists() for path in paths):
        print(f"preserving existing memory set: {root}")
        raise SystemExit(0)
    raise SystemExit(f"partial memory set exists; refusing to guess or overwrite: {root}")
faiss.write_index(faiss.IndexFlatIP(384), str(paths[0]))
np.save(paths[1], np.array([], dtype=object), allow_pickle=True)
with paths[2].open("wb") as stream:
    pickle.dump([], stream)
print(f"created empty memory set: {root}")

