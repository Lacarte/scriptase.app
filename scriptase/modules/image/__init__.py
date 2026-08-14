"""Image generation (V2 ``storyboard``). Provider-capable.

Own capability vocabulary (step 6.1): ``text_to_image``, ``image_edit``,
``reference_image``, ``inpainting``.

Nothing may import business logic from ``routes.py``. ``storyboard_bp`` is this
package's own transport and is the one exception — it is exported, never
imported from.
"""

from .routes import storyboard_bp

__all__ = ["storyboard_bp"]
