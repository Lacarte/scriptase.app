"""Helpers for turning legacy scene templates into structured style specs."""

from __future__ import annotations

import re
from copy import deepcopy


SECTION_LABELS = {
    "palette": ("color palette",),
    "lighting": ("lighting",),
    "environments": ("environments", "settings"),
    "composition": ("composition",),
    "motifs": ("visual motifs", "props", "flora", "textures", "creatures"),
    "motion": ("animation cues",),
    "references": ("style",),
}

GENERIC_STOPWORDS = {
    "and", "the", "with", "for", "from", "that", "this", "into", "like",
    "style", "image", "prompts", "prompt", "quality", "should", "feel",
    "generate", "include", "using", "through", "against", "modern",
}

DEFAULT_NEGATIVE_RULES = {
    "dark_horror": ["avoid gore", "avoid cheerful daylight"],
    "minimal": ["avoid visual clutter", "avoid crowded environments"],
    "cyberpunk": ["avoid natural daylight", "avoid soft earth tones"],
    "children_storybook": ["avoid horror elements", "avoid harsh realism"],
    "documentary": ["avoid glossy commercial polish", "avoid surreal fantasy imagery"],
    "true_crime": ["avoid cartoon stylization", "avoid heroic glamorization"],
    "dark_psychology": ["avoid cozy warmth", "avoid playful color palettes"],
    "stickman_animation": ["avoid photorealism", "avoid dense backgrounds", "no gradients or textures in background", "no paper grain or vignetting", "no shadows or artifacts on the background", "background must be solid pure white (#FFFFFF) edge to edge", "no extra arms or extra legs", "no duplicated limbs or polylimbs", "exactly two arms and two legs per figure", "no branching or forked limb strokes", "no motion smears or ghost limbs to imply movement", "no extra fingers, no multiple hand stubs"],
    "existential": ["avoid visual clutter", "avoid warm cozy aesthetics", "avoid cartoon stylization"],
    "code_cosmos": ["avoid bright daylight", "avoid cartoon aesthetic", "avoid minimal/clean compositions", "avoid warm colors", "avoid empty backgrounds"],
    "solitary_path": ["avoid crowds", "avoid urban settings", "avoid cheerful colors", "avoid close-ups", "avoid lush vegetation"],
    "crimson_silhouette": ["avoid photorealism", "avoid more than 3 colors", "avoid detail inside silhouettes", "avoid blue or cool tones", "avoid repeating the same composition across scenes"],
    "gothic_moonlit": ["avoid modern architecture", "avoid bright daylight", "avoid photorealism", "avoid flat vector art", "avoid cheerful warm tones"],
    "holographic_entity": ["avoid wireframe mesh", "avoid bright daylight", "avoid warm ambient lighting", "avoid cartoon aesthetic", "avoid multiple figures", "avoid realistic skin or clothing"],
    "neon_sigil": ["avoid photorealism", "avoid warm colors", "avoid multiple symbols", "avoid busy backgrounds", "avoid human figures", "avoid 3D rendering"],
    "glowing_core": ["avoid photorealism", "avoid detailed backgrounds", "avoid multiple figures", "avoid ground planes or floors", "avoid harsh shadows", "avoid facial features"],
    "ethereal_connection": ["avoid opaque solid subjects", "avoid warm colors", "avoid bright backgrounds", "avoid cartoon or flat illustration", "avoid hard edges", "avoid environmental detail"],
    "stickman_glow": ["avoid photorealism", "avoid detailed anatomy", "avoid bright backgrounds", "avoid cheerful mood", "avoid multiple figures", "avoid environmental detail", "no extra arms or extra legs", "no duplicated limbs or polylimbs", "exactly two arms and two legs per figure", "no branching or forked limb strokes", "no motion smears or ghost limbs"],
    "shadow_pursuit": ["avoid photorealism", "avoid bright saturated colors", "avoid static poses", "avoid cheerful mood", "avoid sunny skies", "avoid clean vector lines"],
    "white_gaze": ["avoid dark backgrounds", "avoid photorealistic detail", "avoid saturated colors", "avoid multiple subjects", "avoid warm tones", "avoid busy compositions"],
    "white_room": ["avoid dark lighting", "avoid busy environments", "avoid saturated colors", "avoid cartoon or illustration styles", "avoid multiple people", "avoid dynamic action poses"],
    "ink_fury": ["avoid clean vector lines", "avoid photorealism", "avoid pastel or bright colors", "avoid calm poses", "avoid wide full-body shots", "avoid detailed faces"],
    "transparent_skeleton": ["avoid cartoon or illustration styles", "avoid multiple golden figures", "avoid horror treatment of skeleton", "avoid empty minimal backgrounds", "avoid supernatural glow effects"],
    "body_signal": ["avoid bright backgrounds", "avoid facial features", "avoid warm colors", "avoid dynamic action poses", "avoid cartoon aesthetic", "avoid environmental settings"],
    "neural_glow": ["avoid bright backgrounds", "avoid flat illustration", "avoid human figures", "avoid opaque solid subjects", "avoid warm color temperature", "avoid wireframe rendering"],
    "tension_macro": ["avoid wide shots", "avoid bright lighting", "avoid full face reveals", "avoid cheerful expressions", "avoid busy backgrounds", "avoid photorealism"],
}


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    return [part.strip() for part in parts if part.strip()]


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        value = item.strip(" ,.;:-")
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _clean_phrase(text: str) -> str:
    value = (text or "").strip()
    value = re.sub(r"^generate\s+", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\bimage prompts?\b", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value)
    return value.strip(" ,.;:-")


def _split_list(value: str) -> list[str]:
    if not value:
        return []
    text = value.replace(" - ", ", ")
    text = re.sub(r"\s+or\s+", ", ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+and\s+", ", ", text, flags=re.IGNORECASE)
    return _dedupe([part.strip() for part in re.split(r"[;,]", text) if part.strip()])


def _extract_labeled_value(style_prompt: str, labels: tuple[str, ...]) -> str:
    sentences = _split_sentences(style_prompt)
    for sentence in sentences:
        lowered = sentence.lower()
        for label in labels:
            prefix = f"{label.lower()}:"
            if prefix in lowered:
                _, _, remainder = sentence.partition(":")
                return remainder.strip()
    return ""


def _extract_style_keywords(template: dict) -> list[str]:
    name = template.get("name", "")
    description = template.get("description", "")
    prompt = template.get("style_prompt", "")
    first_sentence = _split_sentences(prompt)[:1]
    raw_parts = [name, description, *first_sentence]
    words = []
    for part in raw_parts:
        for token in re.findall(r"[A-Za-z][A-Za-z0-9'/-]+", part or ""):
            lowered = token.lower()
            if lowered in GENERIC_STOPWORDS or len(lowered) < 4:
                continue
            words.append(token)
    return _dedupe(words)[:8]


def derive_style_spec(template: dict) -> dict:
    """Build a structured style spec from the legacy template text."""
    prompt = template.get("style_prompt", "")
    sentences = _split_sentences(prompt)
    first_sentence = _clean_phrase(sentences[0]) if sentences else template.get("name", "")

    palette = _split_list(_extract_labeled_value(prompt, SECTION_LABELS["palette"]))
    lighting = _split_list(_extract_labeled_value(prompt, SECTION_LABELS["lighting"]))
    environments = _split_list(_extract_labeled_value(prompt, SECTION_LABELS["environments"]))
    composition = _split_list(_extract_labeled_value(prompt, SECTION_LABELS["composition"]))
    motifs = _split_list(_extract_labeled_value(prompt, SECTION_LABELS["motifs"]))
    motion = _split_list(_extract_labeled_value(prompt, SECTION_LABELS["motion"]))
    references = _split_list(_extract_labeled_value(prompt, SECTION_LABELS["references"]))

    if not lighting:
        lighting = [
            _clean_phrase(sentence) for sentence in sentences
            if "light" in sentence.lower()
        ][:4]
    if not composition:
        composition = [
            _clean_phrase(sentence) for sentence in sentences
            if any(word in sentence.lower() for word in ("composition", "shot", "angle", "frame"))
        ][:4]
    if not environments:
        environments = [
            _clean_phrase(sentence) for sentence in sentences
            if any(word in sentence.lower() for word in ("environment", "setting", "scene", "interior", "exterior"))
        ][:4]
    if not motion:
        motion = [
            _clean_phrase(sentence) for sentence in sentences
            if any(word in sentence.lower() for word in ("motion", "rain", "drifting", "flicker", "flow", "curling"))
        ][:4]

    style_keywords = _extract_style_keywords(template)
    negative_rules = list(DEFAULT_NEGATIVE_RULES.get(template.get("id", ""), []))

    return {
        "identity": {
            "render_mode": first_sentence or template.get("description", "") or template.get("name", ""),
            "style_keywords": style_keywords,
            "references": references[:4],
        },
        "hard_constraints": {
            "palette": palette[:5],
            "lighting_baseline": lighting[:5],
            "environments": environments[:5],
        },
        "soft_preferences": {
            "motifs": motifs[:6],
            "composition": composition[:5],
        },
        "motion_profile": {
            "energy": template.get("description", "") or template.get("name", ""),
            "video_motion": motion[:5],
        },
        "negative_rules": negative_rules,
    }


def compile_style_prompt(style_spec: dict, custom_style_notes: str = "") -> str:
    """Compile a readable prose prompt from the structured style spec."""
    identity = style_spec.get("identity", {})
    hard = style_spec.get("hard_constraints", {})
    soft = style_spec.get("soft_preferences", {})
    motion = style_spec.get("motion_profile", {})

    parts = []
    render_mode = identity.get("render_mode")
    if render_mode:
        parts.append(f"Generate scenes in {render_mode}.")

    palette = hard.get("palette") or []
    if palette:
        parts.append(f"Color palette: {', '.join(palette)}.")

    lighting = hard.get("lighting_baseline") or []
    if lighting:
        parts.append(f"Lighting baseline: {', '.join(lighting)}.")

    environments = hard.get("environments") or []
    if environments:
        parts.append(f"Environment cues: {', '.join(environments)}.")

    motifs = soft.get("motifs") or []
    if motifs:
        parts.append(f"Recurring motifs: {', '.join(motifs)}.")

    composition = soft.get("composition") or []
    if composition:
        parts.append(f"Composition tendencies: {', '.join(composition)}.")

    style_keywords = identity.get("style_keywords") or []
    if style_keywords:
        parts.append(f"Style keywords: {', '.join(style_keywords[:6])}.")

    motion_vocab = motion.get("video_motion") or []
    if motion_vocab:
        parts.append(f"Motion vocabulary: {', '.join(motion_vocab)}.")

    negative_rules = style_spec.get("negative_rules") or []
    if negative_rules:
        parts.append(f"Avoid: {', '.join(negative_rules)}.")

    notes = (custom_style_notes or "").strip()
    if notes:
        parts.append(f"Custom style notes: {notes}.")

    return " ".join(parts).strip()


def normalize_template(template: dict) -> dict:
    """Ensure a template carries both a style spec and a legacy style prompt."""
    enriched = deepcopy(template)
    style_spec = deepcopy(enriched.get("style_spec") or derive_style_spec(enriched))
    enriched["style_spec"] = style_spec
    enriched["style_prompt"] = enriched.get("style_prompt") or compile_style_prompt(style_spec)
    return enriched


def enrich_templates(templates: list[dict]) -> list[dict]:
    return [normalize_template(template) for template in templates]


def public_template_payload(template: dict) -> dict:
    """Return the public frontend-safe shape for template pickers."""
    normalized = normalize_template(template)
    return {
        "id": normalized.get("id", ""),
        "name": normalized.get("name", ""),
        "description": normalized.get("description", ""),
        "color": normalized.get("color", ""),
        "style_prompt": normalized.get("style_prompt", ""),
    }


def resolve_template_bundle(style_id: str, templates_by_id: dict, custom_style_notes: str = "") -> dict:
    """Resolve a template ID into backend generation inputs."""
    template = templates_by_id.get(style_id) or templates_by_id.get("cinematic") or {}
    normalized = normalize_template(template)
    style_spec = deepcopy(normalized.get("style_spec", {}))
    notes = (custom_style_notes or "").strip()
    if notes:
        style_spec["custom_style_notes"] = notes
    style_prompt = compile_style_prompt(style_spec, notes)
    return {
        "template": normalized,
        "style_spec": style_spec,
        "style_prompt": style_prompt,
        "custom_style_notes": notes,
    }
