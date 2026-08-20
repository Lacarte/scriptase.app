"""TTS provider package — compatibility facade over the provider hub.

The registry, discovery, and lookup logic lives in
`scriptase.providers.hub`; this module only binds the `tts` domain and
keeps the historical import surface working.
"""

from scriptase.providers.hub import bind_domain

registry, discover, get_provider, list_providers, init_tts_registry = bind_domain('tts')


__all__ = [
    'discover',
    'get_provider',
    'init_tts_registry',
    'list_providers',
    'registry',
]
