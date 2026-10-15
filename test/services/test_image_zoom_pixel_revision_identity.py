import shutil
from pathlib import Path

import numpy as np
import pytest
from moviepy import VideoFileClip
from PIL import Image

from app.config import config
from app.services import video


def test_updated_image_does_not_replace_previous_rendered_pixels(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("native FFmpeg required")
    source = tmp_path / "scene.png"
    Image.new("RGB", (64, 64), "red").save(source)
    first = video.render_image_zoom_video(str(source), clip_duration=0.1)
    first_bytes = Path(first).read_bytes()
    Image.new("RGB", (64, 64), "blue").save(source)
    second = video.render_image_zoom_video(str(source), clip_duration=0.1)
    assert first != second
    assert Path(first).read_bytes() == first_bytes
    for output, channel in [(first, 0), (second, 2)]:
        with VideoFileClip(output, audio=False) as rendered:
            assert rendered.get_frame(0)[32, 32, channel] > 200


def test_zoom_setting_changes_effect_and_render_identity(tmp_path, monkeypatch):
    source = tmp_path / "scene.png"
    source.write_bytes(b"same source for both render settings")
    end_scales = []

    class FakeClip:
        duration = 0
        mask = None

        def with_duration(self, duration):
            self.duration = duration
            return self

        def with_position(self, _position):
            return self

        def resized(self, resize):
            end_scales.append(resize(self.duration))
            return self

        def get_frame(self, _time):
            return np.zeros((2, 2, 3), dtype=np.uint8)

        def close(self):
            pass

    class FakeComposite:
        def write_videofile(self, output_path, **_kwargs):
            Path(output_path).write_bytes(b"rendered")

        def close(self):
            pass

    monkeypatch.setattr(video, "_open_image_clip_with_fallback", lambda _path: (FakeClip(), None))
    monkeypatch.setattr(video, "CompositeVideoClip", lambda _clips, **_kwargs: FakeComposite())
    monkeypatch.setitem(config.app, "image_zoom_ratio", 0.0)
    no_zoom = video.render_image_zoom_video(str(source), clip_duration=2)
    monkeypatch.setitem(config.app, "image_zoom_ratio", 0.5)
    max_zoom = video.render_image_zoom_video(str(source), clip_duration=2)

    assert end_scales == [1.0, 1.5]
    assert no_zoom != max_zoom
    assert Path(no_zoom).is_file()
    assert Path(max_zoom).is_file()
