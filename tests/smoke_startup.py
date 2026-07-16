"""Open and close the GTK application for CI startup validation."""

from gi.repository import GLib

from main import VideoCompressorApplication


application = VideoCompressorApplication()
GLib.timeout_add(1500, lambda: application.quit() or GLib.SOURCE_REMOVE)
raise SystemExit(application.run(["video-compressor"]))
