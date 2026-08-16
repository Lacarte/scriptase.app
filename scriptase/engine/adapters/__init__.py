"""Executable adapters between workflow ports and application services.

Adapters use the uniform ``(inputs, config, context) -> outputs`` contract.
The scheduler may pass either an :class:`AdapterContext` or a mapping as the
context.  Output dictionaries are keyed by the stable registry port IDs.
"""

from .common import PROVIDER_OVERRIDE_KEY, AdapterContext, AdapterError

__all__ = ["PROVIDER_OVERRIDE_KEY", "AdapterContext", "AdapterError"]
