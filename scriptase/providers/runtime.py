"""Runtime Base Class — Phase 3.

Base class for extension providers that need to register WebSocket routes.
Extension providers (kind='extension') can register their own WS routes
and own their client pool, handshake, queueing, and reconnect logic.

Usage:
    class MyExtensionRuntime(Runtime):
        def register_routes(self, app, sock):
            # Register WebSocket routes and handlers
            @sock.route('/ws/my-extension')
            def my_handler(ws):
                ...
    
    # In provider's runtime.py:
    def register_runtime(app, sock):
        MyExtensionRuntime().register(app, sock)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from loguru import logger

from scriptase.providers.validation import sanitize_message


class Runtime(ABC):
    """Base class for extension provider runtimes.
    
    Extension providers can override register_routes() to add
    WebSocket routes and initialize their runtime.
    """
    
    @abstractmethod
    def register_routes(self, app, sock) -> None:
        """Register WebSocket routes and initialize runtime.
        
        Called once at app boot if the provider has kind='extension'.
        
        Args:
            app: Flask application instance
            sock: Flask-Sock instance
        """
        pass
    
    def shutdown(self) -> None:
        """Clean up runtime resources. Called on app shutdown."""
        pass


@dataclass(frozen=True)
class RuntimeBinding:
    """Outcome of one `register_runtime()` attempt.

    Reported back as provider metadata so a failed WebSocket bind is visible in the
    catalog instead of being buried in the boot log (step 11.2).
    """

    bound: bool
    error: str | None = None


def call_provider_runtime(provider_id: str, provider_module: Any, app, sock) -> RuntimeBinding:
    """Call register_runtime() on a provider module if it exists.

    Failure is isolated: it is logged, returned as metadata, and never raised, so
    one broken extension cannot stop application startup (contracts.md §21.4).

    Args:
        provider_id: Provider identifier
        provider_module: Loaded provider module
        app: Flask application
        sock: Flask-Sock instance
    """
    hook = getattr(provider_module, 'register_runtime', None)
    if not callable(hook):
        logger.debug("[runtime] Provider '{}' has no register_runtime hook", provider_id)
        return RuntimeBinding(bound=False)
    try:
        hook(app, sock)
    except Exception as e:
        logger.error("[runtime] Failed to initialize runtime for '{}': {}", provider_id, e)
        return RuntimeBinding(bound=False, error=sanitize_message(f"register_runtime() failed: {e}"))
    logger.info("[runtime] Initialized runtime for provider '{}'", provider_id)
    return RuntimeBinding(bound=True)
