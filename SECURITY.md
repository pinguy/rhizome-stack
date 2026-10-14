# Security

Please report vulnerabilities privately through GitHub Security Advisories for
this repository. Do not open a public issue containing credentials, personal
data or an exploitable secret-handling failure.

The release privacy scanner is defence in depth, not permission to commit
private material. Provider credentials belong only in the target machine's
mode-0600 configuration.

The adapter is a credential boundary: its per-installation bearer token is
separate from the gateway token. It accepts loopback Host headers, JSON POSTs
and server-to-server calls only. Creative desks accept same-origin browser
requests and pass adapter credentials from their service environment.
These checks do not isolate untrusted processes already running as your user.

Jupyter requires a separate token and rejects non-local Host headers. Its
container remains loopback-published with restricted mounts and capabilities.
It is one shared code execution environment, not a per-user isolation system.

See [security upgrade steps](docs/SECURITY_UPGRADE.md) for existing installs.
The privacy scanner recognises common token formats and contextual Telegram
IDs; it cannot identify every bare numeric ID or arbitrary secret. Removing a
value from current files does not remove it from Git history or earlier archives.
