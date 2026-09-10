# Updating and troubleshooting

## Update a working installation

Keep your working configuration and data backed up. From a clean checkout:

```bash
git pull --ff-only
python3 tests/test_static.py
python3 tests/test_behaviour.py
./install-linux.sh --dry-run --with-skills
rhizome-stack stop
./install-linux.sh --with-skills
rhizome-stack doctor
rhizome-stack start
rhizome-stack smoke
```

Use the same optional flags you need and the WSL launcher where applicable.
Read the diff before updating an installation with local code patches.

Shipped components, tools, manifests, patches and templates are refreshed.
The first overwritten copy of a deployed file is retained with the suffix
`.before-rhizome-stack`; this is a first-change backup, not a complete versioned
backup system. Workspace notes are seeded only when absent. Existing
`stack.env` and OpenClaw settings are preserved except for explicitly selected
configuration steps, such as enabling the memory plugin.

The installer does not upgrade the OpenClaw/Open WebUI version pins. Restoring
an earlier checkout alone does not roll back installed packages or databases.
Do not downgrade a migrated database without its matching backup.

Core lifecycle commands manage the gateway, adapter and Open WebUI. Stop any
optional services you have separately enabled before modifying their files.

## Check failures

| Symptom | Check |
| --- | --- |
| `rhizome-stack: command not found` | Use `~/.local/bin/rhizome-stack`, then add that directory to PATH |
| `doctor` reports missing runtime files | Re-run installation; `--skip-runtime` deliberately leaves dependencies absent |
| Provider catalogue succeeds but chat fails | Test credentials, quota and the exact configured model using a real chat |
| Ollama model not found | Compare the selected name/tag with `ollama list`; rerun welcome or configure |
| OAuth refresh/persistence failure | Check ownership of the local auth files, then use the provider login flow exposed by `openclaw configure` |
| PDF/DOCX import lacks dependencies | Install `--with-memory`; the importer uses that environment when available |
| New import is not visible | Run `import --reindex` if it was only staged, then restart the gateway |
| Skills are not discovered | Check the configured workspace and start a new session |
| Audio port already in use | Inspect whether the stack or Chatterbox add-on owns the overlapping services |
| WSL has no user services | Enable systemd, shut down WSL from Windows and reopen the distribution |

Useful logs:

```bash
systemctl --user --no-pager status openclaw-gateway openclaw-openwebui-adapter open-webui
journalctl --user -u openclaw-gateway -u openclaw-openwebui-adapter -u open-webui -n 100 --no-pager
```

Review logs before sharing them: they may contain prompts, private paths or
provider information.

## Verification levels

- `doctor` checks commands, installed files and required local configuration.
- `smoke` checks HTTP reachability, with bounded connection/request timeouts.
- The welcome wizard checks the selected model in the provider catalogue.
- A real chat in Open WebUI checks the request path and inference.
- Memory, voice and Jupyter each need their own real acceptance check.

Static success must not be reported as a complete native/WSL installation.
The [Open WebUI regression skill](../components/skills/openwebui-regression-test/SKILL.md)
describes testing through the actual browser path.

## Release maintenance

`manifests/release-files.json` is the explicit distribution file list. Add new
distributable source/docs paths there. Never generate it from a runtime install,
and never add private state just to make a release check pass.

The release builder runs the privacy audit, creates a SHA-256 manifest and
produces deterministic tar.zst output. Compare two independent builds before
publishing an archive. GitHub source commits and downloadable release archives
are different deliverables; pushing this repository does not create a release.
