"""Step 2.4 channel media uploads and nine-position watermark rendering."""

import io
import os
from unittest import mock

import pytest

from app import create_app
from scriptase.modules.compose.video_processor import VideoProcessor


@pytest.fixture()
def client(tmp_path):
    app = create_app(discover_providers=False)
    app.config["TESTING"] = True
    with mock.patch("scriptase.modules.music.routes.MUSIC_DIR", str(tmp_path / "musics")):
        yield app.test_client()


def test_music_upload_returns_managed_ref(client):
    response = client.post(
        "/api/music/upload",
        data={"file": (io.BytesIO(b"ID3" + b"\0" * 32), "bed.mp3", "audio/mpeg")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    asset = response.get_json()
    assert asset["ref"].startswith("musics/")
    assert not asset["ref"].startswith("/")
    assert ":\\" not in asset["ref"]


def test_music_upload_rejects_renamed_non_audio(client):
    response = client.post(
        "/api/music/upload",
        data={"file": (io.BytesIO(b"not audio"), "notes.mp3", "audio/mpeg")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "BAD_REQUEST"


@pytest.mark.parametrize(
    ("position", "coordinates"),
    [
        ("top_left", "overlay=x=32:y=32"),
        ("top_center", "overlay=x=(W-w)/2:y=32"),
        ("top_right", "overlay=x=W-w-32:y=32"),
        ("middle_left", "overlay=x=32:y=(H-h)/2"),
        ("center", "overlay=x=(W-w)/2:y=(H-h)/2"),
        ("middle_right", "overlay=x=W-w-32:y=(H-h)/2"),
        ("bottom_left", "overlay=x=32:y=H-h-32"),
        ("bottom_center", "overlay=x=(W-w)/2:y=H-h-32"),
        ("bottom_right", "overlay=x=W-w-32:y=H-h-32"),
    ],
)
@pytest.mark.parametrize("resolution", [(1080, 1920), (1920, 1080), (1080, 1080)])
def test_watermark_coordinates_cover_all_positions_and_profiles(
    tmp_path, monkeypatch, position, coordinates, resolution
):
    branding = tmp_path / "output" / "branding"
    branding.mkdir(parents=True)
    logo = branding / "logo.png"
    logo.write_bytes(b"png")
    input_path = tmp_path / "input.mp4"
    input_path.write_bytes(b"video")
    output_path = tmp_path / "output.mp4"
    captured = {}

    def run(command, **_kwargs):
        captured["command"] = command
        return mock.Mock(returncode=0, stderr="")

    monkeypatch.setattr("scriptase.modules.compose.video_processor.subprocess.run", run)
    processor = VideoProcessor({
        "output": {"resolution": {"width": resolution[0], "height": resolution[1]}},
    })
    processor.project_root = str(tmp_path)
    processor._apply_logo_overlay(
        str(input_path), str(output_path),
        {"path": "/output/branding/logo.png", "position": position},
    )

    filter_graph = captured["command"][captured["command"].index("-filter_complex") + 1]
    assert coordinates in filter_graph
