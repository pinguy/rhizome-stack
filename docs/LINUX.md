# Native Linux installation

Tested package families are Arch/CachyOS and Debian/Ubuntu on x86-64 with
systemd user services.

```bash
./install-linux.sh --dry-run
./install-linux.sh
```

Optional profiles can be combined:

```bash
./install-linux.sh --with-memory --with-voice --download-models --with-jupyter --with-routing --with-retrieval
./install-linux.sh --with-creative --download-creative-models
```

The installer stages configuration and units but deliberately does not enable
or start them. Review `~/.config/rhizome-stack/stack.env`, configure provider
credentials locally, then run `bin/rhizome-stack doctor` before starting the
core services.

The creative profile requires a compatible NVIDIA driver/CUDA path and large
model downloads. Verify one real Qwen image and one MiniMax audio generation on
the target; a successful install or healthy HTTP response is not GPU acceptance.
