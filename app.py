"""Flask entry point: application factory, blueprint registration, provider init.

Blueprints land as their packages do:

* step 0.2 — engine and provider platform routes  ← here
* step 0.3 — media module blueprints
* step 1.3 — Channel CRUD
* step 2.x — Production view and stage projection

Workflow and provider API routes stay loopback-only; they describe and mutate
the credential store. That check lives inside the blueprints themselves rather
than here, so a route cannot be added that quietly skips it.
"""

from __future__ import annotations

import os

from flask import Flask, jsonify

import config


def create_app(*, discover_providers: bool = True) -> Flask:
    config.ensure_runtime_dirs()

    app = Flask(
        __name__,
        static_folder=str(config.STATIC_DIST_DIR),
        static_url_path="/static",
    )
    app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB max request body

    _configure_cors(app)
    sock = _configure_sock(app)

    @app.get("/api/health")
    def health():
        return jsonify(status="ok", version=_version())

    register_blueprints(app)
    if discover_providers:
        init_provider_platform(app, sock)
    return app


def register_blueprints(app: Flask) -> None:
    """Attach feature blueprints. Populated as packages land in Phase 0.

    Transport only. Every blueprint here is a thin shell over a service module,
    which is why step 0.3 could split V2's 2,821-line editor blueprint into the
    seven `compose_*` ones below without moving a single behaviour: the logic
    they used to hold now lives in `scriptase/modules/compose/*_service.py`.
    """
    from scriptase.channels import channels_bp
    from scriptase.engine.routes import workflows_bp
    from scriptase.jobs.routes import jobs_bp
    from scriptase.modules.captions import captions_bp
    from scriptase.modules.compose import (
        compose_archive_bp,
        compose_assemble_bp,
        compose_assets_bp,
        compose_export_bp,
        compose_projects_bp,
        compose_settings_bp,
        compose_sfx_bp,
    )
    from scriptase.modules.image import storyboard_bp
    from scriptase.modules.music import music_bp
    from scriptase.modules.scene_director import scenes_bp
    from scriptase.modules.script import story_bp
    from scriptase.modules.segmenter import segmenter_bp
    from scriptase.modules.timing import timing_bp
    from scriptase.modules.thumbnails import thumbnails_bp
    from scriptase.modules.tts import tts_bp
    from scriptase.modules.video import animation_bp, animator_bp
    from scriptase.providers.routes import providers_bp

    app.register_blueprint(workflows_bp)
    app.register_blueprint(providers_bp)
    app.register_blueprint(channels_bp)
    app.register_blueprint(jobs_bp)

    for blueprint in (
        story_bp,
        tts_bp,
        timing_bp,
        thumbnails_bp,
        segmenter_bp,
        scenes_bp,
        storyboard_bp,
        animator_bp,
        animation_bp,
        captions_bp,
        music_bp,
        compose_settings_bp,
        compose_sfx_bp,
        compose_projects_bp,
        compose_assemble_bp,
        compose_archive_bp,
        compose_assets_bp,
        compose_export_bp,
    ):
        app.register_blueprint(blueprint)

    _register_spa_fallback(app)


def init_provider_platform(app: Flask, sock) -> None:
    """Discover every provider domain and bind extension runtimes."""
    from loguru import logger

    from scriptase.providers.hub import hub, init_providers

    init_providers(app=app, sock=sock)
    logger.info(
        "[providers] {} domains: {}",
        len(hub.domains()),
        {domain: len(hub.registry(domain)) for domain in hub.domains()},
    )


def _configure_cors(app: Flask) -> None:
    """Allow the Vite dev-server origins only. Production is same-origin."""
    from flask_cors import CORS

    raw = os.environ.get(
        "SCRIPTASE_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    )
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    CORS(app, origins=origins or None)


def _register_spa_fallback(app: Flask) -> None:
    """Serve the Vite production build's index.html for client-side routes.

    API and engine-managed paths stay first-match; only bare UI routes fall
    through here. Absent dist (dev / fresh clone) the handler 404s cleanly.
    """
    from flask import send_from_directory

    dist = config.STATIC_DIST_DIR
    index = dist / "index.html"

    @app.get("/")
    def spa_root():
        if index.is_file():
            return send_from_directory(dist, "index.html")
        return (
            "<!doctype html><title>Scriptase</title>"
            "<p>Frontend not built. Run <code>cd frontend && npm run build</code> "
            "or start the Vite dev server on :5173.</p>"
        ), 200

    @app.get("/workflow")
    @app.get("/workflow/<path:_rest>")
    @app.get("/channels")
    @app.get("/channels/<path:_rest>")
    def spa_client_routes(_rest=None):
        if index.is_file():
            return send_from_directory(dist, "index.html")
        return spa_root()


def _configure_sock(app: Flask):
    """The WebSocket surface extension providers register their runtime on."""
    from flask_sock import Sock

    return Sock(app)


def _version() -> str:
    from scriptase import __version__

    return __version__


if __name__ == "__main__":
    from scriptase.engine.scheduled_runs import schedule_service
    from scriptase.engine.watch_folders import watch_folder_service

    application = create_app()
    # Trigger services start here in the dev server. Step 9.2 moves them behind
    # an app-factory hook so they also run under a WSGI host — starting them
    # under `__main__` only is the V2 defect that step records.
    schedule_service.start()
    watch_folder_service.start()
    application.run(
        host=config.HOST, port=config.PORT, debug=config.DEBUG, threaded=True
    )
