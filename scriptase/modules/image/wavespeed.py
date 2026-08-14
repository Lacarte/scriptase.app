"""Direct WaveSpeed API client for image generation.

Used when the style requires a non-default model (e.g. GPT Image, Reve)
instead of the n8n webhook which hardcodes Flux Dev LoRA.
"""

import json
import os
import time
from pathlib import Path

import requests
from loguru import logger

from config import WAVESPEED_API_KEY

_WAVESPEED_BASE = "https://api.wavespeed.ai/api/v3"

# Aspect ratio → size mapping for models that need explicit dimensions
_ASPECT_TO_SIZE = {
    "9:16": "576*1024",
    "16:9": "1024*576",
    "1:1": "1024*1024",
    "4:3": "1024*768",
    "3:4": "768*1024",
}

# Models that use aspect_ratio parameter instead of size
_ASPECT_RATIO_MODELS = {
    "openai/gpt-image-1.5/text-to-image",
    "openai/gpt-image-1-mini/text-to-image",
    "openai/gpt-image-1/text-to-image",
    "reve/text-to-image",
    "minimax/image-01/text-to-image",
    "ideogram-ai/ideogram-v3-turbo",
}

# Models that use width/height instead of size
_WH_MODELS = {
    "leonardoai/lucid-origin",
}

_ASPECT_TO_WH = {
    "9:16": (576, 1024),
    "16:9": (1024, 576),
    "1:1": (1024, 1024),
}


def _load_image_models():
    """Load image-models.json config."""
    config_path = Path(__file__).resolve().parent.parent.parent / "resources" / "image-models.json"
    if config_path.is_file():
        return json.loads(config_path.read_text(encoding="utf-8"))
    return {}


def get_models_for_style(style: str) -> list:
    """Get the priority-ordered model list for a style. Falls back to default."""
    config = _load_image_models()
    style_cfg = config.get(style, config.get("default", {}))
    return style_cfg.get("models", [])


def is_default_model(style: str) -> bool:
    """Check if a style uses the default n8n/Flux pipeline (no direct API needed)."""
    config = _load_image_models()
    return style not in config or style == "default"


def _build_payload(model_id: str, prompt: str, aspect_ratio: str, model_config: dict) -> dict:
    """Build the API payload for a given model."""
    payload = {"prompt": prompt}

    if model_id in _ASPECT_RATIO_MODELS:
        payload["aspect_ratio"] = aspect_ratio
    elif model_id in _WH_MODELS:
        w, h = _ASPECT_TO_WH.get(aspect_ratio, (576, 1024))
        payload["width"] = w
        payload["height"] = h
        payload["num_images"] = 1
    else:
        payload["size"] = _ASPECT_TO_SIZE.get(aspect_ratio, "576*1024")
        payload["num_images"] = 1
        payload["output_format"] = "jpeg"

    # Merge model-specific config (loras, guidance_scale, etc.)
    for k, v in model_config.items():
        payload[k] = v

    return payload


def generate_image(
    prompt: str,
    style: str,
    aspect_ratio: str = "9:16",
    timeout: int = 300,
    model_override: str = None,
) -> str:
    """Generate a single image using the best model for the style.

    Returns the image URL on success.
    Raises RuntimeError on failure after trying all models.
    """
    api_key = WAVESPEED_API_KEY
    if not api_key:
        raise RuntimeError("WAVESPEED_API_KEY not set")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    if model_override:
        models = [{"id": model_override, "config": {}}]
    else:
        models = get_models_for_style(style)

    if not models:
        raise RuntimeError(f"No image models configured for style '{style}'")

    last_error = None
    for model in models:
        model_id = model["id"]
        model_config = model.get("config", {})
        url = f"{_WAVESPEED_BASE}/{model_id}"
        payload = _build_payload(model_id, prompt, aspect_ratio, model_config)

        try:
            logger.info("WaveSpeed direct: {} (style={})", model_id, style)
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
            resp.raise_for_status()
            pred_id = resp.json().get("data", {}).get("id")
            if not pred_id:
                logger.warning("No prediction ID from {}: {}", model_id, resp.text[:200])
                continue

            # Poll for result
            deadline = time.time() + timeout
            while time.time() < deadline:
                time.sleep(5)
                r = requests.get(
                    f"{_WAVESPEED_BASE}/predictions/{pred_id}/result",
                    headers=headers, timeout=15,
                )
                data = r.json().get("data", {})
                status = data.get("status", "")

                if status == "completed":
                    outputs = data.get("outputs", [])
                    if outputs:
                        logger.info("WaveSpeed image ready: {} via {}", outputs[0][:60], model_id)
                        return outputs[0]
                    break
                elif status in ("failed", "error"):
                    logger.warning("WaveSpeed {} failed: {}", model_id, str(data)[:200])
                    break

            logger.warning("WaveSpeed {} timed out after {}s", model_id, timeout)

        except Exception as e:
            last_error = e
            logger.warning("WaveSpeed {} error: {}", model_id, e)
            continue

    raise RuntimeError(f"All models failed for style '{style}': {last_error}")
