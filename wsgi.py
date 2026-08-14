"""WSGI entrypoint — starts trigger services under gunicorn / waitress / etc.

Step 9.2: V2 only started schedule and watch-folder services under
``if __name__ == "__main__"``, so production WSGI hosts never ran triggers.
This module is the host-facing application object; ``create_app`` starts the
trigger services when not disabled by environment.
"""

from __future__ import annotations

from app import create_app

application = create_app(start_triggers=True)
