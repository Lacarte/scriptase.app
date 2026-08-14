"""Scene-segmentation adapter (`segmenter.run`).

`_step_segment` stamps an absolute `output_path` onto its result so the legacy
HTTP route could report where it wrote. Step 0.3 strips that key before the
result becomes a port payload (§36 L7): the written file is addressed by the
relative `artifact_refs` entry `with_artifacts` derives from it, and
`output_folder` — a managed folder *name*, not a path — still identifies the run.
"""

from __future__ import annotations

from scriptase.modules.segmenter.service import _step_segment
from .common import outputs, project_id, with_artifacts

# Absolute path keys that must never reach a port payload, cache entry, or SSE
# frame (contracts.md §30.2 / §36 / §44).
_ABSOLUTE_KEYS = frozenset({"output_path"})


def run(inputs, config, context):
    pid = project_id(context, inputs)
    result = _step_segment(inputs["alignment"], dict(config or {}), pid)
    output_path = result["output_path"]
    body = {key: value for key, value in result.items() if key not in _ABSOLUTE_KEYS}
    return outputs(segments=with_artifacts(body, output_path))
