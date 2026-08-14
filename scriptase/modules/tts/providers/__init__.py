"""TTS provider package — compatibility facade over the provider hub.

The registry, discovery, and lookup logic lives in
`scriptase.providers.hub`; this module only binds the `tts` domain and
keeps the historical import surface working.
"""

from scriptase.providers.hub import bind_domain

registry, discover, get_provider, list_providers, init_tts_registry = bind_domain('tts')


def kokoro_engine():
    """The one Kokoro engine module in this process (contracts.md B5 / K1).

    `scriptase/modules/tts/routes.py` used to declare its own model handle, G2P handle,
    inference lock, and voice catalog, and the provider package declared a
    second, never-populated copy of all four. Both now come from here, so there
    is exactly one ONNX session and one lock however a caller arrives.

    Resolved through the registry rather than imported: the folder has no
    `__init__.py` and loads under a synthetic module name, so `registry.get` is
    the only way to reach the object the platform actually serves (B8).
    """
    instance = registry.get('kokoro')
    if instance is None:
        # Discovery is idempotent; a caller arriving before boot finished (a
        # test, a CLI entry point) gets it on demand rather than an error.
        discover()
        instance = registry.get('kokoro')
    if instance is None:
        raise RuntimeError("The 'kokoro' TTS provider is not registered")
    return instance.provider_module


def local_engine():
    """The local (offline) TTS engine module, named without naming a provider.

    Callers outside this package — the `tts_voices` option source is the only
    one — need the shipped voice catalog as a last-resort fallback but must not
    contain a provider id, or the §26 zero-touch guard fails. Which provider is
    local is a fact about this package, so the id stays inside it.
    """
    return kokoro_engine()


__all__ = [
    'discover',
    'get_provider',
    'init_tts_registry',
    'kokoro_engine',
    'list_providers',
    'local_engine',
    'registry',
]
