"""Run the vendored ai-web-auto WebSocket server headlessly.

Upstream's own entry point -- `python -m ai_web_auto_backend.automation_controller`
-- is an interactive REPL. It blocks on `input()` and, before that, waits up to
two minutes for an extension to connect before it prints anything at all. V2 hid
that by giving it a separate minimised console window; Scriptase runs its
children in the launcher's console, where a child reading stdin would swallow
the keystrokes meant for the launcher.

So this is the server without the REPL: bind the socket, stay up, and let the
launcher's job object end it. Nothing here reaches into the vendored package
beyond constructing `WebSocketServer`, which keeps re-vendoring a straight
overwrite.

    python tools/automation/serve.py                # SCRIPTASE_AUTOMATION_PORT, else 8765
    python tools/automation/serve.py --port 8799

The port has to agree with the `automationPort` that tools/chromium.ps1 injects
into the extensions, because a WebSocket that never connects is invisible: the
extension retries forever and the provider simply looks unresponsive. That is
why both sides resolve it from SCRIPTASE_AUTOMATION_PORT rather than from a
constant each -- see Get-ScriptaseAutomationPort in tools/automation.ps1.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Mapping, Sequence

VENDOR_ROOT = Path(__file__).resolve().parent / "ai-web-auto"

PORT_ENV = "SCRIPTASE_AUTOMATION_PORT"
DEFAULT_PORT = 8765

# Loopback only, and not negotiable. This server's whole job is to drive a
# browser holding live Google and Grok sessions, so anything that can reach it
# can act as the user. "localhost" rather than "127.0.0.1" on purpose: the
# extensions dial ws://localhost, and on Windows that resolves to ::1 first --
# binding one family would leave the other refusing connections. asyncio binds
# every address the name resolves to, and every one of those is loopback.
HOST = "localhost"


def resolve_port(environ: Mapping[str, str] | None = None) -> int:
    """The port to bind, from the environment.

    A malformed value raises rather than falling back to the default: silently
    binding 8765 when someone asked for something else is the exact mismatch
    this variable exists to prevent.
    """
    raw = (os.environ if environ is None else environ).get(PORT_ENV, "").strip()
    if not raw:
        return DEFAULT_PORT
    try:
        port = int(raw)
    except ValueError:
        raise SystemExit(f"{PORT_ENV} is not a number: {raw!r}") from None
    if not 1 <= port <= 65535:
        raise SystemExit(f"{PORT_ENV} is out of range: {port}")
    return port


def _build_server(port: int):
    # Imported here, not at module scope, so --help and resolve_port work
    # without the provisioned venv -- and so the failure below is about the
    # missing dependency rather than an import error three frames deep.
    if str(VENDOR_ROOT) not in sys.path:
        sys.path.insert(0, str(VENDOR_ROOT))
    try:
        from ai_web_auto_backend.core.server import WebSocketServer
    except ImportError as exc:
        raise SystemExit(
            f"ai-web-auto is not installed: {exc}.\n"
            f"Provision it with: powershell -File tools\\automation.ps1 -InstallOnly"
        ) from None
    # The auth token is left at the package default. It is a fixed constant the
    # extension also ships (`local-dev-token` in ws-client.js), not a secret --
    # and the server logs it on startup, so a real one has no business here.
    return WebSocketServer(host=HOST, port=port)


async def _serve(port: int) -> int:
    server = _build_server(port)
    try:
        await server.start()
    except OSError as exc:
        # The launcher checks the port first, but between that check and this
        # bind is a window; report it as a plain message rather than a traceback.
        print(f"ai-web-auto could not bind {HOST}:{port} -- {exc}", file=sys.stderr)
        return 1
    try:
        await asyncio.Event().wait()  # until the process is ended from outside
    finally:
        await server.stop()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help=f"port to bind; defaults to {PORT_ENV}, then {DEFAULT_PORT}",
    )
    args = parser.parse_args(argv)
    port = args.port or resolve_port()
    try:
        return asyncio.run(_serve(port))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
