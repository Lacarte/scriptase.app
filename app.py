"""Flask entry point: application factory, blueprint registration, provider init.

Scaffold only. Blueprints land as their packages do:

* step 0.2 — engine and provider platform routes
* step 0.3 — media module blueprints
* step 1.3 — Channel CRUD
* step 2.x — Production view and stage projection

Workflow and provider API routes stay loopback-only; they describe and mutate
the credential store.
"""

from __future__ import annotations

from flask import Flask, jsonify

import config


def create_app() -> Flask:
    config.ensure_runtime_dirs()

    app = Flask(
        __name__,
        static_folder=str(config.STATIC_DIST_DIR),
        static_url_path="/static",
    )

    @app.get("/api/health")
    def health():
        return jsonify(status="ok", version=_version())

    register_blueprints(app)
    return app


def register_blueprints(app: Flask) -> None:
    """Attach feature blueprints. Populated as packages land in Phase 0."""


def _version() -> str:
    from scriptase import __version__

    return __version__


if __name__ == "__main__":
    create_app().run(host=config.HOST, port=config.PORT, debug=config.DEBUG)
