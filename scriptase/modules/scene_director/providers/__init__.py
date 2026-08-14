"""Scene Blueprint provider package — compatibility facade over the provider hub.

The registry, discovery, and lookup logic lives in
`scriptase.providers.hub`; this module only binds the `scene_blueprint`
domain so the package has the same shape as the three domains that already ship
providers (contracts.md §19.2, §27).

Domain request/result models live in `contract.py` (contracts.md §32.2);
the shared ABC is `base.SceneBlueprintProvider`.
"""

from scriptase.modules.scene_director.providers.base import SceneBlueprintProvider
from scriptase.modules.scene_director.providers.contract import (
    SCENESPEC_FIELDS,
    PatternShotInput,
    SceneBlueprintRequest,
    SceneBlueprintResultPayload,
    SceneItem,
    SceneSpec,
    VisualDirectionInput,
    coerce_scene_specs,
    stamp_scene_specs_from_segments,
    visual_direction_from_config,
)
from scriptase.providers.hub import bind_domain

registry, discover, get_provider, list_providers, init_scene_blueprint_registry = bind_domain(
    'scene_director'
)

__all__ = [
    'registry',
    'discover',
    'get_provider',
    'list_providers',
    'init_scene_blueprint_registry',
    'SceneBlueprintProvider',
    'SceneBlueprintRequest',
    'SceneBlueprintResultPayload',
    'SceneSpec',
    'SceneItem',
    'PatternShotInput',
    'VisualDirectionInput',
    'visual_direction_from_config',
    'SCENESPEC_FIELDS',
    'coerce_scene_specs',
    'stamp_scene_specs_from_segments',
]
