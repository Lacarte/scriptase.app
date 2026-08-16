"""Viral provider package — compatibility facade over the provider hub.

The registry, discovery, and lookup logic lives in ``scriptase.providers.hub``;
this module only binds the ``viral`` domain (step 16.2).

Domain request/result models live in ``contract.py``; the shared ABC is
``base.ViralProvider``. Providers live in subfolders of this package. The
scoring arithmetic itself lives one level up in ``scriptase.modules.viral`` and
is imported by the ``deterministic`` provider — no other provider has to.
"""

from scriptase.modules.viral.providers.base import ViralProvider
from scriptase.modules.viral.providers.contract import (
    ViralRequest,
    ViralResultPayload,
)
from scriptase.providers.hub import bind_domain

registry, discover, get_provider, list_providers, init_viral_registry = bind_domain(
    "viral"
)

__all__ = [
    "registry",
    "discover",
    "get_provider",
    "list_providers",
    "init_viral_registry",
    "ViralProvider",
    "ViralRequest",
    "ViralResultPayload",
]
