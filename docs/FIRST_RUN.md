# First run

Run `~/.local/bin/rhizome-stack welcome` after installation. Native Linux and
WSL2 share this wizard.

## 1. Choose a backend

Choose OpenAI, Anthropic, NVIDIA NIM, Ollama, another OpenAI-compatible endpoint,
or the advanced GGUF-to-Ollama route. Enter the exact model ID listed by your
provider. Hosted API keys use a hidden prompt and are stored locally with mode
0600 after the catalogue check succeeds.

The wizard checks that the **selected model** is present. If the provider omits
an alias from its catalogue, use the listed ID or configure it manually through
`openclaw configure`. A successful catalogue check is recorded separately from
inference: it does not prove quota, chat permissions, tool calling or generation.

Ollama must already be running with a model installed. When a custom Ollama
endpoint is chosen, the same endpoint is saved to both OpenClaw and the stack
environment. GGUF files stay where you put them.

Existing provider logins and customised configurations are best handled with
`openclaw configure`; the wizard is intended for initial setup.

## 2. Choose optional components

The wizard offers voice, private semantic memory, Jupyter and the core Skills
profile. It can re-run the installed installer for these choices. Voice weights
remain a separate download:

```bash
./install-linux.sh --with-voice --download-models
```

The Skills profile installs into the workspace configured by OpenClaw, preserving
differing existing skill directories. See [integrations](INTEGRATIONS.md).

## 3. Start and test

```bash
rhizome-stack doctor
rhizome-stack start
rhizome-stack smoke
```

Open **http://localhost:8080**, create the first administrator and send a message
to the selected model. Check that an actual response appears. Then try the
specific capabilities you enabled: memory lookup, speech or code execution.
See [maintenance](MAINTENANCE.md) for service logs and common failures.

`start`, `stop` and `status` manage the three core services. Optional services
and timers are enabled separately after their dependencies are configured.

## 4. Register packaged Open WebUI tools

Create an Open WebUI API token and save only the token in a mode-0600 file:

```bash
install -m 600 /dev/null ~/.config/rhizome-stack/openwebui-admin.token
${EDITOR:-vi} ~/.config/rhizome-stack/openwebui-admin.token
python3 ~/.local/share/rhizome-stack/tools/register_openwebui_tools.py \
  --token-file ~/.config/rhizome-stack/openwebui-admin.token
```

Use the matching configuration directory if you set `XDG_CONFIG_HOME`.
Registration preserves matching tool IDs. Select the tools in Open WebUI as
needed; the token is read from disk rather than supplied in process arguments.

## 5. Import your own knowledge

```bash
rhizome-stack import ~/Documents/manual.pdf --dry-run
rhizome-stack import ~/Documents/manual.pdf
```

PDF and DOCX reading needs the optional memory environment. If invoking the
import command from the system Python, the launcher selects that environment
when it is installed. [Memory guide](MEMORY.md) covers all formats and reindexing.

For Open WebUI memory synchronisation, set `OPENWEBUI_USER_ID` in `stack.env`,
then enable the timer:

```bash
systemctl --user enable --now openwebui-memory-sync.timer
```

Enable the Ollama catalogue timer only when its endpoint is available:

```bash
systemctl --user enable --now openclaw-ollama-model-sync.timer
```
