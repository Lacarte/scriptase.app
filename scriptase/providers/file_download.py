"""File Download Helper — Phase 3.

Provides normalized file download functionality for provider outputs.
Downloads to the appropriate output directory and handles retries.
"""

import os
import time
from urllib.parse import urlparse

from loguru import logger

from scriptase.providers.http_client import get_http_client


DEFAULT_DOWNLOAD_TIMEOUT = 120
DEFAULT_MAX_RETRIES = 3
DEFAULT_CHUNK_SIZE = 65536


def download_file(
    url: str,
    dest_path: str,
    headers: dict | None = None,
    timeout: int = DEFAULT_DOWNLOAD_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> bool:
    """Download a file from URL to a local path with retries.
    
    Args:
        url: Source URL
        dest_path: Destination file path
        headers: Optional additional headers
        timeout: Download timeout in seconds
        max_retries: Number of retry attempts
        chunk_size: Chunk size for streaming download
        
    Returns:
        True if successful, False otherwise
    """
    client = get_http_client()
    parsed = urlparse(url)
    
    default_headers = {
        "User-Agent": "ScriptToScene-Studio/1.0",
        "Accept": "*/*",
    }
    if parsed.netloc:
        default_headers["Referer"] = f"{parsed.scheme}://{parsed.netloc}/"
    
    if headers:
        default_headers.update(headers)
    
    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
    
    last_error = None
    for attempt in range(max_retries):
        try:
            response = client.get(
                url,
                headers=default_headers,
                timeout=timeout,
                stream=True,
            )
            response.raise_for_status()
            
            with open(dest_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
            
            size_kb = os.path.getsize(dest_path) / 1024
            logger.info("[download] Downloaded {:.0f} KB: {} → {}", 
                       size_kb, url, dest_path)
            return True
            
        except Exception as e:
            last_error = e
            logger.warning("[download] Attempt {}/{} failed for {}: {}",
                          attempt + 1, max_retries, url, e)
            if os.path.exists(dest_path):
                try:
                    os.remove(dest_path)
                except OSError:
                    pass
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
    
    logger.error("[download] Failed to download {} after {} attempts: {}",
                url, max_retries, last_error)
    return False


def download_to_output_dir(
    url: str,
    output_dir: str,
    filename: str | None = None,
    create_subdir: str | None = None,
    headers: dict | None = None,
    **kwargs,
) -> str | None:
    """Download a file to an output directory.
    
    Args:
        url: Source URL
        output_dir: Base output directory
        filename: Optional filename (extracted from URL if not provided)
        create_subdir: Optional subdirectory to create
        headers: Optional additional headers
        **kwargs: Additional arguments passed to download_file
        
    Returns:
        Path to downloaded file, or None if failed
    """
    if filename is None:
        parsed = urlparse(url)
        filename = os.path.basename(parsed.path)
        if not filename or "." not in filename:
            filename = "download"
    
    if create_subdir:
        output_dir = os.path.join(output_dir, create_subdir)
    
    dest_path = os.path.join(output_dir, filename)
    if download_file(url, dest_path, headers=headers, **kwargs):
        return dest_path
    return None
