"""Exercise file loading and compression through the GTK window controller."""

from pathlib import Path
import subprocess
import tempfile

from gi.repository import GLib

from compressor import probe_source
from main import VideoCompressorApplication, VideoCompressorWindow


temporary_directory = tempfile.TemporaryDirectory()
source_path = Path(temporary_directory.name, "source.mp4")
output_path = Path(temporary_directory.name, "output.mp4")
subprocess.run(
    [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=320x180:rate=24",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=48000",
        "-t",
        "1",
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        str(source_path),
    ],
    check=True,
)

application = VideoCompressorApplication()
state = {"started": False, "exit_code": 1, "ticks": 0}


def exercise_window() -> bool:
    state["ticks"] += 1
    window = application.props.active_window
    if not isinstance(window, VideoCompressorWindow):
        return GLib.SOURCE_CONTINUE
    if window.source is None:
        if state["ticks"] == 1:
            window.load_file(str(source_path))
        return GLib.SOURCE_CONTINUE
    if not state["started"]:
        state["started"] = True
        window._start_compression(str(output_path))
        return GLib.SOURCE_CONTINUE
    if window._runner is not None:
        return GLib.SOURCE_CONTINUE

    try:
        output = probe_source(str(output_path))
    except Exception as error:
        print(f"GTK compression smoke test failed: {error}")
    else:
        if output.width == 320 and output.height == 180 and output.duration > 0:
            state["exit_code"] = 0
    application.quit()
    return GLib.SOURCE_REMOVE


def fail_on_timeout() -> bool:
    print("GTK compression smoke test timed out")
    application.quit()
    return GLib.SOURCE_REMOVE


GLib.timeout_add(100, exercise_window)
GLib.timeout_add_seconds(20, fail_on_timeout)
run_status = application.run(["video-compressor"])
temporary_directory.cleanup()
raise SystemExit(run_status or state["exit_code"])
