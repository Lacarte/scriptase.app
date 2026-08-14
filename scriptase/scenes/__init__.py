"""Stable scene identity and the re-segmentation rule (step 1.6).

Scenes carry ``scn_XXXXXX`` ids that survive re-segmentation. Ordinal position
is presentation data only. Re-running the segmenter rebinds, supersedes, or
creates scenes under the contracts.md §4 rule so no open issue or artifact is
left bound to a scene that no longer resolves.
"""

from scriptase.scenes.migrations import SCHEMA_VERSION, apply_migrations
from scriptase.scenes.models import (
    SCENE_ID_RE,
    SCENE_SCHEMA_VERSION,
    Scene,
    parse_scene,
    validation_problems,
)
from scriptase.scenes.resegment import (
    REBIND_IOU_THRESHOLD,
    REBIND_MAX_SPAN_RATIO,
    ResegmentConfig,
    ResegmentDecision,
    ResegmentResult,
    SegmentCandidate,
    apply_resegmentation,
    candidates_from_segments,
    is_rebind_eligible,
    stamp_segments_with_scene_ids,
    temporal_iou,
)
from scriptase.scenes.store import (
    SceneNotFound,
    SceneSuperseded,
    SceneValidationError,
    active_scenes_for_job,
    create_scene,
    get_scene,
    list_scenes,
    mark_superseded,
    resolve_scene,
    scene_resolves,
    update_scene_span,
)

__all__ = [
    "REBIND_IOU_THRESHOLD",
    "REBIND_MAX_SPAN_RATIO",
    "SCENE_ID_RE",
    "SCENE_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "ResegmentConfig",
    "ResegmentDecision",
    "ResegmentResult",
    "Scene",
    "SceneNotFound",
    "SceneSuperseded",
    "SceneValidationError",
    "SegmentCandidate",
    "active_scenes_for_job",
    "apply_migrations",
    "apply_resegmentation",
    "candidates_from_segments",
    "create_scene",
    "get_scene",
    "is_rebind_eligible",
    "list_scenes",
    "mark_superseded",
    "parse_scene",
    "resolve_scene",
    "scene_resolves",
    "stamp_segments_with_scene_ids",
    "temporal_iou",
    "update_scene_span",
    "validation_problems",
]
