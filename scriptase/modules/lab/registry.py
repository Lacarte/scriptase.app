"""Lab registry — the framework that lets many labs share one variant + experiment engine.

A *lab* is a self-describing unit of prompt/config tuning. Each one declares
what it is (name, purpose, how-to, what it measures), which knobs a variant may
override (its `variant_fields`), the real defaults those knobs have in code (its
`default_variant`, shown pre-filled), and two callables — `build_prompt` and
`run_experiment` — that the shared engine drives.

Adding a lab means writing one `LabDescriptor` and registering it; the store,
routes, and UI shell are shared. Variants and runs are scoped by `lab_id`, so
labs never collide.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping


@dataclass(frozen=True)
class VariantField:
    """One tunable knob a variant may set, and how the UI should render it."""

    key: str
    label: str
    # text | textarea | list | number | select
    type: str = "text"
    help: str = ""
    options: tuple[str, ...] = ()
    default: Any = None
    min: float | None = None
    max: float | None = None
    step: float | None = None

    def to_dict(self) -> dict:
        d = {
            "key": self.key, "label": self.label, "type": self.type,
            "help": self.help, "default": self.default,
        }
        if self.options:
            d["options"] = list(self.options)
        for k in ("min", "max", "step"):
            v = getattr(self, k)
            if v is not None:
                d[k] = v
        return d


@dataclass(frozen=True)
class LabDescriptor:
    """A self-describing lab. The metadata is what the UI header renders."""

    id: str
    name: str
    description: str
    purpose: str            # "what it is for"
    how_to: str             # "how to use it"
    measures: str           # "what it measures"
    domain: str             # the pipeline domain it tunes (script, image, …)
    variant_fields: tuple[VariantField, ...]
    default_variant: Mapping[str, Any]
    # The engine hooks. `build_prompt(channel_id, variant, overrides) -> dict`
    # and `run_experiment(channel_id, variant, provider_id, overrides) -> dict`.
    build_prompt: Callable[..., dict]
    run_experiment: Callable[..., dict]
    # Provider domain whose ids populate the lab's provider picker; "" = none.
    provider_domain: str = ""

    def meta(self) -> dict:
        """Presentation-safe descriptor (no callables)."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "purpose": self.purpose,
            "how_to": self.how_to,
            "measures": self.measures,
            "domain": self.domain,
            "provider_domain": self.provider_domain,
            "variant_fields": [f.to_dict() for f in self.variant_fields],
            "default_variant": dict(self.default_variant),
        }


_REGISTRY: dict[str, LabDescriptor] = {}


def register(descriptor: LabDescriptor) -> None:
    if descriptor.id in _REGISTRY:
        raise RuntimeError(f"Duplicate lab id {descriptor.id!r}")
    _REGISTRY[descriptor.id] = descriptor


def get_lab(lab_id: str) -> LabDescriptor | None:
    _ensure_loaded()
    return _REGISTRY.get(lab_id)


def list_labs() -> list[LabDescriptor]:
    _ensure_loaded()
    return list(_REGISTRY.values())


_loaded = False


def _ensure_loaded() -> None:
    """Import the shipped lab definitions once, on first access."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    # Importing the module registers its descriptor as a side effect.
    from scriptase.modules.lab import labs_script  # noqa: F401


__all__ = ["LabDescriptor", "VariantField", "get_lab", "list_labs", "register"]
