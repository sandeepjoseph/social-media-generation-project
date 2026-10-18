"""Local media checks for native cinema; no provider calls or review claims."""

from pathlib import Path
import math
import subprocess


def run_ffmpeg(args):
    import imageio_ffmpeg

    result = subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-hide_banner",
            "-v",
            "error",
            "-nostdin",
            *map(str, args),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(
            f"FFmpeg failed ({result.returncode}): {result.stderr[-3000:]}"
        )
    return result


def decode_video(path, *, expected_frames, samples=(), dimensions=(1280, 720)):
    """Decode every frame. Motion variation alone never approves acting/lips."""
    import av
    import numpy as np

    wanted = set(samples)
    images = {}
    black = []
    deltas = []
    times = []
    previous = None
    errors = []
    with av.open(str(Path(path))) as container:
        if len(container.streams.video) != 1:
            raise ValueError("Exactly one video stream is required")
        stream = container.streams.video[0]
        rate = float(stream.average_rate) if stream.average_rate else None
        info = {
            "dimensions": [stream.width, stream.height],
            "fps": rate,
            "codec": stream.codec_context.name,
            "time_base": str(stream.time_base),
            "has_source_audio": bool(container.streams.audio),
        }
        for index, frame in enumerate(container.decode(video=0)):
            pixels = frame.to_ndarray(format="rgb24")
            times.append(float(frame.time) if frame.time is not None else None)
            thumb = pixels[::12, ::12].astype(np.float32)
            if float(thumb.mean()) < 3 and float(np.mean(thumb < 12)) > 0.995:
                black.append(index)
            if previous is not None:
                deltas.append(float(np.mean(np.abs(thumb - previous))) / 255)
            previous = thumb
            if index in wanted:
                images[index] = pixels.copy()
    if info["dimensions"] != list(dimensions):
        errors.append("unexpected_dimensions")
    if rate is None or not math.isclose(rate, 24, abs_tol=1e-6):
        errors.append("native_24fps_required")
    if len(times) != expected_frames:
        errors.append("frame_count_mismatch")
    if not times or any(t is None for t in times):
        errors.append("presentation_timestamps_missing")
    else:
        error = max(abs((t - times[0]) - i / 24) for i, t in enumerate(times))
        if error > 0.001:
            errors.append("nonlinear_native_timestamps")
        info["max_relative_pts_error_seconds"] = error
    if wanted - set(images):
        errors.append("requested_frames_missing")
    if black:
        errors.append("near_black_frames_present")
    if deltas and max(deltas) < 1e-8:
        errors.append("entire_clip_exactly_static")
    info.update(
        fully_decoded_frames=len(times),
        frame_duration_seconds=len(times) / 24,
        near_black_frame_indices=black,
        technical_pass=not errors,
        errors=errors,
        motion_measurement_limit="Pixel variation is not proof of character performance or lip synchronization.",
    )
    return info, images
