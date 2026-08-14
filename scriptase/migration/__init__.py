"""V2 → Scriptase migration surface (step 10.1).

The single documented entry for importing V2 projects, artifacts, workflows,
and settings is :mod:`scriptase.migration.v2`. Callers must not invent a second
alias table — domain renames and settings-shape aliases live there.
"""

from scriptase.migration.v2 import (
    DOMAIN_ALIASES,
    OUTPUT_LAYOUT_DIRS,
    SELECTION_ALIASES,
    SETTINGS_SHAPE,
    V2ImportError,
    V2ImportReport,
    import_project_tree,
    import_settings,
    import_v2_root,
    import_workflow,
    migrate_settings_document,
    migrate_workflow_document,
)

__all__ = [
    "DOMAIN_ALIASES",
    "OUTPUT_LAYOUT_DIRS",
    "SELECTION_ALIASES",
    "SETTINGS_SHAPE",
    "V2ImportError",
    "V2ImportReport",
    "import_project_tree",
    "import_settings",
    "import_v2_root",
    "import_workflow",
    "migrate_settings_document",
    "migrate_workflow_document",
]
