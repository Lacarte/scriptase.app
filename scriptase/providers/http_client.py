"""HTTP Client with Retry and Backoff — Phase 3.

Provides a wrapped requests Session with automatic retry logic,
exponential backoff, and timeout handling.
"""

import time
import requests
from loguru import logger
from typing import Any


DEFAULT_TIMEOUT = 30
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_FACTOR = 0.5


class HttpClient:
    """HTTP client with automatic retry and exponential backoff."""
    
    def __init__(
        self,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "ScriptToScene-Studio/1.0",
        })
    
    def request(
        self,
        method: str,
        url: str,
        **kwargs,
    ) -> requests.Response:
        """Make an HTTP request with retry logic.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            url: Request URL
            **kwargs: Additional arguments passed to requests
            
        Returns:
            requests.Response object
            
        Raises:
            requests.HTTPError: After exhausting retries
        """
        timeout = kwargs.pop("timeout", self.timeout)
        retries = kwargs.pop("retries", self.max_retries)
        
        last_exception = None
        for attempt in range(retries + 1):
            try:
                response = self.session.request(
                    method,
                    url,
                    timeout=timeout,
                    **kwargs,
                )
                if response.status_code < 500:
                    return response
                if attempt < retries:
                    wait = self.backoff_factor * (2 ** attempt)
                    logger.warning(
                        "[http] {} {} → {} (attempt {}/{}), retrying in {:.1f}s",
                        method, url, response.status_code, attempt + 1, retries + 1, wait
                    )
                    time.sleep(wait)
                else:
                    response.raise_for_status()
            except requests.RequestException as e:
                last_exception = e
                if attempt < retries:
                    wait = self.backoff_factor * (2 ** attempt)
                    logger.warning(
                        "[http] {} {} → {} (attempt {}/{}), retrying in {:.1f}s",
                        method, url, type(e).__name__, attempt + 1, retries + 1, wait
                    )
                    time.sleep(wait)
                else:
                    raise
        
        if last_exception:
            raise last_exception
        raise requests.RequestException(f"Failed after {retries + 1} attempts")
    
    def get(self, url: str, **kwargs) -> requests.Response:
        return self.request("GET", url, **kwargs)
    
    def post(self, url: str, **kwargs) -> requests.Response:
        return self.request("POST", url, **kwargs)
    
    def put(self, url: str, **kwargs) -> requests.Response:
        return self.request("PUT", url, **kwargs)
    
    def delete(self, url: str, **kwargs) -> requests.Response:
        return self.request("DELETE", url, **kwargs)
    
    def patch(self, url: str, **kwargs) -> requests.Response:
        return self.request("PATCH", url, **kwargs)
    
    def close(self) -> None:
        self.session.close()


_default_client: HttpClient | None = None


def get_http_client() -> HttpClient:
    """Get the default shared HTTP client."""
    global _default_client
    if _default_client is None:
        _default_client = HttpClient()
    return _default_client


def close_http_client() -> None:
    """Close the default shared HTTP client."""
    global _default_client
    if _default_client is not None:
        _default_client.close()
        _default_client = None
