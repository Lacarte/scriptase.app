"""App-config read/write, moved verbatim out of V2 ``studio/editor/routes.py``.

Service layer: no Flask import belongs in this module.
"""

import json

from config import APP_CONFIG_PATH
from scriptase.shared.io_utils import safe_json_read, safe_json_write


def _read_app_config():
    """Read the full app-config.json file."""
    try:
        return safe_json_read(APP_CONFIG_PATH)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"version": 2, "defaults": {}, "localStorage": []}


def _write_app_config(cfg):
    """Write the full app-config.json file."""
    safe_json_write(APP_CONFIG_PATH, cfg, indent=2)
