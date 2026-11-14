# COMET-ATOMIC-2020 WeightSpace context

- Architecture: BART-large encoder-decoder, 12 encoder and 12 decoder layers.
- Input format: `<head text> <relation> [GEN]`.
- The `comet_generate` probe performs real model generation before accepting an edit.
- The canonical downloaded model is immutable. Save edited variants elsewhere.
- Checkpoint: `mismayil/comet-bart-ai2` at the pinned revision in `manifests/versions.json`.
