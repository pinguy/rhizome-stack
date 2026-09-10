# WSL2 installation

Use a current Ubuntu or Debian WSL2 distribution. WSL1 is not supported.

## Enable systemd

Inside WSL, create `/etc/wsl.conf` with:

```ini
[boot]
systemd=true
```

From PowerShell run `wsl --shutdown`, reopen the distribution, and verify:

```bash
test "$(cat /proc/1/comm)" = systemd
systemctl --user status
```

If user services stop when the terminal closes, enable lingering once:

```bash
sudo loginctl enable-linger "$USER"
```

Then unpack or clone this repository **inside the Linux filesystem**, not under
`/mnt/c`, and run:

```bash
./install-wsl.sh --dry-run
./install-wsl.sh
```

A Windows-side convenience launcher is included when the archive is initially
on Windows storage:

```powershell
.\install-wsl.ps1 -Distro Ubuntu -- --dry-run
```

For the actual installation, copying the release into the WSL Linux filesystem
first remains preferable.

Optional profiles:

```bash
./install-wsl.sh --with-memory
./install-wsl.sh --with-voice --download-models
./install-wsl.sh --with-jupyter
```

The default voice profile is CPU-only. WSL GPU acceleration is intentionally
not enabled until its CUDA, driver and Torch compatibility has been tested on
the target host. Open WebUI and all integration endpoints remain loopback-only;
Windows can normally reach Open WebUI at `http://localhost:8080`.

Do not place populated `stack.env`, OpenClaw state or Open WebUI data on the
Windows-mounted filesystem. Permissions and SQLite behaviour are materially
safer inside the WSL ext4 virtual disk.
