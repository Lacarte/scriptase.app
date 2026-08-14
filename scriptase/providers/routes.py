"""Unified provider API (step 11.5 / 3.1).

One blueprint serves the whole provider surface — catalog, domain and provider
detail, capabilities, health, settings read/write, and the targeted selection
write — from the process-wide hub (contracts.md §27).

Step 3.1 adds the instance path segment. Type-scoped URLs
(`/api/providers/<domain>/<provider_type>/…`) continue to address the default
instance of that type (`instance_id == type`). Instance-scoped URLs
(`/api/providers/<domain>/instances/<instance_id>/…`) address any configured
binding, including a second instance of the same type.

Policy, uniformly: loopback-only (`scriptase.shared.security.is_loopback_remote`)
because these payloads describe and mutate the credential store, and the one
error envelope `{"error": {"code", "message", "details?"}}` from contracts.md §6.
Secret values are write-only — every read leaves the process as the `"***"`
sentinel (§22.6) and every write treats the sentinel as "unchanged".
"""

from flask import Blueprint, jsonify, request

from scriptase.providers.catalog import (
    build_catalog,
    catalog_version,
    selected_instances,
    selected_providers,
)
from scriptase.shared.security import is_loopback_remote
from scriptase.providers import hub, settings_manager
from scriptase.providers.domains import DOMAINS
from scriptase.engine.dev_reload import dev_reload_enabled
from scriptase.engine.options import invalidate_settings_cache

providers_bp = Blueprint("providers", __name__)


# ---------------------------------------------------------------------------
# Envelope and policy helpers
# ---------------------------------------------------------------------------

def _error(code, message, status, details=None):
    body = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return jsonify(body), status


def _require_loopback():
    if not is_loopback_remote(request.remote_addr):
        return _error("FORBIDDEN", "Provider endpoints are local-only", 403)
    return None


def _json_object():
    """Return `(payload, None)` for a JSON object body, else `(None, error)`."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return None, _error("INVALID_REQUEST", "Expected JSON object", 400)
    return data, None


def _resolve_domain(domain):
    """Return `(spec, None)` or `(None, error)` for an unknown domain."""
    spec = DOMAINS.get(domain)
    if spec is None:
        return None, _error("UNKNOWN_DOMAIN", f"Unknown domain: {domain}", 400)
    return spec, None


def _resolve_provider_type(domain, provider_id):
    """Resolve one provider *type* by canonical id then alias (§19.3).

    A discovered-but-excluded provider is a `409`, not a `404`: it exists on disk
    and the operator needs to know the difference (§21.4, §24.2).
    """
    _, err = _resolve_domain(domain)
    if err is not None:
        return None, err
    provider = hub.get(domain, provider_id)
    if provider is not None:
        return provider, None
    for exclusion in hub.registry(domain).excluded():
        if exclusion["id"] == provider_id:
            return None, _error(
                "PROVIDER_EXCLUDED",
                f"Provider '{provider_id}' was discovered but could not be loaded",
                409,
                {"reason_code": exclusion["reason_code"], "message": exclusion["message"]},
            )
    return None, _error("PROVIDER_NOT_FOUND", f"Provider '{provider_id}' not found", 404)


def _resolve_instance(domain, instance_id):
    """Resolve a configured instance to `(provider_type_package, instance_id, settings)`.

    Unknown instance ids that match a registered provider type are accepted as
    the default instance of that type (empty settings) — the shape migration
    writes for a selection that never received a settings write.
    """
    _, err = _resolve_domain(domain)
    if err is not None:
        return None, None, None, err

    if not isinstance(instance_id, str) or not instance_id:
        return None, None, None, _error(
            "INVALID_REQUEST", "instance_id must be a non-empty string", 400
        )

    stored_rec = settings_manager.get_instance_record(domain, instance_id)
    resolved_id, type_id, stored = settings_manager.resolve_instance(domain, instance_id)
    if not type_id:
        return None, None, None, _error(
            "PROVIDER_NOT_FOUND", f"Instance '{instance_id}' not found", 404
        )

    provider, err = _resolve_provider_type(domain, type_id)
    if err is not None:
        # A stored instance whose type was uninstalled: still addressable for
        # settings cleanup, but type-bound operations need the package.
        if stored_rec is None and type_id != instance_id:
            return None, None, None, err
        if provider is None:
            return None, None, None, err
    # Canonicalize type aliases: an unstored path id that resolved through the
    # hub alias table becomes the default instance of the canonical type id.
    if stored_rec is None and provider is not None:
        resolved_id = provider.id
        stored = settings_manager.get_instance_settings(domain, provider.id)
    return provider, resolved_id, stored, None


def _issue_dicts(issues):
    """Normalize `ValidationIssue` objects to the frozen `{field, severity, message}`."""
    return [
        {"field": i.field, "severity": i.severity, "message": i.message}
        if hasattr(i, "field") else i
        for i in issues
    ]


def _health_dict(provider, settings, *, instance_id=None):
    health = provider.health_check(settings)
    return {
        "status": health.status,
        "latency_ms": health.latency_ms,
        "message": health.message,
        # `details` is provider-authored and may echo a submitted secret (§21.5).
        "details": settings_manager.redact_settings(health.details or {}),
        "instance_id": instance_id,
    }


def _instance_payload(domain, provider, instance_id, stored):
    """Browser-safe projection of one configured instance."""
    rec = settings_manager.get_instance_record(domain, instance_id) or {}
    payload = provider.to_dict(stored, instance_id=instance_id)
    payload["instance_id"] = instance_id
    payload["provider_type"] = provider.id
    payload["label"] = rec.get("label") or provider.label
    payload["selected"] = selected_instances().get(domain) == instance_id
    return payload


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

@providers_bp.route("/api/providers", methods=["GET"])
def list_providers():
    """The one versioned catalog: every healthy, unavailable, deprecated, and
    broken provider, grouped by domain.

    Registered providers carry an `availability` of `available`,
    `needs_configuration`, or `degraded`; a provider that failed discovery is an
    `excluded[]` entry with its reason code (§21.4, §21.5). Configured instances
    appear under each domain's `instances[]` (step 3.1).

    `dev_reload_enabled` mirrors the flag on `GET /api/workflow/node-types`: the
    hot-reload watcher covers provider packages too, so a browser holding a
    cached catalog needs the same signal to decide whether subscribing to the
    reload stream is worthwhile. It sits outside `domains`, so it can never move
    `catalog_version`.
    """
    denied = _require_loopback()
    if denied:
        return denied
    catalog = build_catalog()
    return jsonify({
        "catalog_version": catalog_version(catalog),
        "domains": catalog,
        "dev_reload_enabled": dev_reload_enabled(),
    })


@providers_bp.route("/api/providers/<domain>", methods=["GET"])
def domain_detail(domain):
    """One domain's slice of the catalog."""
    denied = _require_loopback()
    if denied:
        return denied
    _, err = _resolve_domain(domain)
    if err is not None:
        return err
    return jsonify(build_catalog()[domain])


# ---------------------------------------------------------------------------
# Instance collection (step 3.1)
# ---------------------------------------------------------------------------

@providers_bp.route("/api/providers/<domain>/instances", methods=["GET"])
def list_domain_instances(domain):
    """Every configured instance in a domain, with independent availability."""
    denied = _require_loopback()
    if denied:
        return denied
    _, err = _resolve_domain(domain)
    if err is not None:
        return err
    selected = selected_instances().get(domain)
    entries = []
    for iid, rec in settings_manager.list_instances(domain).items():
        type_id = rec.get("type") if isinstance(rec.get("type"), str) else iid
        provider = hub.get(domain, type_id)
        settings = rec.get("settings") if isinstance(rec.get("settings"), dict) else {}
        entry = {
            "instance_id": iid,
            "provider_type": type_id,
            "label": rec.get("label") if isinstance(rec.get("label"), str) else type_id,
            "selected": selected == iid,
            "availability": (
                provider.availability(settings, instance_id=iid)
                if provider is not None
                else "needs_configuration"
            ),
        }
        entries.append(entry)
    return jsonify({
        "domain": domain,
        "selected_instance_id": selected,
        "instances": entries,
    })


@providers_bp.route("/api/providers/<domain>/instances", methods=["POST"])
def create_domain_instance(domain):
    """Create a configured instance of a provider type.

    Body: `{ "provider_type": "<type>", "instance_id"?, "label"?, "settings"? }`.
    When `instance_id` is omitted a unique id is minted so a second binding of
    an already-instanced type is always possible.
    """
    denied = _require_loopback()
    if denied:
        return denied
    _, err = _resolve_domain(domain)
    if err is not None:
        return err
    body, err = _json_object()
    if err is not None:
        return err

    provider_type = body.get("provider_type") or body.get("type") or body.get("provider_id")
    if not isinstance(provider_type, str) or not provider_type:
        return _error(
            "INVALID_REQUEST",
            "provider_type must be a non-empty string",
            400,
        )
    provider, err = _resolve_provider_type(domain, provider_type)
    if err is not None:
        return err

    instance_id = body.get("instance_id")
    if instance_id is not None and (not isinstance(instance_id, str) or not instance_id):
        return _error("INVALID_REQUEST", "instance_id must be a non-empty string", 400)

    label = body.get("label")
    if label is not None and not isinstance(label, str):
        return _error("INVALID_REQUEST", "label must be a string", 400)

    settings_patch = body.get("settings")
    if settings_patch is not None and not isinstance(settings_patch, dict):
        return _error("INVALID_REQUEST", "settings must be an object", 400)

    merged = settings_manager.merge_provider_settings(
        domain,
        instance_id or provider.id,
        settings_patch or {},
        provider.settings_schema(),
    ) if settings_patch else None

    if merged is not None:
        issues = _issue_dicts(provider.validate_settings(merged))
        if any(i.get("severity") == "error" for i in issues):
            return _error("SETTINGS_INVALID", "Validation failed", 400, {"issues": issues})
    else:
        issues = []
        merged = {}

    created_id = settings_manager.upsert_instance(
        domain,
        provider_type=provider.id,
        instance_id=instance_id,
        label=label or provider.label,
        settings=merged if settings_patch is not None else None,
    )
    invalidate_settings_cache(domain)
    stored = settings_manager.get_instance_settings(domain, created_id)
    return jsonify({
        "ok": True,
        "domain": domain,
        "instance_id": created_id,
        "provider_type": provider.id,
        "instance": _instance_payload(domain, provider, created_id, stored),
        "issues": issues,
    }), 201


# ---------------------------------------------------------------------------
# Instance-scoped routes (step 3.1 path segment)
# ---------------------------------------------------------------------------

@providers_bp.route("/api/providers/<domain>/instances/<instance_id>", methods=["GET"])
def instance_detail(domain, instance_id):
    """One configured instance's browser-safe metadata."""
    denied = _require_loopback()
    if denied:
        return denied
    provider, iid, stored, err = _resolve_instance(domain, instance_id)
    if err is not None:
        return err
    return jsonify(_instance_payload(domain, provider, iid, stored))


@providers_bp.route(
    "/api/providers/<domain>/instances/<instance_id>/capabilities", methods=["GET"]
)
def instance_capabilities(domain, instance_id):
    denied = _require_loopback()
    if denied:
        return denied
    provider, iid, _stored, err = _resolve_instance(domain, instance_id)
    if err is not None:
        return err
    spec = DOMAINS[domain]
    return jsonify({
        "domain": domain,
        "instance_id": iid,
        "provider_id": provider.id,
        "provider_type": provider.id,
        "capabilities": dict(provider.capabilities),
        "vocabulary": sorted(spec.capability_vocabulary),
    })


@providers_bp.route(
    "/api/providers/<domain>/instances/<instance_id>/health", methods=["GET"]
)
def instance_health(domain, instance_id):
    """Probe health against this instance's stored settings."""
    denied = _require_loopback()
    if denied:
        return denied
    provider, iid, stored, err = _resolve_instance(domain, instance_id)
    if err is not None:
        return err
    return jsonify({
        "provider_id": provider.id,
        "provider_type": provider.id,
        "instance_id": iid,
        "domain": domain,
        "health": _health_dict(provider, stored, instance_id=iid),
    })


@providers_bp.route(
    "/api/providers/<domain>/instances/<instance_id>/test", methods=["POST"]
)
def test_instance_settings(domain, instance_id):
    denied = _require_loopback()
    if denied:
        return denied
    provider, iid, _stored, err = _resolve_instance(domain, instance_id)
    if err is not None:
        return err
    patch = request.get_json(silent=True) or {}
    merged = settings_manager.merge_provider_settings(
        domain, iid, patch, provider.settings_schema()
    )
    return jsonify({
        "provider_id": provider.id,
        "provider_type": provider.id,
        "instance_id": iid,
        "domain": domain,
        "health": _health_dict(provider, merged, instance_id=iid),
    })


@providers_bp.route(
    "/api/providers/<domain>/instances/<instance_id>/validate", methods=["POST"]
)
def validate_instance_settings(domain, instance_id):
    denied = _require_loopback()
    if denied:
        return denied
    provider, iid, _stored, err = _resolve_instance(domain, instance_id)
    if err is not None:
        return err
    patch = request.get_json(silent=True) or {}
    merged = settings_manager.merge_provider_settings(
        domain, iid, patch, provider.settings_schema()
    )
    issues = _issue_dicts(provider.validate_settings(merged))
    return jsonify({
        "valid": not any(i.get("severity") == "error" for i in issues),
        "issues": issues,
        "provider_id": provider.id,
        "provider_type": provider.id,
        "instance_id": iid,
        "domain": domain,
    })


@providers_bp.route(
    "/api/providers/<domain>/instances/<instance_id>/settings", methods=["GET"]
)
def get_instance_settings_route(domain, instance_id):
    denied = _require_loopback()
    if denied:
        return denied
    provider, iid, stored, err = _resolve_instance(domain, instance_id)
    if err is not None:
        return err
    schema = provider.settings_schema()
    return jsonify({
        "provider_id": provider.id,
        "provider_type": provider.id,
        "instance_id": iid,
        "domain": domain,
        "settings": settings_manager.redact_settings(stored, schema),
        "schema": schema,
        "manifest": _instance_payload(domain, provider, iid, stored),
    })


@providers_bp.route(
    "/api/providers/<domain>/instances/<instance_id>/settings", methods=["PUT"]
)
def put_instance_settings_route(domain, instance_id):
    denied = _require_loopback()
    if denied:
        return denied
    provider, iid, _stored, err = _resolve_instance(domain, instance_id)
    if err is not None:
        return err
    patch, err = _json_object()
    if err is not None:
        return err

    merged = settings_manager.merge_provider_settings(
        domain, iid, patch, provider.settings_schema()
    )
    issues = _issue_dicts(provider.validate_settings(merged))
    if any(i.get("severity") == "error" for i in issues):
        return _error("SETTINGS_INVALID", "Validation failed", 400, {"issues": issues})

    settings_manager.set_instance_settings(
        domain, iid, merged, provider_type=provider.id, label=provider.label
    )
    invalidate_settings_cache(domain)
    return jsonify({
        "ok": True,
        "issues": issues,
        "provider_id": provider.id,
        "provider_type": provider.id,
        "instance_id": iid,
        "domain": domain,
    })


# ---------------------------------------------------------------------------
# Type-scoped routes (default instance of the type)
# ---------------------------------------------------------------------------

@providers_bp.route("/api/providers/<domain>/<provider_id>", methods=["GET"])
def provider_detail(domain, provider_id):
    """One provider type's metadata, plus whether its default instance is selected."""
    denied = _require_loopback()
    if denied:
        return denied
    # Prefer a configured instance when the path id is an instance id.
    rec = settings_manager.get_instance_record(domain, provider_id)
    if rec is not None:
        provider, iid, stored, err = _resolve_instance(domain, provider_id)
        if err is not None:
            return err
        return jsonify(_instance_payload(domain, provider, iid, stored))

    provider, err = _resolve_provider_type(domain, provider_id)
    if err is not None:
        return err
    stored = settings_manager.get_provider_settings(domain, provider.id)
    payload = provider.to_dict(stored, instance_id=provider.id)
    payload["instance_id"] = provider.id
    payload["selected"] = selected_instances().get(domain) == provider.id
    # Type-level selected also true when any selected instance is of this type
    # and uses the default id convention.
    if not payload["selected"]:
        payload["selected"] = selected_providers().get(domain) == provider.id and (
            selected_instances().get(domain) in (None, provider.id)
        )
    return jsonify(payload)


@providers_bp.route("/api/providers/<domain>/<provider_id>/capabilities", methods=["GET"])
def provider_capabilities(domain, provider_id):
    """Declared capabilities plus the domain's capability vocabulary (§20.4).

    Answered from manifest metadata alone — no provider code runs.
    """
    denied = _require_loopback()
    if denied:
        return denied
    provider, err = _resolve_provider_type(domain, provider_id)
    if err is not None:
        return err
    spec = DOMAINS[domain]
    return jsonify({
        "domain": domain,
        "provider_id": provider.id,
        "provider_type": provider.id,
        "capabilities": dict(provider.capabilities),
        "vocabulary": sorted(spec.capability_vocabulary),
    })


@providers_bp.route("/api/providers/<domain>/<provider_id>/health", methods=["GET"])
def provider_health(domain, provider_id):
    """Probe health against the default instance's stored settings."""
    denied = _require_loopback()
    if denied:
        return denied
    provider, iid, stored, err = _resolve_instance(domain, provider_id)
    if err is not None:
        # Fall back to type resolution for a type that has no stored instance yet.
        provider, err = _resolve_provider_type(domain, provider_id)
        if err is not None:
            return err
        iid = provider.id
        stored = settings_manager.get_provider_settings(domain, provider.id)
    return jsonify({
        "provider_id": provider.id,
        "provider_type": provider.id,
        "instance_id": iid,
        "domain": domain,
        "health": _health_dict(provider, stored, instance_id=iid),
    })


@providers_bp.route("/api/providers/<domain>/<provider_id>/test", methods=["POST"])
def test_provider_settings(domain, provider_id):
    """Probe health against stored settings overlaid with a candidate patch."""
    denied = _require_loopback()
    if denied:
        return denied
    provider, iid, _stored, err = _resolve_instance(domain, provider_id)
    if err is not None:
        provider, err = _resolve_provider_type(domain, provider_id)
        if err is not None:
            return err
        iid = provider.id
    patch = request.get_json(silent=True) or {}
    merged = settings_manager.merge_provider_settings(
        domain, iid, patch, provider.settings_schema()
    )
    return jsonify({
        "provider_id": provider.id,
        "provider_type": provider.id,
        "instance_id": iid,
        "domain": domain,
        "health": _health_dict(provider, merged, instance_id=iid),
    })


@providers_bp.route("/api/providers/<domain>/<provider_id>/validate", methods=["POST"])
def validate_provider_settings(domain, provider_id):
    """Validate provider settings without saving."""
    denied = _require_loopback()
    if denied:
        return denied
    provider, iid, _stored, err = _resolve_instance(domain, provider_id)
    if err is not None:
        provider, err = _resolve_provider_type(domain, provider_id)
        if err is not None:
            return err
        iid = provider.id
    patch = request.get_json(silent=True) or {}
    merged = settings_manager.merge_provider_settings(
        domain, iid, patch, provider.settings_schema()
    )
    issues = _issue_dicts(provider.validate_settings(merged))
    return jsonify({
        "valid": not any(i.get("severity") == "error" for i in issues),
        "issues": issues,
        "provider_id": provider.id,
        "provider_type": provider.id,
        "instance_id": iid,
        "domain": domain,
    })


@providers_bp.route("/api/providers/<domain>/<provider_id>/settings", methods=["GET"])
def get_provider_settings(domain, provider_id):
    """Stored settings for the default instance of a type (or a named instance id)."""
    denied = _require_loopback()
    if denied:
        return denied
    provider, iid, stored, err = _resolve_instance(domain, provider_id)
    if err is not None:
        provider, err = _resolve_provider_type(domain, provider_id)
        if err is not None:
            return err
        iid = provider.id
        stored = settings_manager.get_provider_settings(domain, provider.id)
    schema = provider.settings_schema()
    return jsonify({
        "provider_id": provider.id,
        "provider_type": provider.id,
        "instance_id": iid,
        "domain": domain,
        # Secrets leave as the sentinel; environment fallbacks are never resolved
        # into this payload (contracts.md §22.6).
        "settings": settings_manager.redact_settings(stored, schema),
        "schema": schema,
        "manifest": _instance_payload(domain, provider, iid, stored),
    })


@providers_bp.route("/api/providers/<domain>/<provider_id>/settings", methods=["PUT"])
def put_provider_settings(domain, provider_id):
    """Merge a client patch over stored instance settings and save."""
    denied = _require_loopback()
    if denied:
        return denied
    provider, iid, _stored, err = _resolve_instance(domain, provider_id)
    if err is not None:
        provider, err = _resolve_provider_type(domain, provider_id)
        if err is not None:
            return err
        iid = provider.id
    patch, err = _json_object()
    if err is not None:
        return err

    # A secret submitted as the redaction sentinel leaves the stored value alone.
    merged = settings_manager.merge_provider_settings(
        domain, iid, patch, provider.settings_schema()
    )
    issues = _issue_dicts(provider.validate_settings(merged))
    if any(i.get("severity") == "error" for i in issues):
        return _error("SETTINGS_INVALID", "Validation failed", 400, {"issues": issues})

    settings_manager.set_instance_settings(
        domain, iid, merged, provider_type=provider.id, label=provider.label
    )
    # Options that depend on settings must refetch — changing an API key changes
    # what the provider can offer (contracts.md §23.4).
    invalidate_settings_cache(domain)
    return jsonify({
        "ok": True,
        "issues": issues,
        "provider_id": provider.id,
        "provider_type": provider.id,
        "instance_id": iid,
        "domain": domain,
    })


# ---------------------------------------------------------------------------
# Selection (contracts.md §24.2 — replaces the whole-blob PUT /api/settings/v2)
# ---------------------------------------------------------------------------

@providers_bp.route("/api/providers/<domain>/selection", methods=["PUT"])
def put_domain_selection(domain):
    """Set the selected instance for one domain.

    Accepts `instance_id` (preferred) or `provider_id` (selects the default
    instance of that type). Selection is never blocked by availability or
    health: a `needs_configuration` or failing instance may be selected and the
    issues travel back so the caller can prompt (§21.5, §24.2).
    """
    denied = _require_loopback()
    if denied:
        return denied
    _, err = _resolve_domain(domain)
    if err is not None:
        return err
    body, err = _json_object()
    if err is not None:
        return err

    instance_id = body.get("instance_id")
    provider_id = body.get("provider_id")
    if isinstance(instance_id, str) and instance_id:
        target = instance_id
    elif isinstance(provider_id, str) and provider_id:
        target = provider_id
    else:
        return _error(
            "INVALID_REQUEST",
            "instance_id or provider_id must be a non-empty string",
            400,
        )

    provider, iid, stored, err = _resolve_instance(domain, target)
    if err is not None:
        # Selecting a type that is registered but has no stored instance yet:
        # create the default instance and select it.
        provider, err = _resolve_provider_type(domain, target)
        if err is not None:
            return err
        iid = provider.id
        stored = settings_manager.get_provider_settings(domain, provider.id)

    # Always the canonical instance id — never an alias (§19.3).
    settings_manager.set_selected_instance(domain, iid)
    # A context-free caller resolves options against the selection, so the old
    # instance's answers must not survive the switch (§23.4).
    invalidate_settings_cache(domain)
    return jsonify({
        "domain": domain,
        "selected": iid,
        "selected_instance_id": iid,
        "provider_type": provider.id,
        "availability": provider.availability(stored, instance_id=iid),
        "issues": _issue_dicts(provider.validate_settings(stored)),
    })


# ---------------------------------------------------------------------------
# Whole settings document
# ---------------------------------------------------------------------------

@providers_bp.route("/api/settings/v2", methods=["GET"])
def get_settings_v2():
    """Return the nested settings document, with secrets redacted.

    Secret values are write-only (contracts.md §22.6): they leave the process only
    as the `"***"` sentinel, which `PUT`/`PATCH` treat as "unchanged".
    """
    denied = _require_loopback()
    if denied:
        return denied
    settings = settings_manager.load_settings()
    return jsonify(settings_manager.redact_settings(settings))


@providers_bp.route("/api/settings/v2", methods=["PUT"])
def put_settings_v2():
    """Replace the whole settings document — import and reset only.

    Changing a selection goes through `PUT /api/providers/<domain>/selection`
    instead (§24.2). The client round-trips the redacted document, so every secret
    submitted as the sentinel is restored from the stored value (§22.6).
    """
    denied = _require_loopback()
    if denied:
        return denied
    data, err = _json_object()
    if err is not None:
        return err
    return _save_settings_document(data)


@providers_bp.route("/api/settings/v2", methods=["PATCH"])
def patch_settings_v2():
    """Deep-merge a partial settings document (§24.2).

    Field-level replacement for everything the targeted selection endpoint does
    not cover, without the lost-update window of a whole-document round trip.
    """
    denied = _require_loopback()
    if denied:
        return denied
    patch, err = _json_object()
    if err is not None:
        return err
    stored = settings_manager.load_settings()
    return _save_settings_document(_deep_merge(stored, patch), stored=stored)


def _save_settings_document(data, stored=None):
    """Validate, restore sentinel secrets, and persist a settings document."""
    issues = settings_manager.validate_settings(data)
    if any(i["severity"] == "error" for i in issues):
        return _error("SETTINGS_INVALID", "Invalid settings", 400, {"issues": issues})
    if stored is None:
        stored = settings_manager.load_settings()
    settings_manager.save_settings(
        settings_manager.restore_redacted_secrets(stored, data)
    )
    return jsonify({"ok": True, "issues": issues})


def _deep_merge(base, patch):
    """Recursively merge `patch` over `base`; a non-dict value replaces wholesale."""
    merged = dict(base)
    for key, value in patch.items():
        current = merged.get(key)
        if isinstance(value, dict) and isinstance(current, dict):
            merged[key] = _deep_merge(current, value)
        else:
            merged[key] = value
    return merged
