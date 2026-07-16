"""Open and close the GTK application for CI startup validation."""

from gi.repository import GLib

from main import JoemtVideoCompressorApplication


application = JoemtVideoCompressorApplication()
GLib.timeout_add(1500, lambda: application.quit() or GLib.SOURCE_REMOVE)
raise SystemExit(application.run(["joemt-video-compressor"]))
