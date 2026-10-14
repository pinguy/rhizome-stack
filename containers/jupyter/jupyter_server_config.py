"""Fail closed: the service supplies a private, per-installation token."""
import os

_token = os.environ.get("JUPYTER_TOKEN", "")
if not _token:
    raise RuntimeError("JUPYTER_TOKEN is required; refusing unauthenticated Jupyter")
c = get_config()  # noqa: F821 - provided by Jupyter's configuration loader
c.IdentityProvider.token = _token
c.ServerApp.ip = "0.0.0.0"
c.ServerApp.port = 8888
c.ServerApp.open_browser = False
c.ServerApp.allow_remote_access = False
c.ServerApp.allow_origin = ""
c.ServerApp.log_level = "WARN"
c.ServerApp.allow_unauthenticated_access = False
