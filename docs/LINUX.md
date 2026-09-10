# Native Linux installation

Tested package families are Arch/CachyOS and Debian/Ubuntu on x86-64 with
systemd user services.

```bash
./install-linux.sh --dry-run
./install-linux.sh
```

Optional profiles can be combined:

```bash
./install-linux.sh --with-memory --with-voice --download-models --with-jupyter
```

The installer stages configuration and units but deliberately does not enable
or start them. Review `~/.config/rhizome-stack/stack.env`, configure provider
credentials locally, then run `bin/rhizome-stack doctor` before starting the
core services.

