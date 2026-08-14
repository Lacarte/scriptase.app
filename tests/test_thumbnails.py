"""Security and path-boundary tests for the thumbnail transport."""

from pathlib import Path
from types import SimpleNamespace

from flask import Flask

from scriptase.modules.thumbnails import routes


def _client(monkeypatch, tmp_path):
    thumbnails = tmp_path / "thumbnails"
    monkeypatch.setattr(routes, "THUMBNAILS_DIR", str(thumbnails))
    app = Flask(__name__)
    app.register_blueprint(routes.thumbnails_bp)
    return app.test_client(), thumbnails


def test_invalid_project_id_cannot_alias_an_existing_project(monkeypatch, tmp_path):
    client, thumbnails = _client(monkeypatch, tmp_path)
    target = thumbnails / "project" / "assets"
    target.mkdir(parents=True)
    (target / "0.jpg").write_bytes(b"jpeg")

    assert client.get("/api/thumbnails/project!").status_code == 400
    assert client.get("/api/thumbnails/project!/assets/0.jpg").status_code == 400


def test_editor_thumbnail_rejects_media_path_escaping_output(monkeypatch, tmp_path):
    projects = tmp_path / "projects"
    output = tmp_path / "output"
    project_dir = projects / "project"
    project_dir.mkdir(parents=True)
    output.mkdir()
    (project_dir / "initial.json").write_text(
        '{"scenes": [{"mediaUrl": "/output/../secret.png"}]}',
        encoding="utf-8",
    )
    (tmp_path / "secret.png").write_bytes(b"secret")

    calls = []
    monkeypatch.setattr(routes, "PROJECTS_DIR", str(projects))
    monkeypatch.setattr(routes, "OUTPUT_DIR", str(output))
    monkeypatch.setattr(
        routes,
        "_extract_thumb",
        lambda src, dest, ffmpeg: calls.append(Path(src)) or True,
    )

    result = routes._generate_editor_thumb("project", "ffmpeg")

    assert result == {"generated": 0, "skipped": 0, "errors": 1}
    assert calls == []


def test_editor_thumbnail_rejects_media_path_escaping_working_assets(monkeypatch, tmp_path):
    projects = tmp_path / "projects"
    working_assets = tmp_path / "working-assets"
    project_dir = projects / "project"
    project_dir.mkdir(parents=True)
    working_assets.mkdir()
    (project_dir / "initial.json").write_text(
        '{"scenes": [{"mediaUrl": "working-assets/../secret.png"}]}',
        encoding="utf-8",
    )
    (tmp_path / "secret.png").write_bytes(b"secret")

    calls = []
    monkeypatch.setattr(routes, "PROJECTS_DIR", str(projects))
    monkeypatch.setattr(routes, "ROOT_DIR", str(tmp_path))
    monkeypatch.setattr(
        routes,
        "_extract_thumb",
        lambda src, dest, ffmpeg: calls.append(Path(src)) or True,
    )

    result = routes._generate_editor_thumb("project", "ffmpeg")

    assert result == {"generated": 0, "skipped": 0, "errors": 1}
    assert calls == []


def test_extract_thumb_does_not_report_failed_ffmpeg_as_success(monkeypatch, tmp_path):
    source = tmp_path / "source.png"
    destination = tmp_path / "thumb.jpg"
    source.write_bytes(b"png")
    destination.write_bytes(b"stale thumbnail")
    monkeypatch.setattr(
        routes.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1),
    )

    assert routes._extract_thumb(str(source), str(destination), "ffmpeg") is False
