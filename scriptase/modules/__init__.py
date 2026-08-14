"""Media modules — one package per production capability.

Populated in step 0.3 from V2's ``studio/`` modules with the rename pass
(``story``->``script``, ``build_scene_blueprints``->``scene_director``,
``storyboard``->``image``, ``animator``->``video``, ``editor``->``compose``).

Structural rule enforced by test in 0.3: **no module may import business logic
from a ``routes.py``.** Blueprints are transport; services hold the logic.
"""
