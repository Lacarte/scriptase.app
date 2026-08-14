"""Gemini watermark removal — detection + LaMa inpainting.

Architecture:
    1. Detect: locate the Gemini sparkle/diamond watermark in the corner using
       a multi-tier confidence gate (template correlation + brightness diff +
       edge density). The detection is conservative on false positives but
       robust to textured backgrounds.
    2. Mask: build a binary mask covering the watermark pixels. Two strategies:
         (a) alpha-map mask — uses the reference watermark template
         (b) brightness mask — finds bright pixels above local background
       The brightness mask catches sparkles that extend beyond the alpha map.
    3. Inpaint: send the masked region to LaMa (a SOTA inpainting model)
       running in an isolated venv. LaMa preserves textured backgrounds far
       better than OpenCV's TELEA inpaint.
    4. Fallback: if LaMa is unavailable, fall back to OpenCV TELEA on the
       same mask so the project still works without the worker venv.

LaMa runs in `_dev/venvs/lama/` because its dependencies (numpy<2, torch 2.11)
conflict with the rest of the project. See `lama_client.py` and `lama_worker.py`.
"""
from __future__ import annotations

import os
import tempfile

import cv2
import numpy as np
from gemini_watermark_remover import WatermarkRemover, WatermarkSize
from loguru import logger
from PIL import Image

from scriptase.modules.image import lama_client

_remover = WatermarkRemover()

# ── Detection thresholds ──────────────────────────────────────────────────
_TEMPLATE_SCORE_MIN = 0.45
# A lower threshold admits smooth radial corner glows that correlate strongly
# with the alpha template but are not watermarks (the clean-glow regression
# fixture measures about 8.8). Real low-contrast watermark fixtures remain
# comfortably above this gate (about 17 or higher).
_BRIGHTNESS_DIFF_MIN = 10.0
_EDGE_DENSITY_MAX = 0.14

# Tiered overrides — when multiple strong signals agree, accept even if the
# strict gate fails. Tuned from real missed-detection cases on cinematic
# Gemini outputs (sweater knit, neural networks, DNA strands, dark roof).
_TEMPLATE_SCORE_OVERRIDE = 0.42
_BRIGHTNESS_DIFF_OVERRIDE = 28.0
_TEMPLATE_SCORE_WEAK = 0.28
_BRIGHTNESS_DIFF_WEAK = 32.0

# Empirically the real Gemini watermark sits 16-25px from the corner across
# both sizes. Wider ranges produce false positives in busy backgrounds.
_MARGIN_RANGES = {
    WatermarkSize.SMALL: (8, 36),
    WatermarkSize.LARGE: (12, 50),
}

# Mask-building padding around the detected ROI — gives the inpaint enough
# context to blend cleanly with the surrounding image.
_MASK_PADDING = 6


# ──────────────────────────────────────────────────────────────────────────
# Alpha-map helpers
# ──────────────────────────────────────────────────────────────────────────

def _alpha_map_for_size(size):
    if size == WatermarkSize.SMALL:
        return _remover.alpha_map_small
    if size == WatermarkSize.LARGE:
        return _remover.alpha_map_large
    return None


# ──────────────────────────────────────────────────────────────────────────
# Detection
# ──────────────────────────────────────────────────────────────────────────

def _safe_correlation(lhs, rhs):
    lhs_flat = lhs.astype(np.float32).reshape(-1)
    rhs_flat = rhs.astype(np.float32).reshape(-1)
    if np.std(lhs_flat) < 1e-6 or np.std(rhs_flat) < 1e-6:
        return 0.0
    corr = np.corrcoef(lhs_flat, rhs_flat)[0, 1]
    if np.isnan(corr):
        return 0.0
    return float(corr)


def _candidate_metrics(region, alpha_map):
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY).astype(np.float32)
    template = (alpha_map * 255).astype(np.float32)
    high_alpha_mask = alpha_map > 0.30
    low_alpha_mask = alpha_map < 0.10

    brightness_diff = 0.0
    if np.any(high_alpha_mask) and np.any(low_alpha_mask):
        brightness_diff = float(
            np.mean(gray[high_alpha_mask]) - np.mean(gray[low_alpha_mask])
        )

    correlation = _safe_correlation(gray, template)
    return correlation, brightness_diff


def _search_bounds(image_width, image_height, size, alpha_map):
    logo_h, logo_w = alpha_map.shape
    min_margin, max_margin = _MARGIN_RANGES.get(
        size,
        (max(8, logo_w // 5), max(logo_w, logo_w // 2)),
    )

    x_start = max(0, image_width - logo_w - max_margin)
    y_start = max(0, image_height - logo_h - max_margin)
    x_end = min(image_width - logo_w, image_width - logo_w - min_margin)
    y_end = min(image_height - logo_h, image_height - logo_h - min_margin)

    if x_end < x_start or y_end < y_start:
        return None
    return x_start, y_start, x_end, y_end


def _locate_watermark(image, size, alpha_map):
    h, w = image.shape[:2]
    bounds = _search_bounds(w, h, size, alpha_map)
    if bounds is None:
        return None

    x_start, y_start, x_end, y_end = bounds
    logo_h, logo_w = alpha_map.shape
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32)
    template = (alpha_map * 255).astype(np.float32)

    search = gray[y_start:y_end + logo_h, x_start:x_end + logo_w]
    if search.shape[0] < logo_h or search.shape[1] < logo_w:
        return None

    result = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)

    x = x_start + max_loc[0]
    y = y_start + max_loc[1]
    roi = image[y:y + logo_h, x:x + logo_w]
    correlation, brightness_diff = _candidate_metrics(roi, alpha_map)
    edges = cv2.Canny(roi, 50, 150)

    return {
        "size": size,
        "alpha_map": alpha_map,
        "x": x,
        "y": y,
        "width": logo_w,
        "height": logo_h,
        "template_score": float(max_val),
        "correlation": correlation,
        "brightness_diff": brightness_diff,
        "edge_density": float(np.mean(edges > 0)),
    }


def _is_confident_match(candidate):
    """Multi-tier confidence gate.

    Tier 1 — strict: all three signals pass (template, brightness, edges).
    Tier 2 — override: template + brightness both strong, ignore edge density
             (Gemini watermarks often land on textured imagery where edge
             density is naturally high).
    Tier 3 — weak template + extreme brightness: catches the hardest cases
             where busy textures suppress template correlation.
    """
    if candidate is None:
        return False

    ts = candidate["template_score"]
    bd = candidate["brightness_diff"]
    ed = candidate["edge_density"]

    if ts >= _TEMPLATE_SCORE_MIN and bd >= _BRIGHTNESS_DIFF_MIN and ed <= _EDGE_DENSITY_MAX:
        return True
    if ts >= _TEMPLATE_SCORE_OVERRIDE and bd >= _BRIGHTNESS_DIFF_OVERRIDE:
        return True
    if ts >= _TEMPLATE_SCORE_WEAK and bd >= _BRIGHTNESS_DIFF_WEAK and ed <= _EDGE_DENSITY_MAX:
        return True
    return False


def _select_best_candidate(image, height, width):
    """Try both watermark sizes and pick the best confident match.

    Always prefers a confident match at the size that Gemini's own rules
    would pick for this resolution — that's structurally more reliable than
    a confident match at the wrong size (usually a false positive).
    """
    preferred_size = _remover.get_watermark_size(width, height)
    sizes_to_try = [preferred_size]
    if preferred_size == WatermarkSize.SMALL:
        sizes_to_try.append(WatermarkSize.LARGE)
    else:
        sizes_to_try.append(WatermarkSize.SMALL)

    candidates_by_size = {}
    for size in sizes_to_try:
        alpha_map = _alpha_map_for_size(size)
        if alpha_map is None:
            continue
        logo_h, logo_w = alpha_map.shape
        if height < logo_h or width < logo_w:
            continue
        candidate = _locate_watermark(image, size, alpha_map)
        if candidate is not None:
            candidates_by_size[size] = candidate

    # 1) confident match at preferred size wins
    preferred = candidates_by_size.get(preferred_size)
    if preferred is not None and _is_confident_match(preferred):
        return preferred

    # 2) any confident match
    confident = [c for c in candidates_by_size.values() if _is_confident_match(c)]
    if confident:
        return max(
            confident,
            key=lambda c: c["template_score"] * 100.0 + c["brightness_diff"],
        )

    # 3) strongest non-confident — will be rejected upstream, kept for logs
    if candidates_by_size:
        return max(
            candidates_by_size.values(),
            key=lambda c: c["template_score"] * 100.0 + c["brightness_diff"],
        )
    return None


# ──────────────────────────────────────────────────────────────────────────
# Mask building
# ──────────────────────────────────────────────────────────────────────────

def _build_mask(image, candidate):
    """Build a binary mask covering the watermark pixels.

    Combines two strategies:
        (a) alpha-map mask — every pixel where the reference template has
            non-trivial alpha
        (b) brightness mask — every pixel notably brighter than the local
            background (catches sparkles extending beyond the template)

    The union is then dilated and blurred so the inpaint blends cleanly.
    """
    h, w = image.shape[:2]
    x = candidate["x"]
    y = candidate["y"]
    lh = candidate["height"]
    lw = candidate["width"]
    alpha_map = candidate["alpha_map"]

    full_mask = np.zeros((h, w), dtype=np.uint8)

    # (a) Alpha-map mask
    alpha_mask = (alpha_map >= 0.10).astype(np.uint8) * 255
    full_mask[y:y + lh, x:x + lw] = alpha_mask

    # (b) Brightness mask — sample background from the alpha-low border
    roi = image[y:y + lh, x:x + lw]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY).astype(np.float32)
    bg_pixels = gray[alpha_map < 0.05]
    if bg_pixels.size > 0:
        bg_median = float(np.median(bg_pixels))
        bg_std = float(np.std(bg_pixels))
        threshold = bg_median + max(18.0, 2.2 * bg_std)
        bright_local = (gray > threshold).astype(np.uint8) * 255
        # Restrict to where the alpha map suggests the watermark could be
        region_gate = (alpha_map >= 0.02).astype(np.uint8) * 255
        region_gate = cv2.dilate(
            region_gate,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)),
            iterations=2,
        )
        bright_local = cv2.bitwise_and(bright_local, region_gate)
        full_mask[y:y + lh, x:x + lw] = cv2.bitwise_or(
            full_mask[y:y + lh, x:x + lw],
            bright_local,
        )

    # Dilate outward and blur the edges so the inpaint covers the soft halo
    full_mask = cv2.dilate(
        full_mask,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
        iterations=2,
    )
    full_mask = cv2.GaussianBlur(full_mask, (5, 5), 0)
    # Re-binarize after blur so LaMa gets a clean mask
    _, full_mask = cv2.threshold(full_mask, 32, 255, cv2.THRESH_BINARY)
    return full_mask


# ──────────────────────────────────────────────────────────────────────────
# Flat-background detection & color fill
# ──────────────────────────────────────────────────────────────────────────

def _sample_surrounding_ring(image, mask, ring_width=12):
    """Return BGR pixels from a ring just outside the masked area.

    Used to characterize the local background. Pixels inside the mask are
    excluded; we want only what's around the watermark.
    """
    # Dilate the mask to get an "outer" region, then subtract the original
    # to get the ring around it.
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ring_width * 2 + 1, ring_width * 2 + 1))
    outer = cv2.dilate(mask, kernel, iterations=1)
    ring = cv2.subtract(outer, mask)
    if not np.any(ring):
        return None
    return image[ring > 0]


def _is_flat_background(ring_pixels, std_threshold=8.0):
    """True if the ring is essentially a flat color (low per-channel std).

    LaMa hallucinates content on flat backgrounds because there's no texture
    to extrapolate from. Solid colors (cartoons, gradients, studio backdrops)
    are far better served by a simple color fill.
    """
    if ring_pixels is None or len(ring_pixels) < 50:
        return False
    # Per-channel standard deviation, averaged across BGR
    stds = ring_pixels.astype(np.float32).std(axis=0)
    avg_std = float(np.mean(stds))
    return avg_std <= std_threshold


def _color_fill(image, mask, ring_pixels):
    """Replace masked pixels with the median color of the surrounding ring.

    On flat backgrounds (cartoons, studio backdrops, gradients) the watermark
    halo extends beyond what brightness detection catches, so we widen the
    mask aggressively here. The fill matches the noise level of the ring so
    there's no visible boundary on JPEG-compressed images.
    """
    # Widen the mask outward — flat-background watermarks have a larger
    # visible halo than the brightness mask captures.
    expand_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    expanded_mask = cv2.dilate(mask, expand_kernel, iterations=2)

    median_bgr = np.median(ring_pixels, axis=0).astype(np.float32)
    fill = np.full_like(image, median_bgr, dtype=np.float32)

    # Use noise sized to match the surrounding texture variance. On truly
    # flat backgrounds (std ~ 1-3) this stays imperceptible; on slightly
    # noisy backgrounds it grain-matches to hide the seam.
    noise_std = max(0.3, float(np.mean(ring_pixels.std(axis=0))) * 0.5)
    noise = np.random.normal(0.0, noise_std, image.shape).astype(np.float32)
    fill = np.clip(fill + noise, 0, 255).astype(np.uint8)

    out = image.copy()
    mask_bool = expanded_mask > 0
    # Feather the boundary so the patch transitions smoothly into the
    # surrounding color rather than showing a hard rectangle edge.
    soft_mask = cv2.GaussianBlur(expanded_mask.astype(np.float32), (15, 15), 0) / 255.0
    soft_mask = np.clip(soft_mask, 0.0, 1.0)[..., None]  # H,W,1 for broadcast
    blended = (image.astype(np.float32) * (1.0 - soft_mask) + fill.astype(np.float32) * soft_mask).astype(np.uint8)
    return blended


# ──────────────────────────────────────────────────────────────────────────
# Inpainting (LaMa with OpenCV fallback)
# ──────────────────────────────────────────────────────────────────────────

def _inpaint_with_lama(image_path, mask, output_path):
    """Run LaMa via the isolated worker. Returns True on success."""
    if not lama_client.is_available():
        return False

    # LaMa wants a mask file path, not a numpy array, so we write it out.
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        mask_path = tmp.name
    try:
        cv2.imwrite(mask_path, mask)
        return lama_client.inpaint(image_path, mask_path, output_path)
    finally:
        try:
            os.unlink(mask_path)
        except OSError:
            pass


def _inpaint_with_opencv(image, mask):
    """Fallback when LaMa is unavailable. TELEA is fast but artifact-prone."""
    return cv2.inpaint(image, mask, 3, cv2.INPAINT_TELEA)


# ──────────────────────────────────────────────────────────────────────────
# Public entry point
# ──────────────────────────────────────────────────────────────────────────

def remove_watermark(filepath: str) -> bool:
    """Remove the Gemini watermark from *filepath* in-place.

    Returns True when the file was handled successfully (whether or not a
    watermark was actually found and removed). Returns False only on a hard
    read/write error.
    """
    try:
        image = cv2.imread(filepath)
        if image is None:
            logger.warning("Could not read image: {}", filepath)
            return False

        height, width = image.shape[:2]
        candidate = _select_best_candidate(image, height, width)

        if not _is_confident_match(candidate):
            logger.info("No Gemini watermark detected: {}", filepath)
            return True

        mask = _build_mask(image, candidate)
        if not np.any(mask):
            logger.info("Empty watermark mask, skipping: {}", filepath)
            return True

        method = "lama"
        ring = _sample_surrounding_ring(image, mask)
        if _is_flat_background(ring):
            # Flat backgrounds (cartoons, studio backdrops, sky) confuse LaMa.
            # A median-color fill with matching noise is far more reliable.
            cleaned = _color_fill(image, mask, ring)
            ext = filepath.rsplit(".", 1)[-1].lower()
            if ext in ("jpg", "jpeg"):
                rgb = cv2.cvtColor(cleaned, cv2.COLOR_BGR2RGB)
                Image.fromarray(rgb).save(filepath, quality=100, subsampling=0)
            else:
                cv2.imwrite(filepath, cleaned)
            method = "color_fill"
        else:
            # Try LaMa first for textured backgrounds
            used_lama = False
            if lama_client.is_available():
                ok = _inpaint_with_lama(filepath, mask, filepath)
                if ok:
                    used_lama = True
                else:
                    logger.debug("[lama] inpaint failed, falling back to OpenCV TELEA")

            if not used_lama:
                cleaned = _inpaint_with_opencv(image, mask)
                ext = filepath.rsplit(".", 1)[-1].lower()
                if ext in ("jpg", "jpeg"):
                    rgb = cv2.cvtColor(cleaned, cv2.COLOR_BGR2RGB)
                    Image.fromarray(rgb).save(filepath, quality=100, subsampling=0)
                else:
                    cv2.imwrite(filepath, cleaned)
                method = "opencv"

        logger.success(
            "Watermark removed: {} (size={}, score={:.3f}, bdiff={:.2f}, edge={:.3f}, method={})",
            filepath,
            candidate["size"].name.lower(),
            candidate["template_score"],
            candidate["brightness_diff"],
            candidate["edge_density"],
            method,
        )
        return True

    except Exception as exc:
        logger.warning("Watermark removal failed on {}: {}", filepath, exc)
        return False
