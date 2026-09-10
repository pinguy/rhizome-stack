# Welcome and first run

Run `rhizome-stack welcome`. The same wizard is used on native Linux and WSL;
only their installer and preflight differ.

The wizard deliberately configures intelligence first. It offers OpenAI,
Anthropic, NVIDIA NIM, Ollama, another OpenAI-compatible endpoint, or an
advanced guided GGUF-to-Ollama route. Hosted credentials are entered through a
hidden prompt and stored only in the new owner's mode-0600 environment file.
They are never printed, passed in process arguments, logged, or exported.

The selected backend must answer its provider/model probe before it becomes the
default. This is worth doing first: a working model can then help the owner with
the less familiar parts of setup.

After verification, the wizard offers speech-to-text/text-to-speech, semantic
memory, and Jupyter as independent modules. None is silently required. Re-running
the installer for selected modules is safe and preserves existing configuration.

The optional import step accepts documents, books, ChatGPT/OpenAI exports and
Claude/Anthropic exports. It reads only paths explicitly supplied by the new
owner, de-duplicates chunks, and builds a private FAISS index when the memory
module is installed. Import sources and generated indexes live under runtime
state and are outside the release exporter.

Then run `rhizome-stack doctor`, followed by `rhizome-stack start`.

## Open WebUI account and packaged tools
4. Open `http://localhost:8080` and create the first Open WebUI administrator.
5. Create an Open WebUI API token, save only the token in a mode-0600 file, and
   register the packaged tools:

```bash
install -m 600 /dev/null ~/.config/rhizome-stack/openwebui-admin.token
${EDITOR:-vi} ~/.config/rhizome-stack/openwebui-admin.token
python3 tools/register_openwebui_tools.py \
  --token-file ~/.config/rhizome-stack/openwebui-admin.token
```

The registration command preserves tools with matching IDs instead of
overwriting them. The token is read from disk and never accepted on the command
line.

For memory synchronisation, obtain the Open WebUI user ID from the account/API
response and set `OPENWEBUI_USER_ID` in `stack.env`; then enable the timer:

```bash
systemctl --user enable --now openwebui-memory-sync.timer
```

Enable the Ollama catalogue timer only when an Ollama endpoint is available:

```bash
systemctl --user enable --now openclaw-ollama-model-sync.timer
```
