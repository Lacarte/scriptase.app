"""Browser-extension WebSocket hub — step 14.4.

Domain-neutral client-pool, pending-message queue, prune, and broadcast
mechanics. Each extension provider constructs one hub with its frozen route
path (``/ws/storyboard-gemini-image-grabber``, ``/ws/animator-grok-video-grabber``)
and keeps its own message handlers: the hub never interprets IMAGE_JOB /
GRABBER_START / ASSET_UPLOAD payloads.

A disconnected extension is a health state, not a submit failure — pending
messages stay queued and flush on the next handshake, which is what both
extension providers have always relied on.
"""

from __future__ import annotations

import json
import threading
from typing import Any, Callable, Literal, Mapping

from loguru import logger

MessageHandler = Callable[[Mapping[str, Any], Any], None]
ConnectHandler = Callable[[Any], None]
PendingMode = Literal["list", "single"]

# Diagnostic bridge message types both extensions understand.
_RELAY_TYPES = frozenset({"DIAGNOSE", "DIAGNOSE_REPORT", "FORCE_DISCONNECT"})


class ExtensionWebSocketHub:
    """One WebSocket route's client pool and pending outbound queue.

    Parameters
    ----------
    name:
        Short log label (e.g. ``"gemini"``, ``"grok"``).
    route:
        Frozen public path registered on flask-sock.
    pending_mode:
        ``"list"`` keeps every queued job until acknowledged (storyboard multi-
        project). ``"single"`` keeps only the most recent message (animator
        grabber start).
    on_message:
        Domain handler for non-relay, non-ping frames. Signature
        ``(msg, ws) -> None``.
    on_connect:
        Optional hook after a client is registered (e.g. send CONNECTED).
    """

    def __init__(
        self,
        name: str,
        route: str,
        *,
        pending_mode: PendingMode = "list",
        on_message: MessageHandler | None = None,
        on_connect: ConnectHandler | None = None,
        project_key: str = "projectId",
    ) -> None:
        if pending_mode not in {"list", "single"}:
            raise ValueError(f"unknown pending_mode: {pending_mode!r}")
        self.name = name
        self.route = route
        self.pending_mode: PendingMode = pending_mode
        self.project_key = project_key
        self.on_message = on_message
        self.on_connect = on_connect

        # Public so health checks and tests can inspect / patch the pool
        # without reaching into private locks.
        self.clients: list[Any] = []
        self._clients_lock = threading.Lock()
        self._pending: list[Mapping[str, Any]] = []
        self._pending_single: Mapping[str, Any] | None = None
        self._pending_lock = threading.Lock()
        self._registered = False

    # -- registration -------------------------------------------------------

    def register(self, sock) -> None:
        """Bind the frozen route on a flask-sock instance. Idempotent."""
        if sock is None:
            logger.warning(
                "[{}] No socket provided, skipping runtime registration", self.name
            )
            return
        if self._registered:
            logger.debug("[{}] route {} already registered", self.name, self.route)
            return

        hub = self

        def _ws_handler(ws):  # type: ignore[no-untyped-def]
            hub._serve(ws)

        # Each hub needs a unique endpoint name: two nested `_ws_handler`
        # functions would collide inside Flask's view map.
        _ws_handler.__name__ = f"ws_{self.name}_extension"
        _ws_handler.__qualname__ = _ws_handler.__name__
        sock.route(self.route)(_ws_handler)

        self._registered = True
        logger.info("[{}] registered WebSocket route {}", self.name, self.route)

    def _serve(self, ws) -> None:
        with self._clients_lock:
            self.clients.append(ws)
            count = len(self.clients)
        logger.info("[{}] WS client connected (clients: {})", self.name, count)

        if self.on_connect is not None:
            try:
                self.on_connect(ws)
            except Exception as exc:
                logger.warning("[{}] on_connect failed: {}", self.name, exc)

        self.flush_pending(ws)

        try:
            while True:
                raw = ws.receive()
                if raw is None:
                    logger.info("[{}] WS received None — client closed", self.name)
                    break
                self._dispatch_raw(raw, ws)
        except Exception as exc:
            logger.info("[{}] WS closed: {}", self.name, exc)
        finally:
            with self._clients_lock:
                if ws in self.clients:
                    self.clients.remove(ws)
                count = len(self.clients)
            logger.info("[{}] WS client disconnected (clients: {})", self.name, count)

    def _dispatch_raw(self, raw: Any, ws) -> None:
        try:
            msg = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            sample = raw[:120] if isinstance(raw, str) else ""
            logger.warning("[{}] WS bad JSON: {}", self.name, sample)
            return
        if not isinstance(msg, Mapping):
            logger.warning("[{}] WS non-object message", self.name)
            return

        msg_type = str(msg.get("type") or "")
        logger.debug("[{}] WS ← {}", self.name, msg_type or "unknown")

        if msg_type == "PING":
            self.send(ws, {"type": "PONG"})
            return
        if msg_type in _RELAY_TYPES:
            self.relay(msg, except_ws=ws)
            return
        if self.on_message is not None:
            try:
                self.on_message(msg, ws)
            except Exception as exc:
                logger.error("[{}] message handler failed ({}): {}", self.name, msg_type, exc)

    # -- client pool --------------------------------------------------------

    def prune(self) -> list[Any]:
        """Drop dead sockets by sending PING. Caller must not hold the lock."""
        with self._clients_lock:
            alive: list[Any] = []
            ping = json.dumps({"type": "PING"})
            for ws in self.clients:
                try:
                    ws.send(ping)
                    alive.append(ws)
                except Exception:
                    pass
            self.clients[:] = alive
            return list(alive)

    def is_connected(self) -> bool:
        alive = self.prune()
        logger.info(
            "[{}] WS connection check: {} alive client(s)", self.name, len(alive)
        )
        return len(alive) > 0

    def client_count(self) -> int:
        with self._clients_lock:
            return len(self.clients)

    def send(self, ws, message: Mapping[str, Any]) -> bool:
        try:
            ws.send(json.dumps(message))
            return True
        except Exception as exc:
            logger.warning("[{}] send failed: {}", self.name, exc)
            return False

    def broadcast(
        self,
        message: Mapping[str, Any],
        *,
        label: str | None = None,
        prune: bool = False,
    ) -> bool:
        """Send to every connected client. Returns True if at least one accepted."""
        data = json.dumps(message)
        tag = label or str(message.get("type") or "message")
        sent = False
        with self._clients_lock:
            if prune:
                # prune needs the lock's contents; do it inline to avoid re-entry.
                alive: list[Any] = []
                ping = json.dumps({"type": "PING"})
                for ws in self.clients:
                    try:
                        ws.send(ping)
                        alive.append(ws)
                    except Exception:
                        pass
                self.clients[:] = alive
                logger.info("{} → {} alive client(s)", tag, len(alive))
            for ws in list(self.clients):
                try:
                    ws.send(data)
                    sent = True
                except Exception as exc:
                    logger.warning("{} send failed: {}", tag, exc)
        if sent:
            logger.info("{} delivered to {} extension", tag, self.name)
        else:
            logger.warning("{} failed — no connected {} clients", tag, self.name)
        return sent

    def relay(self, message: Mapping[str, Any], *, except_ws=None) -> int:
        """Forward a diagnostic frame to every client except the sender."""
        data = json.dumps(message)
        others = 0
        with self._clients_lock:
            for client in list(self.clients):
                if client is except_ws:
                    continue
                try:
                    client.send(data)
                    others += 1
                except Exception:
                    pass
        logger.info(
            "[{}] Relayed {} to {} other client(s)",
            self.name, message.get("type", "?"), others,
        )
        return others

    # -- pending queue ------------------------------------------------------

    def queue(self, message: Mapping[str, Any], *, label: str | None = None) -> bool:
        """Queue an outbound job and try to deliver it immediately.

        Returns True when at least one connected client accepted the send.
        The message stays pending either way so a late-connecting client still
        receives it on handshake.
        """
        with self._pending_lock:
            if self.pending_mode == "single":
                self._pending_single = dict(message)
            else:
                self._pending.append(dict(message))

        tag = label or str(message.get("type") or "JOB")
        project = message.get(self.project_key, "?")
        scenes = message.get("scenes")
        scene_count = len(scenes) if isinstance(scenes, list) else "?"

        sent = False
        with self._clients_lock:
            client_count = len(self.clients)
            if self.clients:
                data = json.dumps(message)
                for ws in list(self.clients):
                    try:
                        ws.send(data)
                        sent = True
                    except Exception as exc:
                        logger.warning("{} send failed to a client: {}", tag, exc)

        if sent:
            logger.info(
                "{} → {} extension ({} — {} scenes, clients: {}, awaiting JOB_RECEIVED)",
                tag, self.name, project, scene_count, client_count,
            )
        else:
            logger.warning(
                "{} queued — NO connected clients ({} — {} scenes)",
                tag, project, scene_count,
            )
        return sent

    def flush_pending(self, ws) -> int:
        """Re-send every pending message to a newly connected client."""
        with self._pending_lock:
            if self.pending_mode == "single":
                pending = [self._pending_single] if self._pending_single else []
            else:
                pending = list(self._pending)

        flushed = 0
        for msg in pending:
            if msg is None:
                continue
            try:
                ws.send(json.dumps(msg))
                flushed += 1
                logger.info(
                    "[{}] Flushed pending {} to new client ({} — {} scenes)",
                    self.name,
                    msg.get("type", "?"),
                    msg.get(self.project_key, "?"),
                    len(msg.get("scenes") or []) if isinstance(msg.get("scenes"), list) else "?",
                )
            except Exception as exc:
                logger.warning("[{}] Flush failed: {}", self.name, exc)
        return flushed

    def drop_pending(self, project_id: str | None = None) -> int:
        """Clear pending messages. With a project_id, only that project's jobs.

        For ``single`` mode the single slot is cleared when it matches (or when
        ``project_id`` is None).
        """
        with self._pending_lock:
            if self.pending_mode == "single":
                if self._pending_single is None:
                    return 0
                if project_id is None or self._pending_single.get(self.project_key) == project_id:
                    self._pending_single = None
                    return 1
                return 0
            before = len(self._pending)
            if project_id is None:
                self._pending.clear()
            else:
                self._pending[:] = [
                    msg for msg in self._pending
                    if msg.get(self.project_key) != project_id
                ]
            return before - len(self._pending)

    def pending_count(self) -> int:
        with self._pending_lock:
            if self.pending_mode == "single":
                return 0 if self._pending_single is None else 1
            return len(self._pending)


def extension_connected(hub: ExtensionWebSocketHub | None) -> bool:
    """Safe connectivity probe used by preflight and health checks."""
    if hub is None:
        return False
    try:
        return bool(hub.is_connected())
    except Exception:
        return False


__all__ = ["ExtensionWebSocketHub", "extension_connected"]
