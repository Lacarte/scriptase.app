"""Segmenter — decides only where narration divides.

Turning a segment into a visual scene is Scene Director's job, not this one.

Scenes carry stable ids that survive re-segmentation (step 1.6); ordinal
position is presentation data. Re-running the segmenter must never leave an open
issue or artifact bound to a scene that no longer exists.
"""
