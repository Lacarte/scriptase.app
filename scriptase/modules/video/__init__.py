"""Video generation (V2 ``animator``). Provider-capable.

Own capability vocabulary (step 6.1): ``image_to_video``, ``text_to_video``,
``reference_image``, ``duration_control``.

An image is **not** a mandatory input to every video provider; routing is
capability-based (step 6.2).

Nothing may import business logic from ``routes.py`` or ``animation_routes.py``.
``animator_bp`` and ``animation_bp`` are this package's own transport and are
the one exception — they are exported, never imported from. The extension
WebSocket runtime lives in ``ws_runtime.py`` (step 0.3), which is where
``init_animator_ws`` and every non-transport caller now resolve.
"""

from .routes import animator_bp
from .ws_runtime import init_animator_ws
from .animation_routes import animation_bp

__all__ = ["animator_bp", "init_animator_ws", "animation_bp"]
