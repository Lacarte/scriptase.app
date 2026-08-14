"""Unified provider API (step 11.5).

One blueprint serves the whole provider surface — catalog, domain and provider
detail, capabilities, health, settings read/write, and the targeted selection
write — from the process-wide hub (contracts.md §27). Before this step the same
five handlers lived in the editor blueprint and each re-imported the three domain
registries; the URLs are unchanged, only the owning module moved.

Policy, uniformly: loopback-only (`scriptase.shared.security.is_loopback_remote`) because
these payloads describe and mutate the credential store, and the one error
envelope `{"error": {"code", "message", "details?"}}` from contracts.md §6.
Secret values are write-only — every read leaves the process as the `"***"`
sentinel (§22.6) and every write treats the sentinel as "unchanged".
"""

from flask import Blueprint, jsonify, request

from scriptase.providers.catalog import build_catalog, catalog_version, selected_providers
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


def _resolve_provider(domain, provider_id):
    """Resolve one provider by canonical id then alias (§19.3).

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


def _issue_dicts(issues):
    """Normalize `ValidationIssue` objects to the frozen `{field, severity, message}`."""
    return [
        {"field": i.field, "severity": i.severity, "message": i.message}
        if hasattr(i, "field") else i
        for i in issues
    ]


def _health_dict(provider, settings):
    health = provider.health_check(settings)
    return {
        "status": health.status,
        "latency_ms": health.latency_ms,
        "message": health.message,
        # `details` is provider-authored and may echo a submitted secret (§21.5).
        "details": settings_manager.redact_settings(health.details or {}),
    }


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

@providers_bp.route("/api/providers", methods=["GET"])
def list_providers():
    """The one versioned catalog: every healthy, unavailable, deprecated, and
    broken provider, grouped by domain.

    Registered providers carry an `availability` of `available`,
    `needs_configuration`, or `degraded`; a provider that failed discovery is an
    `excluded[]` entry with its reason code (§21.4, §21.5).

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


@providers_bp.route("/api/providers/<domain>/<provider_id>", methods=["GET"])
def provider_detail(domain, provider_id):
    """One provider's browser-safe metadata, plus whether it is the selection."""
    denied = _require_loopback()
    if denied:
        return denied
    provider, err = _resolve_provider(domain, provider_id)
    if err is not None:
        return err
    stored = settings_manager.get_provider_settings(domain, provider.id)
    payload = provider.to_dict(stored)
    payload["selected"] = selected_providers().get(domain) == provider.id
    return jsonify(payload)


@providers_bp.route("/api/providers/<domain>/<provider_id>/capabilities", methods=["GET"])
def provider_capabilities(domain, provider_id):
    """Declared capabilities plus the domain's capability vocabulary (§20.4).

    Answered from manifest metadata alone — no provider code runs.
    """
    denied = _require_loopback()
    if denied:
        return denied
    provider, err = _resolve_provider(domain, provider_id)
    if err is not None:
        return err
    spec = DOMAINS[domain]
    return jsonify({
        "domain": domain,
        "provider_id": provider.id,
        "capabilities": dict(provider.capabilities),
        "vocabulary": sorted(spec.capability_vocabulary),
    })


# ---------------------------------------------------------------------------
# Health and validation
# ---------------------------------------------------------------------------

@providers_bp.route("/api/providers/<domain>/<provider_id>/health", methods=["GET"])
def provider_health(domain, provider_id):
    """Probe health against the *stored* settings. May perform I/O (§21.5)."""
    denied = _require_loopback()
    if denied:
        return denied
    provider, err = _resolve_provider(domain, provider_id)
    if err is not None:
        return err
    stored = settings_manager.get_provider_settings(domain, provider.id)
    return jsonify({
        "provider_id": provider.id,
        "domain": domain,
        "health": _health_dict(provider, stored),
    })


@providers_bp.route("/api/providers/<domain>/<provider_id>/test", methods=["POST"])
def test_provider_settings(domain, provider_id):
    """Probe health against stored settings overlaid with a candidate patch."""
    denied = _require_loopback()
    if denied:
        return denied
    provider, err = _resolve_provider(domain, provider_id)
    if err is not None:
        return err
    patch = request.get_json(silent=True) or {}
    merged = settings_manager.merge_provider_settings(
        domain, provider.id, patch, provider.settings_schema()
    )
    return jsonify({
        "provider_id": provider.id,
        "domain": domain,
        "health": _health_dict(provider, merged),
    })


@providers_bp.route("/api/providers/<domain>/<provider_id>/validate", methods=["POST"])
def validate_provider_settings(domain, provider_id):
    """Validate provider settings without saving."""
    denied = _require_loopback()
    if denied:
        return denied
    provider, err = _resolve_provider(domain, provider_id)
    if err is not None:
        return err
    patch = request.get_json(silent=True) or {}
    merged = settings_manager.merge_provider_settings(
        domain, provider.id, patch, provider.settings_schema()
    )
    issues = _issue_dicts(provider.validate_settings(merged))
    return jsonify({
        "valid": not any(i.get("severity") == "error" for i in issues),
        "issues": issues,
        "provider_id": provider.id,
        "domain": domain,
    })


# ---------------------------------------------------------------------------
# Per-provider settings
# ---------------------------------------------------------------------------

@providers_bp.route("/api/providers/<domain>/<provider_id>/settings", methods=["GET"])
def get_provider_settings(domain, provider_id):
    """Stored settings, its schema, and the provider's public metadata."""
    denied = _require_loopback()
    if denied:
        return denied
    provider, err = _resolve_provider(domain, provider_id)
    if err is not None:
        return err
    stored = settings_manager.get_provider_settings(domain, provider.id)
    schema = provider.settings_schema()
    return jsonify({
        "provider_id": provider.id,
        "domain": domain,
        # Secrets leave as the sentinel; environment fallbacks are never resolved
        # into this payload (contracts.md §22.6).
        "settings": settings_manager.redact_settings(stored, schema),
        "schema": schema,
        "manifest": provider.to_dict(stored),
    })


@providers_bp.route("/api/providers/<domain>/<provider_id>/settings", methods=["PUT"])
def put_provider_settings(domain, provider_id):
    """Merge a client patch over stored settings and save."""
    denied = _require_loopback()
    if denied:
        return denied
    provider, err = _resolve_provider(domain, provider_id)
    if err is not None:
        return err
    patch, err = _json_object()
    if err is not None:
        return err

    # A secret submitted as the redaction sentinel leaves the stored value alone.
    merged = settings_manager.merge_provider_settings(
        domain, provider.id, patch, provider.settings_schema()
    )
    issues = _issue_dicts(provider.validate_settings(merged))
    if any(i.get("severity") == "error" for i in issues):
        return _error("SETTINGS_INVALID", "Validation failed", 400, {"issues": issues})

    settings_manager.set_provider_settings(domain, provider.id, merged)
    # Options that depend on settings must refetch — changing an API key changes
    # what the provider can offer (contracts.md §23.4).
    invalidate_settings_cache(domain)
    return jsonify({
        "ok": True,
        "issues": issues,
        "provider_id": provider.id,
        "domain": domain,
    })


# ---------------------------------------------------------------------------
# Selection (contracts.md §24.2 — replaces the whole-blob PUT /api/settings/v2)
# ---------------------------------------------------------------------------

@providers_bp.route("/api/providers/<domain>/selection", methods=["PUT"])
def put_domain_selection(domain):
    """Set the selected provider for one domain.

    The targeted replacement for the read-modify-write of the whole settings
    document, which had a genuine lost-update window. Selection is never blocked
    by availability or health: a `needs_configuration` or failing provider may be
    selected and the issues travel back so the caller can prompt (§21.5, §24.2).
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

    provider_id = body.get("provider_id")
    if not isinstance(provider_id, str) or not provider_id:
        return _error("INVALID_REQUEST", "provider_id must be a non-empty string", 400)

    provider, err = _resolve_provider(domain, provider_id)
    if err is not None:
        return err

    stored = settings_manager.get_provider_settings(domain, provider.id)
    # Always the canonical id — an alias is never written to settings (§19.3).
    settings_manager.set_selected_provider(domain, provider.id)
    # A context-free caller resolves options against the selection, so the old
    # provider's answers must not survive the switch (§23.4).
    invalidate_settings_cache(domain)
    return jsonify({
        "domain": domain,
        "selected": provider.id,
        "availability": provider.availability(stored),
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
