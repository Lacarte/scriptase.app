"""Canonical workflow-node fingerprints and persistent result cache.

Cache entries are scoped by workflow, project, and node identity.  The
fingerprint remains the authority: scoping prevents unrelated graphs which
happen to share a node ID from overwriting one another, while the canonical
input/config representation prevents unsafe reuse within that scope.
"""

from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping

from scriptase.shared.io_utils import now_iso, safe_json_read, safe_json_write
from scriptase.shared.security import safe_join


CACHE_SCHEMA_VERSION = 1
# Bumped in step 15.3: tts.generate no longer emits absolute wav_path/path on
# port payloads (contracts.md §36 L7 / §44). Cache entries written under v1
# carry the old absolute shape in their inputs fingerprint chain and must miss.
ADAPTER_CACHE_SCHEMA_VERSION = 2


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fingerprint_components(
    node: Mapping[str, Any],
    configuration: Mapping[str, Any],
    inputs: Mapping[str, Any],
    upstream_fingerprints: Mapping[str, str],
    *,
    adapter_schema_version: int = ADAPTER_CACHE_SCHEMA_VERSION,
) -> dict[str, Any]:
    """Return the inspectable canonical inputs to a node fingerprint."""
    return {
        "node_type": node.get("type"),
        "type_version": node.get("type_version"),
        "configuration": deepcopy(dict(configuration)),
        "inputs": deepcopy(dict(inputs)),
        "upstream_artifact_fingerprints": dict(sorted(upstream_fingerprints.items())),
        "adapter_cache_schema_version": adapter_schema_version,
    }


def canonical_fingerprint(components: Mapping[str, Any]) -> str:
    return "sha256:" + _sha256_bytes(_canonical(components).encode("utf-8"))


def component_signatures(components: Mapping[str, Any]) -> dict[str, Any]:
    """Persist comparison hashes, never raw configuration/input values."""
    signatures = {
        "node_type": components.get("node_type"),
        "type_version": components.get("type_version"),
        "adapter_cache_schema_version": components.get("adapter_cache_schema_version"),
    }
    for key in ("configuration", "inputs", "upstream_artifact_fingerprints"):
        signatures[key] = "sha256:" + _sha256_bytes(_canonical(components.get(key)).encode("utf-8"))
    return signatures


def _managed_artifact_path(output_dir: str, ref: str) -> str | None:
    if not isinstance(ref, str) or not ref or os.path.isabs(ref):
        return None
    try:
        path = os.path.abspath(safe_join(output_dir, ref.replace("/", os.sep)))
        root = os.path.abspath(output_dir)
        if os.path.commonpath([root, path]) != root:
            return None
    except (ValueError, OSError):
        return None
    return path


def artifact_integrity(refs: list[str], *, output_dir: str) -> tuple[dict[str, dict[str, Any]], str | None]:
    """Hash managed artifacts. Empty/non-files fail closed for cache reuse."""
    result: dict[str, dict[str, Any]] = {}
    for ref in dict.fromkeys(refs):
        path = _managed_artifact_path(output_dir, ref)
        try:
            if path is None or not os.path.isfile(path):
                return {}, "artifact_missing"
            size = os.path.getsize(path)
            if size <= 0:
                return {}, "artifact_integrity_failed"
            digest = hashlib.sha256()
            with open(path, "rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError:
            return {}, "artifact_integrity_failed"
        result[ref] = {"size": size, "sha256": digest.hexdigest()}
    return result, None


def output_fingerprint(outputs: Mapping[str, Any], integrity: Mapping[str, Any]) -> str:
    return "sha256:" + _sha256_bytes(_canonical({
        "outputs": outputs,
        "artifact_integrity": integrity,
    }).encode("utf-8"))


def miss_reason(previous: Mapping[str, Any], current: Mapping[str, Any]) -> str:
    if previous.get("node_type") != current.get("node_type") or previous.get("type_version") != current.get("type_version"):
        return "type_or_version_changed"
    if previous.get("adapter_cache_schema_version") != current.get("adapter_cache_schema_version"):
        return "adapter_schema_changed"
    if previous.get("configuration") != current.get("configuration"):
        return "config_changed"
    if previous.get("upstream_artifact_fingerprints") != current.get("upstream_artifact_fingerprints"):
        return "upstream_changed"
    if previous.get("inputs") != current.get("inputs"):
        return "inputs_changed"
    return "fingerprint_mismatch"


@dataclass(frozen=True)
class CacheLookup:
    hit: bool
    reason: str
    outputs: dict[str, Any] | None = None
    output_fingerprint: str | None = None


class NodeCache:
    def __init__(self, *, root: str, output_dir: str):
        self.root = root
        self.output_dir = output_dir

    def _path(self, workflow_id: str, project_id: str, node_id: str) -> str:
        # Validated workflow documents constrain all three values. Hashing the
        # compound identity keeps this persistence boundary safe independently.
        key = _sha256_bytes(f"{workflow_id}\0{project_id}\0{node_id}".encode("utf-8"))
        return safe_join(self.root, f"{key}.json")

    def lookup(
        self,
        *,
        workflow_id: str,
        project_id: str,
        node_id: str,
        fingerprint: str,
        components: Mapping[str, Any],
        force: bool = False,
    ) -> CacheLookup:
        if force:
            return CacheLookup(False, "forced_regeneration")
        try:
            entry = safe_json_read(self._path(workflow_id, project_id, node_id))
        except FileNotFoundError:
            return CacheLookup(False, "no_prior_success")
        except (OSError, ValueError, json.JSONDecodeError):
            return CacheLookup(False, "cache_corrupt")
        if entry.get("cache_schema_version") != CACHE_SCHEMA_VERSION or entry.get("status") != "succeeded":
            return CacheLookup(False, "no_prior_success")
        if entry.get("fingerprint") != fingerprint:
            return CacheLookup(False, miss_reason(
                entry.get("component_signatures") or {}, component_signatures(components)
            ))
        outputs = entry.get("outputs")
        if not isinstance(outputs, dict):
            return CacheLookup(False, "cache_corrupt")
        stored_integrity = entry.get("artifact_integrity") or {}
        refs = list(stored_integrity)
        current_integrity, failure = artifact_integrity(refs, output_dir=self.output_dir)
        if failure:
            return CacheLookup(False, failure)
        if current_integrity != stored_integrity:
            return CacheLookup(False, "artifact_integrity_failed")
        return CacheLookup(
            True,
            "fingerprint_match",
            deepcopy(outputs),
            entry.get("output_fingerprint"),
        )

    def store(
        self,
        *,
        workflow_id: str,
        project_id: str,
        node_id: str,
        fingerprint: str,
        components: Mapping[str, Any],
        outputs: Mapping[str, Any],
        artifact_refs: list[str],
    ) -> tuple[str | None, str | None]:
        integrity, failure = artifact_integrity(artifact_refs, output_dir=self.output_dir)
        if failure:
            return None, failure
        try:
            output_fp = output_fingerprint(outputs, integrity)
            entry = {
                "cache_schema_version": CACHE_SCHEMA_VERSION,
                "status": "succeeded",
                "workflow_id": workflow_id,
                "project_id": project_id,
                "node_id": node_id,
                "fingerprint": fingerprint,
                "component_signatures": component_signatures(components),
                "outputs": deepcopy(dict(outputs)),
                "artifact_integrity": integrity,
                "output_fingerprint": output_fp,
                "created_at": now_iso(),
            }
            # Prove serializability before the atomic writer boundary.
            _canonical(entry)
            safe_json_write(self._path(workflow_id, project_id, node_id), entry, indent=2)
        except (TypeError, ValueError, OSError):
            return None, "cache_not_serializable"
        return output_fp, None
