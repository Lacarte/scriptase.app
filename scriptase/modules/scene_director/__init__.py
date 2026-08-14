"""Scene Director (V2 ``build_scene_blueprints``). Provider-capable.

The explicit script/segment-to-visual-scene transformation stage. Produces a
structured ``SceneSpec`` (step 5.1) from the Channel's structured visual
direction (step 5.2).

Step 0.3 moves ``_apply_segmenter_timing``, ``_normalize_webhook_response``, and
``generate_with_chapters_chunked`` out of ``routes.py`` into the service layer.
No prompt text lives outside a provider module.
"""
