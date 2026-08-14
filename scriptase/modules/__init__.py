"""Media modules — one package per production capability.

Ported from V2's ``studio/`` modules with the rename pass (``story``->``script``,
``build_scene_blueprints``->``scene_director``, ``storyboard``->``image``,
``animator``->``video``, ``editor``->``compose``).

Step 0.2 brought across only what the **provider platform** needs to register,
validate, and dispatch: each domain's ``providers/`` package plus the data and
service modules those import at module scope. Step 0.3 ports the rest and
rebuilds the four tangled subsystems (``timing``, ``captions``,
``scene_director``, ``compose``).

Structural rule enforced by test in 0.3: **no module may import business logic
from a ``routes.py``.** Blueprints are transport; services hold the logic. Two
known violations arrived with the 0.2 port and are 0.3's to close:
``video/providers/grok_automa`` reaches into ``video/routes`` for its WebSocket
runtime, and ``scene_director/service`` imports three helpers from its own
``routes``.
"""
