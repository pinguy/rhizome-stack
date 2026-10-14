# Updating the adapter and optional Jupyter runtime

Alpha.11 closes unauthenticated access to the adapter and removes the explicit
no-auth Jupyter configuration. Source updates alone do not change running
services. These steps apply on the machine where you installed the stack.

1. Stop the affected services before updating:

   ```bash
   systemctl --user stop openclaw-openwebui-adapter.service
   systemctl --user stop openwebui-code-jupyter.service
   ```

   Skip the second command if you have never installed the Jupyter unit.
2. From the updated checkout, run your usual installer with the same optional
   features you use. For a configuration/component-only update, use
   `./install-linux.sh --skip-packages --skip-runtime` (or `install-wsl.sh`).
   It preserves populated gateway/WebUI secrets, generates separate adapter and
   Jupyter tokens when absent, and updates only the local adapter's key slot in
   `OPENAI_API_KEYS`. First-change `.before-rhizome-stack` backups are retained;
   the populated `stack.env` is mode 0600. Services are not started automatically.
3. If you use Jupyter, include `--with-jupyter` when staging the configuration.
   Rebuild its image before restarting it; a configuration-only run does not
   rebuild the old image:

   ```bash
   podman build --tag localhost/rhizome-stack-jupyter:1 \
     --file containers/jupyter/Containerfile containers/jupyter
   ```

   The new unit passes only `JUPYTER_TOKEN` into the container by environment
   variable name. The token is not put into the command line.
4. In Open WebUI's Admin Panel, edit the saved OpenAI connection for
   `http://127.0.0.1:18888/v1`: set its API key to the private
   `RHIZOME_ADAPTER_TOKEN` value in your installed `stack.env`.
   Existing database settings can override the environment, so changing the
   file alone may leave the saved `local-adapter` key in use. Do not paste
   private values into issues, logs or screenshots.
5. For Jupyter, configure **both Code Execution and Code Interpreter** to use
   the Jupyter engine, URL `http://127.0.0.1:8889`, authentication type `token`,
   and the private `JUPYTER_TOKEN`. `--with-jupyter` seeds the corresponding
   environment settings for new installations; existing saved settings need
   the Admin Panel update too. This explicitly selects the local sandbox.
6. Reload units and restart the adapter, Open WebUI and any creative desks you
   use so they receive the new service environment. Start Jupyter only after
   rebuilding its image. Use the unit names under `systemd/` for your features.
   Confirm a real chat and, if enabled, a small Jupyter code execution from
   Open WebUI. `rhizome-stack smoke` checks reachability only.

The adapter's `/health` endpoint remains available without a secret for local
health checks. Model listing and chat completion require bearer authentication.
A missing or obsolete adapter token fails closed. Creative desk browsers never
receive the adapter token: each desk adds it server-side and rejects cross-site
requests, non-loopback Host headers and unexpected POST content types.

## Python compatibility

Open WebUI 0.11.0 declares `>=3.11,<3.13.0a1`. The installer reads the supported
bounds from `manifests/versions.json`, tries the current interpreter, then
`python3.12` and `python3.11`. You can select one explicitly with
`--python /path/to/python3.12`. Install that interpreter and its venv support
first if your distro's default Python is newer. The installer does not replace
the system Python or silently delete incompatible existing environments.
`--skip-runtime` remains available for configuration-only staging.

## Private data already published

The audit no longer embeds a personal identifier to detect itself. It uses
contextual Telegram ID patterns and recognises additional credential formats.
Old commits and previously downloaded archives can still contain removed data.
A normal update preserves repository history; history removal is a separate,
coordinated operation and cannot recall copies already downloaded.
