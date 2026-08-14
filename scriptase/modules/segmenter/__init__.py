"""Segmenter — decides only where narration divides.

Turning a segment into a visual scene is Scene Director's job, not this one.

Scenes carry stable ids that survive re-segmentation (step 1.6); ordinal
position is presentation data. Re-running the segmenter must never leave an open
issue or artifact bound to a scene that no longer exists. Identity lives in
``scriptase.scenes``; this package runs the algorithm and stamps ids via
``service.apply_stable_scene_identity``.

Step 0.3 relocates the algorithm out of V2's ``studio/timing/segmenter.py`` into
``segmenter/algorithm.py`` and lifts the in-process step implementation
(``_step_segment``) into ``segmenter/service.py``. ``segmenter_bp`` is this
package's own transport and is exported, never imported from.
"""

from .routes import segmenter_bp
from .service import apply_stable_scene_identity, _step_segment

__all__ = ["segmenter_bp", "apply_stable_scene_identity", "_step_segment"]
