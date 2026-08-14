from __future__ import annotations

import os
from datetime import datetime, timezone

from config import CAPTIONS_DIR
from scriptase.modules.captions.presets import CAPTION_PRESETS, _get_default_caption_preset_id
from scriptase.modules.captions.service import _group_words_into_captions
from scriptase.shared.io_utils import safe_json_write
from .common import AdapterError, outputs, project_id, with_artifacts


def generate(inputs, config, context):
    pid = project_id(context, inputs)
    cfg = dict(config or {})
    alignment_payload = inputs["alignment"]
    words = alignment_payload.get("alignment") or alignment_payload.get("word_alignment") or []
    for index, word in enumerate(words):
        if not isinstance(word, dict) or not isinstance(word.get("begin"), (int, float)) or not isinstance(word.get("end"), (int, float)) or word["end"] < word["begin"]:
            raise AdapterError("ALIGNMENT_INVALID", f"Invalid word timing at index {index}")
    source = alignment_payload.get("folder") or alignment_payload.get("source_folder") or pid
    preset_id = cfg.get("preset_id") or _get_default_caption_preset_id()
    if preset_id not in CAPTION_PRESETS:
        raise AdapterError("CAPTION_PRESET_INVALID", f"Unknown caption preset: {preset_id}")
    entries = _group_words_into_captions(words, int(cfg.get("words_per_group", 3))) if cfg.get("enabled", True) else []
    payload = {
        "project_id": pid, "source_folder": source, "preset": preset_id,
        "style": {**CAPTION_PRESETS[preset_id], "preset": preset_id},
        "captions": entries, "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    path = os.path.join(CAPTIONS_DIR, source, "captions.json")
    safe_json_write(path, payload, indent=2)
    return outputs(captions=with_artifacts(payload, path))
