"""Script generation (V2 ``story``). Provider-capable.

Modes per §6: Automatic, Topic->Script, Idea->Script, Paste Script, and
Manual/Edit. Paste and Manual require no provider at all.

Nothing may import business logic from ``routes.py``. ``story_bp`` is this
package's own transport and is the one exception — it is exported, never
imported from.
"""

from .routes import story_bp

__all__ = ["story_bp"]
