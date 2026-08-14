"""Storyboard provider package — compatibility facade over the provider hub.

The registry, discovery, and lookup logic lives in
`scriptase.providers.hub`; this module only binds the `storyboard` domain
and keeps the historical import surface working.
"""

from scriptase.providers.hub import bind_domain

registry, discover, get_provider, list_providers, init_storyboard_registry = bind_domain('image')

__all__ = ['registry', 'discover', 'get_provider', 'list_providers', 'init_storyboard_registry']
