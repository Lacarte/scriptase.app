"""Shared security helpers for path safety, identifiers, and network guards."""

from __future__ import annotations

import ipaddress
import os
import re
import socket
from urllib.parse import urlparse


_ID_RE = re.compile(r"[^A-Za-z0-9_-]+")


def sanitize_project_id(value: str | None, max_len: int = 100) -> str:
    """Return a strict project id (alnum, underscore, hyphen)."""
    raw = (value or "").strip()
    cleaned = _ID_RE.sub("", raw)
    return cleaned[:max_len]


def sanitize_folder_name(value: str | None, max_len: int = 120) -> str:
    """Folder-safe identifier using the same charset constraints as project IDs."""
    return sanitize_project_id(value, max_len=max_len)


def safe_join(root: str, *parts: str) -> str:
    """Join paths while preventing traversal outside root."""
    root_abs = os.path.abspath(root)
    target = root_abs
    for part in parts:
        target = os.path.join(target, part)
    target_abs = os.path.abspath(target)
    if os.path.commonpath([root_abs, target_abs]) != root_abs:
        raise ValueError("Path escapes root")
    return target_abs


def _host_resolves_to_private(hostname: str) -> bool:
    host = (hostname or "").strip().lower()
    if not host:
        return True
    if host in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        ip = ipaddress.ip_address(host)
        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
        )
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except OSError:
        return True

    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
            ):
                return True
        except ValueError:
            return True
    return False


def is_safe_webhook_url(url: str | None, allow_private: bool = True) -> bool:
    """Allow only http(s) webhook URLs, optionally blocking private/local targets."""
    raw = (url or "").strip()
    if not raw:
        return False
    try:
        parsed = urlparse(raw)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    if not parsed.hostname:
        return False
    if allow_private:
        return True
    return not _host_resolves_to_private(parsed.hostname)


def is_loopback_remote(remote_addr: str | None) -> bool:
    value = (remote_addr or "").strip()
    if not value:
        return False
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return ip.is_loopback
