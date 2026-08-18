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


def create_app(
    *,
    discover_providers: bool = True,
    start_triggers: bool | None = None,
    reconcile: bool | None = None,
    seed_default_workflow: bool | None = None,
) -> Flask:
    """Application factory.

    ``start_triggers`` controls the schedule / watch-folder / channel-cadence
    background services. Step 9.2 starts them from the factory so they run under
    both the dev server and a WSGI host (V2 only started them under
    ``__main__``). Default is on unless ``SCRIPTASE_DISABLE_TRIGGERS=1`` or the
    process is under pytest; pass ``start_triggers=True/False`` to override.

    ``reconcile`` runs crash recovery on boot (step 10.3): fail mid-run
    executions/jobs, reclaim dead project locks, and purge orphaned staging.
    Default is on for real servers; off under pytest so unit tests do not
    mutate a developer's ``output/``. Pass ``reconcile=True/False`` to override.

    ``seed_default_workflow`` materialises the Full Video template as a saved
    workflow on a fresh install (step 12.2), so the builder and Production both
    open on a complete graph rather than on nothing. Gated like ``reconcile``.
    """
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

    if reconcile is None:
        reconcile = _default_reconcile()
    app.config["STARTUP_RECONCILE"] = bool(reconcile)
    if reconcile:
        run_startup_reconciliation()

    if seed_default_workflow is None:
        seed_default_workflow = _default_seed_workflow()
    app.config["SEED_DEFAULT_WORKFLOW"] = bool(seed_default_workflow)
    if seed_default_workflow:
        seed_default_workflow_once()

    if start_triggers is None:
        start_triggers = _default_start_triggers()
    app.config["START_TRIGGERS"] = bool(start_triggers)
    if start_triggers:
        start_trigger_services()
    return app


def _default_start_triggers() -> bool:
    """Triggers on for real servers; off under pytest and when explicitly disabled."""
    if os.environ.get("SCRIPTASE_DISABLE_TRIGGERS", "").strip().lower() in {
        "1", "true", "yes", "on",
    }:
        return False
    if os.environ.get("SCRIPTASE_START_TRIGGERS", "").strip().lower() in {
        "0", "false", "no", "off",
    }:
        return False
    # pytest sets this for every test item; keep unit tests free of daemon threads.
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    if os.environ.get("SCRIPTASE_TESTING", "").strip().lower() in {
        "1", "true", "yes", "on",
    }:
        return False
    return True


def _default_reconcile() -> bool:
    """Reconciliation on for real servers; off under pytest unless forced.

    ``SCRIPTASE_DISABLE_RECONCILE=1`` always skips (conftest sets this for the
    whole pytest process so unit tests never mutate a developer's
    ``output/``). ``SCRIPTASE_RECONCILE=1`` forces a pass even then.
    """
    if os.environ.get("SCRIPTASE_DISABLE_RECONCILE", "").strip().lower() in {
        "1", "true", "yes", "on",
    }:
        return False
    if os.environ.get("SCRIPTASE_RECONCILE", "").strip().lower() in {
        "1", "true", "yes", "on",
    }:
        return True
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    if os.environ.get("SCRIPTASE_TESTING", "").strip().lower() in {
        "1", "true", "yes", "on",
    }:
        return False
    return True


def _default_seed_workflow() -> bool:
    """First-run seeding on for real servers; off under pytest.

    ``SCRIPTASE_DISABLE_DEFAULT_WORKFLOW=1`` always skips, for an installation
    that wants to start from a genuinely empty store.
    """
    if os.environ.get("SCRIPTASE_DISABLE_DEFAULT_WORKFLOW", "").strip().lower() in {
        "1", "true", "yes", "on",
    }:
        return False
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    if os.environ.get("SCRIPTASE_TESTING", "").strip().lower() in {
        "1", "true", "yes", "on",
    }:
        return False
    return True


def seed_default_workflow_once() -> dict | None:
    """Seed the Full Video workflow on a fresh install (step 12.2).

    Safe to call more than once. Failures are logged and never abort boot — an
    unwritable workflow store is a problem the user must be able to see in the
    UI, not one that keeps the server from starting.
    """
    from loguru import logger

    from scriptase.engine.persistence import ensure_default_workflow

    try:
        return ensure_default_workflow()
    except Exception as exc:
        logger.exception("[startup] could not seed the default workflow: {}", exc)
        return None


def run_startup_reconciliation() -> dict:
    """Fail mid-run records, reclaim dead locks, purge orphaned staging.

    Safe to call more than once. Failures are logged and never abort boot —
    a half-broken store should not take the API down with it.
    """
    from loguru import logger

    from scriptase.engine.reconciliation import reconcile_on_startup

    try:
        report = reconcile_on_startup()
        return report.to_dict()
    except Exception as exc:
        logger.exception("[reconciliation] startup pass aborted: {}", exc)
        return {"changed": False, "error": str(exc)}


def start_trigger_services() -> dict[str, bool]:
    """Start schedule, watch-folder, and channel-cadence services (idempotent).

    Safe to call from the app factory, a WSGI entrypoint, or the dev
    ``__main__`` block. Returns a map of service name → running state.
    """
    from scriptase.channels.cadence import channel_cadence_service
    from scriptase.engine.scheduled_runs import schedule_service
    from scriptase.engine.watch_folders import watch_folder_service

    schedule_service.start()
    watch_folder_service.start()
    channel_cadence_service.start()
    return {
        "schedule": schedule_service.is_running,
        "watch_folder": watch_folder_service.is_running,
        "channel_cadence": channel_cadence_service.is_running,
    }


def stop_trigger_services() -> None:
    """Stop background trigger services (tests / orderly shutdown)."""
    from scriptase.channels.cadence import channel_cadence_service
    from scriptase.engine.scheduled_runs import schedule_service
    from scriptase.engine.watch_folders import watch_folder_service

    schedule_service.stop()
    watch_folder_service.stop()
    channel_cadence_service.stop()


def register_blueprints(app: Flask) -> None:
    """Attach feature blueprints. Populated as packages land in Phase 0.

    Transport only. Every blueprint here is a thin shell over a service module,
    which is why step 0.3 could split V2's 2,821-line editor blueprint into the
    seven `compose_*` ones below without moving a single behaviour: the logic
    they used to hold now lives in `scriptase/modules/compose/*_service.py`.
    """
    from scriptase.artifacts import artifacts_bp
    from scriptase.channels import channels_bp
    from scriptase.engine.routes import workflows_bp
    from scriptase.jobs.routes import jobs_bp
    from scriptase.migration.routes import migration_bp
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
    from scriptase.scripts import scripts_bp

    app.register_blueprint(workflows_bp)
    app.register_blueprint(providers_bp)
    app.register_blueprint(channels_bp)
    app.register_blueprint(jobs_bp)
    app.register_blueprint(artifacts_bp)
    app.register_blueprint(scripts_bp)
    app.register_blueprint(migration_bp)

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

    # The six destinations (step 1.1), then the routes that stay reachable
    # without being destinations. A hard reload or a pasted URL is a plain GET
    # to Flask, so each one needs a handler here or it 404s outside Vite.
    @app.get("/script")
    @app.get("/production")
    @app.get("/schema")
    @app.get("/library")
    @app.get("/channels")
    @app.get("/channels/<path:_rest>")
    @app.get("/providers")
    @app.get("/workflow")
    @app.get("/workflow/<path:_rest>")
    # /editor and /library open as their own windows (step 14.4), so a reload
    # in one of them hits Flask directly rather than an in-app navigation.
    @app.get("/editor")
    # Previous paths. They reach the shell so vue-router can redirect them,
    # rather than the server answering 404 before the app ever loads.
    @app.get("/exports")
    @app.get("/settings/providers")
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
    # Dev server: factory starts trigger services (step 9.2). The same hook
    # runs under WSGI via wsgi.py — V2 only started them under __main__.
    application = create_app(start_triggers=True)
    application.run(
        host=config.HOST, port=config.PORT, debug=config.DEBUG, threaded=True
    )
