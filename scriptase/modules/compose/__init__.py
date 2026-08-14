"""Compose and export (V2 ``editor``). Local service.

Step 0.3 splits V2's 2,821-line ``editor/routes.py`` into separate blueprints:
app settings, SFX library, project discovery, assemble, archive, fonts/overlays,
and export. ``VideoProcessor`` keeps its clean ``dict in -> .process(path)``
boundary and is not rewritten.

V2's export adapter emitted an absolute ``"path"`` into a port payload; that is
fixed on the way in.
"""
