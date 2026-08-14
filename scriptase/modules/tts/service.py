"""Reusable TTS step implementation.

V2 kept this in ``studio/pipeline/services.py``, next to the classic pipeline
steps. There is no ``pipeline`` package here — the node engine is the execution
model — so the one step that belongs to this module lives with it, and the TTS
node adapter imports it from here rather than from a route module.
"""


def _step_tts(config, project_id, context=None):
    """Generate TTS audio and return the reconciled metadata dict.

    Step 15.2 replaced the two provider branches this function used to pick
    between with one dispatch through the registry. Voice selection,
    exclusivity, the preview cache, and the `job_meta` block are all
    provider-agnostic now, so a TTS provider nobody has written yet runs here
    without an edit.
    """
    from scriptase.modules.tts import dispatch
    from scriptase.modules.tts.normalize import clean_for_tts

    return dispatch.synthesize(
        {**dict(config or {}), "text": clean_for_tts(config["text"])},
        project_id=project_id,
        context=context,
        use_cache=True,
        # `_step_timing` copies this file out by name and every recorded
        # `tts.json` names it, so the managed layout stays `voice.wav`.
        basename="voice",
    )
