"""Backend-approved async option sources (step 2.3, parameterized in step 12.2).

Every `options_source` identifier in the registry and every provider settings
`ui.options_source` resolves through this allowlist — a schema-provided URL is
never fetched (contracts.md §11).

Step 12.2 implements the parameterized envelope frozen in §23: a resolver now
receives a **validated, normalized** context (domain, provider, node type,
project) rather than nothing at all, which is what lets one dropdown depend on
the selected provider. Two consequences follow directly:

  - `_provider_options` stops hardcoding image and video (P32). One
    resolver serves all five `*_providers` sources, reading the domain off the
    source's `OptionSourceSpec`, so a sixth domain is a spec entry and nothing
    else.
  - the cache key is `(source, normalized_context)` rather than the bare source
    (§23.4). A per-source cache was already wrong the moment options depend on
    settings: changing an API key has to make the voice list refetch.

Resolvers import their data sources lazily so importing this module stays cheap.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field
from threading import RLock

from loguru import logger

from .registry import ASYNC_OPTION_SOURCES, OptionSourceSpec

EXPORT_PROFILES = ["yt_shorts", "tiktok", "reels", "yt_landscape", "square"]

# Node config fields that name a provider, newest first (contracts.md §40.1).
# 12.3 converted all five provider-backed nodes to a `provider`-widget field, so
# a node's schema now answers "which provider is this configured for?" by
# itself. These names stay as the fallback for a document that has not been
# migrated: `POST /api/workflow/validate` accepts a client-supplied document
# that never went through `migrate_workflow`.
PROVIDER_CONFIG_FIELDS = ("provider_id", "provider", "engine")

# §23.4 — at most this many context variations are cached per source, so query
# parameters cannot grow the cache without limit.
MAX_CACHE_ENTRIES_PER_SOURCE = 64
# §23.4 — `cache="settings"` entries also expire on their own, so an out-of-band
# settings edit is picked up without an explicit invalidation.
SETTINGS_CACHE_TTL_SECONDS = 300


class OptionContextError(ValueError):
    """A context parameter was unknown, malformed, or did not resolve (§23.3).

    Surfaced as `OPTION_CONTEXT_INVALID` / 400. The message names the parameter
    but never echoes a resolver's internals.
    """


def _opt(value, label=None):
    return {"value": value, "label": label or value}


# ---------------------------------------------------------------------------
# Context validation (contracts.md §23.1)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OptionContext:
    """The validated, normalized context one resolver call runs under.

    `values` holds only the parameters the source declares, already normalized —
    a provider alias has become the canonical id — so it is both the cache key
    and the `context` echoed to the client (§23.2).
    """

    source: str
    spec: OptionSourceSpec
    values: dict = field(default_factory=dict)

    @property
    def domain(self) -> str | None:
        """The domain this resolution is scoped to, declared or implied."""
        return self.values.get("domain") or self.spec.domain

    @property
    def provider(self) -> str | None:
        return self.values.get("provider")

    @property
    def key(self) -> tuple:
        return (self.source, tuple(sorted(self.values.items())))


def _validate_domain(spec: OptionSourceSpec, value: str) -> str:
    from scriptase.providers.domains import DOMAINS, canonical_domain

    # A retired V2 spelling (`storyboard`, `animator`, `scene_blueprint`)
    # normalizes to its canonical id here, so the *normalized* context is what
    # reaches the resolver and the cache key. Two spellings of one domain must
    # not become two cache entries.
    value = canonical_domain(value)
    if value not in DOMAINS:
        raise OptionContextError("domain is not a known provider domain")
    # A source scoped to one domain accepts only that domain. Answering
    # `tts_voices?domain=image` with the TTS fallback list would be a nonsense
    # pairing that the client could then cache and save.
    if spec.domain is not None and value != spec.domain:
        raise OptionContextError("domain is not valid for this option source")
    return value


def _validate_provider(domain: str | None, value: str) -> str:
    """Resolve a provider id or alias to the canonical id within `domain`."""
    from scriptase.providers.hub import hub

    if domain is None:
        raise OptionContextError("provider requires a domain")
    provider = hub.get(domain, value)
    if provider is None:
        raise OptionContextError("provider is not registered for this domain")
    return provider.id


def _validate_node_type(value: str) -> str:
    from .registry import all_node_types

    if value not in all_node_types():
        raise OptionContextError("node_type is not a known node type")
    return value


def _validate_project_id(value: str) -> str:
    from scriptase.shared.security import sanitize_project_id

    if sanitize_project_id(value) != value:
        raise OptionContextError("project_id is not a valid project identifier")
    return value


def _selected_provider(domain: str) -> str | None:
    """The domain's selected provider *type*, then its catalog default (§24.1).

    Step 3.1 stores a selected *instance* id; this helper returns the type of
    that instance so option sources and node defaults keep speaking package ids.
    """
    from scriptase.providers import settings_manager
    from scriptase.providers.domains import DOMAINS
    from scriptase.providers.hub import hub

    _iid, type_id, _settings = settings_manager.resolve_instance(domain)
    spec = DOMAINS.get(domain)
    for provider_id in (type_id, spec.default_provider if spec else None):
        if provider_id:
            provider = hub.get(domain, provider_id)
            if provider is not None:
                return provider.id
    return None


def build_context(source: str, params: dict | None = None) -> OptionContext:
    """Validate raw query parameters against a source's context allowlist.

    Raises `KeyError` for an unknown source and `OptionContextError` for a
    parameter that is not accepted, not well-formed, or does not resolve. A
    declared parameter may be omitted: `domain` then falls back to the source's
    own domain and `provider` to that domain's selection, which is what keeps
    every existing context-free caller working (§23.1).
    """
    spec = ASYNC_OPTION_SOURCES[source]
    supplied = {k: v for k, v in (params or {}).items() if v not in (None, "")}

    unknown = sorted(set(supplied) - set(spec.context))
    if unknown:
        raise OptionContextError(f"unsupported context parameter: {unknown[0]}")

    values: dict = {}
    for name in spec.context:
        raw = supplied.get(name)
        if raw is not None and not isinstance(raw, str):
            raise OptionContextError(f"{name} must be a string")
        if name == "domain":
            values["domain"] = _validate_domain(spec, raw) if raw else spec.domain
        elif name == "provider":
            domain = values.get("domain") or spec.domain
            values["provider"] = (
                _validate_provider(domain, raw) if raw else _selected_provider(domain)
            )
        elif name == "node_type":
            values["node_type"] = _validate_node_type(raw) if raw else None
        elif name == "project_id":
            values["project_id"] = _validate_project_id(raw) if raw else None
        else:  # pragma: no cover - guarded by the spec/resolver parity assert
            raise OptionContextError(f"unsupported context parameter: {name}")

    # An unresolvable optional parameter stays out of the key entirely, so the
    # "no provider selected" case shares one cache entry rather than one per
    # spelling of absence.
    return OptionContext(
        source=source,
        spec=spec,
        values={k: v for k, v in values.items() if v is not None},
    )


# ---------------------------------------------------------------------------
# Resolvers — every one takes the validated context
# ---------------------------------------------------------------------------


def _tts_voices(ctx: OptionContext):
    """Voices for the context's TTS provider (step 15.2).

    The catalog comes from `scriptase.modules.tts.dispatch`, the same helper
    `GET /api/tts/voices` answers with, so the canvas dropdown and the legacy
    page cannot disagree about what a provider offers. Before this the resolver
    read a settings schema while the route asked one provider's API directly,
    and a provider whose voices live behind that API — every cloud one — was
    simply unreachable from a node.

    The final fallback is load-bearing: with no provider resolved — an empty
    catalog, a selection pointing at an uninstalled provider — the node must
    still offer the voices the default engine accepts rather than an empty list.
    It reads the local engine's catalog straight off the provider package, which
    is where V2's `tts/routes.py::VOICES` re-exported it from anyway; going
    through the blueprint was the indirection, not the source. The accessor is
    named `local_engine` rather than after a provider because this module is a
    §26 zero-touch surface and may not contain a provider id.
    """
    from scriptase.providers.hub import hub
    from scriptase.modules.tts import dispatch

    instance = hub.get(ctx.domain, ctx.provider) if ctx.domain and ctx.provider else None
    if instance is not None:
        options = [
            _opt(voice["id"], voice["label"]) for voice in dispatch.list_voices(instance)
        ]
        if options:
            return options
    from scriptase.modules.tts.providers import local_engine

    return [_opt(voice) for voice in local_engine().VOICES]


def _story_tones(_ctx: OptionContext):
    from scriptase.modules.music.selector import TONE_MUSIC_MAP

    return [_opt("", "—")] + [_opt(tone) for tone in sorted(TONE_MUSIC_MAP)]


def _style_templates(_ctx: OptionContext):
    from scriptase.modules.scene_director.templates import TEMPLATES_BY_ID

    options = []
    for template_id in sorted(TEMPLATES_BY_ID):
        template = TEMPLATES_BY_ID[template_id] or {}
        options.append(_opt(template_id, template.get("name") or template_id))
    return options


def _provider_options(ctx: OptionContext):
    """Registered providers for the source's domain (replaces P32).

    Reads the domain off the spec, so all five `*_providers` sources — including
    the three added in this step — share one resolver and a sixth domain needs
    no code here. A provider that failed discovery is deliberately absent: an
    excluded id is not a legal saved value.
    """
    from scriptase.providers.hub import hub

    if not ctx.domain:  # pragma: no cover - every *_providers spec sets a domain
        raise RuntimeError(f"option source {ctx.source} has no domain")
    return [
        _opt(provider.id, provider.manifest.label or provider.id)
        for provider in hub.list(ctx.domain)
    ]


def _image_models(ctx: OptionContext):
    """The selected provider's own model list (§22.4, P32 closed in 14.2).

    This used to import one provider's module directly, so a second provider
    with a different catalog would have shown the first one's models. The list
    now comes from the provider's optional `list_models()` hook, which is why
    the source declares a `provider` context parameter.

    The empty first option means "let the provider choose", matching the
    `image_model: ""` default in its settings schema.
    """
    options = [_opt("", "Auto")]
    for model in _provider_models(ctx):
        if not isinstance(model, dict) or not model.get("id"):
            continue
        label = model.get("name") or model["id"]
        price = model.get("price")
        options.append(_opt(model["id"], f"{label} (${price})" if price else label))
    return options


def _provider_models(ctx: OptionContext) -> list:
    """Ask the selected provider for its models. No hook means no models."""
    from scriptase.providers import settings_manager
    from scriptase.providers.hub import hub

    domain = ctx.domain
    if ctx.provider:
        provider_id = ctx.provider
        instance_key = ctx.provider
    else:
        instance_key, provider_id, _stored = settings_manager.resolve_instance(domain)
    instance = hub.get(domain, provider_id) if provider_id else None
    if instance is None:
        return []
    hook = instance._resolve("list_models")
    if not callable(hook):
        return []
    try:
        models = hook(
            instance.resolve_settings(
                settings_manager.get_provider_settings(
                    domain, instance_key or instance.id
                )
            )
        )
    except Exception as exc:
        # An option list is advisory; a broken provider hook must not 500 the
        # editor. The redacted logger is the only place the cause is recorded.
        logger.warning("[options] list_models failed for {}: {}", instance.id, exc)
        return []
    return list(models or [])


def _export_profiles(_ctx: OptionContext):
    return [_opt(profile) for profile in EXPORT_PROFILES]


def _caption_presets(_ctx: OptionContext):
    from scriptase.modules.captions.presets import CAPTION_PRESETS

    options = []
    for preset_id, preset in CAPTION_PRESETS.items():
        label = preset_id
        if isinstance(preset, dict):
            label = preset.get("name") or preset.get("label") or preset_id
        options.append(_opt(preset_id, label))
    return options


_RESOLVERS = {
    "tts_voices": _tts_voices,
    "script_providers": _provider_options,
    "scene_director_providers": _provider_options,
    "tts_providers": _provider_options,
    "image_providers": _provider_options,
    "video_providers": _provider_options,
    "image_models": _image_models,
    "story_tones": _story_tones,
    "style_templates": _style_templates,
    "export_profiles": _export_profiles,
    "caption_presets": _caption_presets,
}

# The registry allowlist and the resolver table must never drift.
assert set(_RESOLVERS) == set(ASYNC_OPTION_SOURCES), (
    "options resolvers out of sync with ASYNC_OPTION_SOURCES"
)


# ---------------------------------------------------------------------------
# Cache (contracts.md §23.4)
# ---------------------------------------------------------------------------


class _OptionCache:
    """Bounded, per-source, context-keyed cache with three expiry policies.

    Failures are never cached: a provider that is unreachable for one request
    must be retried on the next, not remembered as empty for the process
    lifetime.
    """

    def __init__(self):
        self._entries: OrderedDict[tuple, tuple[float, list]] = OrderedDict()
        self._lock = RLock()

    def get(self, ctx: OptionContext):
        expiry_policy = ctx.spec.cache
        with self._lock:
            entry = self._entries.get(ctx.key)
            if entry is None:
                return None
            stored_at, options = entry
            if (
                expiry_policy == "settings"
                and time.monotonic() - stored_at > SETTINGS_CACHE_TTL_SECONDS
            ):
                del self._entries[ctx.key]
                return None
            self._entries.move_to_end(ctx.key)
            return options

    def put(self, ctx: OptionContext, options: list):
        with self._lock:
            self._entries[ctx.key] = (time.monotonic(), options)
            self._entries.move_to_end(ctx.key)
            self._evict(ctx.source)

    def _evict(self, source: str):
        """LRU-evict within one source so a busy source cannot starve the rest."""
        keys = [key for key in self._entries if key[0] == source]
        for key in keys[: max(0, len(keys) - MAX_CACHE_ENTRIES_PER_SOURCE)]:
            del self._entries[key]

    def drop(self, predicate):
        with self._lock:
            for key in [key for key in self._entries if predicate(key)]:
                del self._entries[key]

    def clear(self):
        with self._lock:
            self._entries.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._entries)


_CACHE = _OptionCache()


def _sources_with_policy(policy: str) -> set[str]:
    return {
        source
        for source, spec in ASYNC_OPTION_SOURCES.items()
        if spec.cache == policy
    }


def invalidate_discovery_cache():
    """Drop every `cache="discovery"` entry — a provider appeared or vanished."""
    sources = _sources_with_policy("discovery")
    _CACHE.drop(lambda key: key[0] in sources)


def invalidate_settings_cache(domain: str | None = None):
    """Drop `cache="settings"` entries after a settings or selection write.

    Scoped to one domain when given (§23.4): changing a TTS API key must not
    discard an unrelated domain's resolved options.
    """
    sources = _sources_with_policy("settings")

    def matches(key):
        source, context = key
        if source not in sources:
            return False
        if domain is None:
            return True
        scoped = dict(context).get("domain") or ASYNC_OPTION_SOURCES[source].domain
        return scoped == domain

    _CACHE.drop(matches)


def clear_option_cache():
    """Drop every cached entry. Test hook and hard reset."""
    _CACHE.clear()


# ---------------------------------------------------------------------------
# Public resolution
# ---------------------------------------------------------------------------


def _resolve(ctx: OptionContext) -> list:
    cached = _CACHE.get(ctx)
    if cached is not None:
        return cached
    try:
        options = _RESOLVERS[ctx.source](ctx)
    except Exception as exc:  # data source unavailable — never a 500
        logger.warning("option source {} failed: {}", ctx.source, exc)
        raise RuntimeError(f"Option source {ctx.source} is unavailable") from exc
    _CACHE.put(ctx, options)
    return options


def resolve_options(source: str, params: dict | None = None):
    """Return `(options, context)` for an allowlisted source, or `(None, None)`.

    Raises `OptionContextError` when the context is rejected and `RuntimeError`
    when a known source fails to load (surfaced as `OPTION_CONTEXT_INVALID` and
    `PROVIDER_UNAVAILABLE` by the route).
    """
    if source not in ASYNC_OPTION_SOURCES:
        return None, None
    ctx = build_context(source, params)
    return _resolve(ctx), dict(ctx.values)


def allowed_option_values(source: str, context: dict | None = None):
    """Frozen set of legal values for a source, or None when it cannot answer.

    Server-side validation of submitted option values (step 6.3) still fails
    open: a bad value is rejected, but an unavailable provider — or a context
    that no longer resolves — must never block saving an otherwise-valid
    workflow (§23.3).
    """
    if source not in ASYNC_OPTION_SOURCES:
        return None
    try:
        ctx = build_context(source, context)
        return frozenset(option["value"] for option in _resolve(ctx))
    except Exception as exc:
        logger.warning("option source {} unavailable for validation: {}", source, exc)
        return None


def configured_provider(configuration: dict | None, fields: dict | None = None):
    """Return `(domain, provider_id)` for the provider a node is configured with.

    The `provider` widget is authoritative: it carries its own
    `provider_domain`, so one lookup answers for every domain and a sixth domain
    needs no edit here (step 12.3). `PROVIDER_CONFIG_FIELDS` is the fallback for
    a document that has not been migrated, and it cannot name a domain — the
    caller supplies one or gets `None`.

    The field's schema default counts. A node that never wrote the key still
    runs on that default, so resolving to the *global* selection instead would
    make changing that selection reinterpret saved workflows, which §24.1 rule 2
    forbids.
    """
    fields = fields or {}
    configuration = configuration or {}
    for name, field in fields.items():
        if (field or {}).get("type") != "provider":
            continue
        value = configuration.get(name)
        if not isinstance(value, str) or not value:
            value = field.get("default")
        if isinstance(value, str) and value:
            return field.get("provider_domain"), value
        return field.get("provider_domain"), None
    for name in PROVIDER_CONFIG_FIELDS:
        value = configuration.get(name)
        if value is None:
            value = ((fields.get(name) or {}).get("default"))
        if isinstance(value, str) and value:
            return None, value
    return None, None


def config_option_context(source: str, configuration: dict | None, fields: dict | None = None):
    """Context for validating one node configuration's value for `source`.

    A context-sensitive value is checked against the provider **this node** will
    run with, never against a union across providers — accepting one provider's
    voice for another provider's node would defer a deterministic configuration
    error until execution (§23.3).

    The provider field's schema default counts. A node that never wrote `engine`
    still runs on the default engine, so validating its voice against the global
    selection instead would make changing that selection invalidate saved
    workflows — exactly what §24.1 rule 2 forbids. Only a node type with no
    provider field at all falls through to the domain selection.
    """
    spec = ASYNC_OPTION_SOURCES.get(source)
    if spec is None or "provider" not in spec.context:
        return None
    _domain, provider_id = configured_provider(configuration, fields)
    return {"provider": provider_id} if provider_id else None


__all__ = [
    "EXPORT_PROFILES",
    "OptionContext",
    "OptionContextError",
    "allowed_option_values",
    "build_context",
    "clear_option_cache",
    "config_option_context",
    "configured_provider",
    "invalidate_discovery_cache",
    "invalidate_settings_cache",
    "resolve_options",
]
