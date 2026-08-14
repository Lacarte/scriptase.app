"""Compose and export (V2 ``editor``). Local service.

Step 0.3 splits V2's 2,821-line ``editor/routes.py`` into separate blueprints:
app settings, SFX library, project discovery, assemble, archive, fonts/overlays,
and export. ``VideoProcessor`` keeps its clean ``dict in -> .process(path)``
boundary and is not rewritten.

The business logic lives in the service layer — ``project_service``,
``audio_service``, ``service`` (assemble), ``export_service``,
``settings_service`` — none of which imports Flask. Nothing may import business
logic from a ``*_routes.py``; the seven blueprints below are this package's own
transport and are the one exception — they are exported, never imported from.

V2's export adapter emitted an absolute ``"path"`` into a port payload; that is
fixed on the way in.
"""

from .assemble_routes import compose_assemble_bp
from .archive_routes import compose_archive_bp
from .asset_routes import compose_assets_bp
from .export_routes import compose_export_bp
from .project_routes import compose_projects_bp
from .settings_routes import compose_settings_bp
from .sfx_routes import compose_sfx_bp

__all__ = [
    "compose_archive_bp",
    "compose_assemble_bp",
    "compose_assets_bp",
    "compose_export_bp",
    "compose_projects_bp",
    "compose_settings_bp",
    "compose_sfx_bp",
]
