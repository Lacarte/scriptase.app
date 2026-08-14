"""Scene Director (V2 ``build_scene_blueprints``). Provider-capable.

The explicit script/segment-to-visual-scene transformation stage. Produces a
structured ``SceneSpec`` (step 5.1) from the Channel's structured visual
direction (step 5.2).

Step 0.3 moves ``_apply_segmenter_timing``, ``_normalize_webhook_response``, and
``generate_with_chapters_chunked`` out of ``routes.py`` into the service layer.
No prompt text lives outside a provider module.

``_assign_hook_animations`` came across from V2's ``studio/pipeline/services.py``
into ``hooks.py`` — ``scriptase.modules.pipeline`` does not exist.

Nothing may import business logic from ``routes.py``. ``scenes_bp`` is this
package's own transport and is the one exception — it is exported, never
imported from.
"""

from .routes import scenes_bp

__all__ = ["scenes_bp"]
