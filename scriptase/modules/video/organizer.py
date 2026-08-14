"""Animator Organizer — Download and organize generated assets into project folders.

Directory structure (grabber mode):
  output/animator/{project_id}/
    {scene_num}/
      0.png
      1.png
      ...
    metadata.json
"""

import base64
import json
import os
import re
import time
from urllib.parse import urlparse

import requests as http_requests
from loguru import logger

from scriptase.shared.io_utils import safe_json_write

# CDN servers often block bare requests — mimic a real browser
_DL_HEADERS_BASE = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _dl_headers(url):
    """Build download headers with a Referer derived from the URL's origin."""
    parsed = urlparse(url)
    referer = f"{parsed.scheme}://{parsed.netloc}/"
    return {**_DL_HEADERS_BASE, "Referer": referer}

MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds


def _unique_filepath(directory, basename, ext):
    """Return a filepath that doesn't collide with existing files.

    If ``directory/basename+ext`` already exists, appends _1, _2, … until a
    free name is found.  Returns (filepath, filename).
    """
    filename = f"{basename}{ext}"
    filepath = os.path.join(directory, filename)
    if not os.path.exists(filepath):
        return filepath, filename
    n = 1
    while True:
        filename = f"{basename}_{n}{ext}"
        filepath = os.path.join(directory, filename)
        if not os.path.exists(filepath):
            return filepath, filename
        n += 1


def organize_grabber_assets(project_id, scene_num, urls, assets_dir):
    """Download all image/video URLs for a scene into its subfolder.

    Returns list of local URL paths (e.g. ['/output/animator/proj/1/0.png']).
    """
    scene_dir = os.path.join(assets_dir, project_id, str(scene_num))
    os.makedirs(scene_dir, exist_ok=True)

    local_files = []
    for i, url in enumerate(urls):
        filepath = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = http_requests.get(
                    url, headers=_dl_headers(url), timeout=120, stream=True,
                )
                resp.raise_for_status()

                ext = _detect_ext(url, resp.headers.get("Content-Type", ""))
                # Use UUID from URL as filename if available (e.g. generated/{uuid}/...)
                uuid_match = re.search(r"generated/([a-f0-9-]+)/", url)
                basename = uuid_match.group(1) if uuid_match else str(i)
                filepath, filename = _unique_filepath(scene_dir, basename, ext)

                with open(filepath, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=65536):
                        f.write(chunk)

                local_url = f"/output/animator/{project_id}/{scene_num}/{filename}"
                local_files.append(local_url)
                size_kb = os.path.getsize(filepath) / 1024
                logger.info(
                    "Scene {}/{} downloaded ({:.0f} KB): {}",
                    scene_num, filename, size_kb, _truncate(url, 80),
                )
                break  # success
            except Exception as e:
                logger.warning(
                    "Download attempt {}/{} failed for scene {}, file {}: {}",
                    attempt, MAX_RETRIES, scene_num, i, e,
                )
                if filepath and os.path.isfile(filepath):
                    os.remove(filepath)  # clean up partial file
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY * attempt)
                else:
                    logger.error("Gave up downloading scene {}, file {}: {}", scene_num, i, _truncate(url, 60))

    # Update metadata
    _update_project_metadata(assets_dir, project_id, scene_num, urls, local_files)

    return local_files


def save_base64_assets(project_id, scene_num, images, assets_dir):
    """Save base64-encoded image data for a scene.

    Args:
        images: list of dicts with 'data' (base64 string) and optional 'ext' (e.g. '.png').
                The 'data' may include a data URI prefix like 'data:image/png;base64,...'

    Returns list of local URL paths.
    """
    scene_dir = os.path.join(assets_dir, project_id, str(scene_num))
    os.makedirs(scene_dir, exist_ok=True)

    local_files = []
    source_urls = []

    for i, img in enumerate(images):
        raw = img.get("data", "")
        if not raw:
            continue

        # Strip data URI prefix if present
        ext = img.get("ext", ".png")
        if raw.startswith("data:"):
            # data:image/png;base64,iVBOR...
            header, raw = raw.split(",", 1)
            mime = header.split(":")[1].split(";")[0] if ":" in header else ""
            ext = _ext_from_mime(mime) or ext

        try:
            data = base64.b64decode(raw)
        except Exception as e:
            logger.error("Invalid base64 for scene {}, image {}: {}", scene_num, i, e)
            continue

        # Use UUID-based filename from client if provided, else sequential index
        basename = img.get("filename") or str(i)
        filepath, filename = _unique_filepath(scene_dir, basename, ext)
        with open(filepath, "wb") as f:
            f.write(data)

        local_url = f"/output/animator/{project_id}/{scene_num}/{filename}"
        local_files.append(local_url)
        source_urls.append(img.get("source_url", f"base64:{i}"))
        size_kb = len(data) / 1024
        logger.info("Scene {}/{} saved ({:.0f} KB)", scene_num, filename, size_kb)

    _update_project_metadata(assets_dir, project_id, scene_num, source_urls, local_files)
    return local_files


def _ext_from_mime(mime):
    """Convert MIME type to file extension."""
    m = {
        "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp",
        "image/gif": ".gif", "video/mp4": ".mp4",
    }
    return m.get(mime, "")


def _detect_ext(url, content_type):
    """Detect file extension from URL path or Content-Type header."""
    # Try URL path first (strip query params)
    path = urlparse(url).path.lower()
    for ext in (".png", ".jpg", ".jpeg", ".webp", ".mp4", ".gif"):
        if ext in path:
            return ext if ext != ".jpeg" else ".jpg"

    # Fall back to content-type
    ct = content_type.lower()
    if "mp4" in ct or "video" in ct:
        return ".mp4"
    if "jpeg" in ct or "jpg" in ct:
        return ".jpg"
    if "webp" in ct:
        return ".webp"
    if "gif" in ct:
        return ".gif"
    return ".png"


def _truncate(s, n):
    return s if len(s) <= n else s[:n] + "..."


def reconcile_project(assets_dir, project_id):
    """Scan disk folders and update metadata.json + grabber_job.json to match.

    Finds scene folders with files that aren't tracked in JSON and adds them.
    Returns the number of scenes that were added/updated.
    """
    project_dir = os.path.join(assets_dir, project_id)
    if not os.path.isdir(project_dir):
        return 0

    # --- Load existing JSON files ---
    meta_path = os.path.join(project_dir, "metadata.json")
    job_path = os.path.join(project_dir, "grabber_job.json")

    meta = {}
    if os.path.isfile(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except (json.JSONDecodeError, OSError):
            meta = {}
    if "scenes" not in meta:
        meta["scenes"] = {}

    job = {}
    if os.path.isfile(job_path):
        try:
            with open(job_path, "r", encoding="utf-8") as f:
                job = json.load(f)
        except (json.JSONDecodeError, OSError):
            job = {}
    if "scene_statuses" not in job:
        job["scene_statuses"] = {}

    # --- Scan disk for scene folders ---
    updated = 0
    for entry in os.scandir(project_dir):
        if not entry.is_dir():
            continue
        try:
            int(entry.name)  # only numeric subdirs
        except ValueError:
            continue

        scene_key = entry.name
        files_on_disk = []
        for fname in sorted(os.listdir(entry.path)):
            fpath = os.path.join(entry.path, fname)
            if os.path.isfile(fpath) and fname.lower().endswith(
                (".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm", ".mov")
            ):
                files_on_disk.append(f"/output/animator/{project_id}/{scene_key}/{fname}")

        if not files_on_disk:
            continue

        scene_changed = False

        # --- Update metadata.json if scene missing or file list changed ---
        existing_meta = meta["scenes"].get(scene_key, {})
        existing_files = set(existing_meta.get("local_files", []))
        if set(files_on_disk) != existing_files:
            meta["scenes"][scene_key] = {
                "scene": scene_key,
                "source_urls": existing_meta.get("source_urls", []),
                "local_files": files_on_disk,
                "file_count": len(files_on_disk),
            }
            scene_changed = True

        # --- Update grabber_job.json if scene missing or status stale ---
        existing_status = job["scene_statuses"].get(scene_key, {})
        if existing_status.get("status") != "ready" or set(existing_status.get("local_files", [])) != set(files_on_disk):
            job["scene_statuses"][scene_key] = {
                "status": "ready",
                "urls": existing_status.get("urls", existing_meta.get("source_urls", [])),
                "local_files": files_on_disk,
            }
            scene_changed = True

        if scene_changed:
            updated += 1

    # --- Write back only if something changed ---
    if updated > 0:
        safe_json_write(meta_path, meta, indent=2)

        # Fix overall job status
        if job.get("scene_statuses"):
            all_ready = all(
                s.get("status") in ("ready", "error")
                for s in job["scene_statuses"].values()
            )
            if all_ready:
                job["status"] = "done"
            safe_json_write(job_path, job, indent=2)

        logger.info("Reconciled project {}: {} scenes updated", project_id, updated)

    return updated


def _update_project_metadata(assets_dir, project_id, scene_num, source_urls, local_files):
    """Update the project metadata.json with scene download info."""
    project_dir = os.path.join(assets_dir, project_id)
    meta_path = os.path.join(project_dir, "metadata.json")

    meta = {}
    if os.path.isfile(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except (json.JSONDecodeError, OSError):
            meta = {}

    if "scenes" not in meta:
        meta["scenes"] = {}

    meta["scenes"][str(scene_num)] = {
        "scene": scene_num,
        "source_urls": source_urls,
        "local_files": local_files,
        "file_count": len(local_files),
    }

    safe_json_write(meta_path, meta, indent=2)
