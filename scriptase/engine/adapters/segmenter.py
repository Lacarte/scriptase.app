"""Scene-segmentation adapter (`segmenter.run`).

`_step_segment` stamps an absolute `output_path` onto its result so the legacy
HTTP route could report where it wrote. Step 0.3 strips that key before the
result becomes a port payload (§36 L7): the written file is addressed by the
relative `artifact_refs` entry `with_artifacts` derives from it, and
`output_folder` — a managed folder *name*, not a path — still identifies the run.
"""

from __future__ import annotations

from scriptase.modules.segmenter.algorithm import pacing_config
from scriptase.modules.segmenter.service import _step_segment
from .common import outputs, project_id, with_artifacts

# Absolute path keys that must never reach a port payload, cache entry, or SSE
# frame (contracts.md §30.2 / §36 / §44).
_ABSOLUTE_KEYS = frozenset({"output_path"})

# Segmenter knobs the Channel's scene-pacing preset supplies. A value explicitly
# set on the node wins over the inherited preset (an author who dialed a band on
# the node means it) — the same "explicit config wins" rule inherited_config uses.
_PACING_KEYS = ("target_min", "target_max", "hard_max")


def _with_channel_pacing(config, context):
    """Fill segmenter duration knobs from the Channel's scene-pacing preset.

    Only fills a knob the node did not set itself, and only when the preset is a
    known one, so a workflow that dialed its own band or a `segment_config`
    override is left untouched.
    """
    # Imported lazily so `engine.adapters` keeps no import-time dependency on the
    # `jobs` layer that orchestrates it.
    from scriptase.jobs.channel_settings import resolve_channel_settings

    merged = dict(config or {})
    if merged.get("segment_config"):
        return merged  # An explicit override owns every knob.
    band = pacing_config(resolve_channel_settings(context).get("scene_pacing"))
    for key, value in band.items():
        if key in _PACING_KEYS and merged.get(key) in (None, ""):
            merged[key] = value
    return merged


def run(inputs, config, context):
    pid = project_id(context, inputs)
    result = _step_segment(inputs["alignment"], _with_channel_pacing(config, context), pid)
    output_path = result["output_path"]
    body = {key: value for key, value in result.items() if key not in _ABSOLUTE_KEYS}
    return outputs(segments=with_artifacts(body, output_path))
