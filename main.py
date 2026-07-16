#!/usr/bin/env python3
"""GTK 4 and libadwaita interface for Joemt Video Compressor."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from compressor import (  # noqa: E402
    DEFAULT_AUDIO_BITRATE_KBPS,
    FFmpegToolchain,
    FFmpegRunner,
    SourceInfo,
    VIDEO_CODECS,
    ValidationError,
    calculate_video_bitrate,
    ensure_even,
    evaluate_expression,
    make_job,
    probe_source,
    resolve_ffmpeg_toolchain,
)


APPLICATION_ID = "io.github.Joedotmt.JoemtVideoCompressor"
APPLICATION_NAME = "Joemt Video Compressor"
VERSION = "2.0.0"

CODEC_OPTIONS = list(VIDEO_CODECS.items())
H26X_PRESETS = [
    ("Very Fast", "ultrafast"),
    ("Fast", "fast"),
    ("Balanced", "medium"),
    ("Slow", "slow"),
]
AV1_PRESETS = [
    ("Highest Quality", "0"),
    ("Very High Quality", "1"),
    ("High Quality", "2"),
    ("Quality", "3"),
    ("Balanced", "4"),
    ("Fast", "5"),
    ("Fastest", "6"),
]
TUNE_OPTIONS: list[tuple[str, str | None]] = [
    ("None", None),
    ("Film", "film"),
    ("Animation", "animation"),
    ("Grain", "grain"),
    ("Still Image", "stillimage"),
]


def format_decimal(value: float, places: int = 2) -> str:
    return f"{value:.{places}f}".rstrip("0").rstrip(".")


def format_duration(seconds: float) -> str:
    rounded = max(0, round(seconds))
    hours, remainder = divmod(rounded, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def icon_button(icon_name: str, tooltip: str, action_name: str | None = None) -> Gtk.Button:
    button = Gtk.Button.new_from_icon_name(icon_name)
    button.set_tooltip_text(tooltip)
    button.update_property([Gtk.AccessibleProperty.LABEL], [tooltip])
    if action_name:
        button.set_action_name(action_name)
    return button


class JoemtVideoCompressorWindow(Adw.ApplicationWindow):
    def __init__(self, application: "JoemtVideoCompressorApplication") -> None:
        super().__init__(application=application)
        self.set_title(APPLICATION_NAME)
        self.set_default_size(720, 760)

        self.source: SourceInfo | None = None
        self._probe_generation = 0
        self._pending_file: str | None = None
        self._ffmpeg_state = "checking"
        self._ffmpeg_toolchain: FFmpegToolchain | None = None
        self._runner: FFmpegRunner | None = None
        self._worker_thread: threading.Thread | None = None
        self._close_dialog: Adw.AlertDialog | None = None
        self._close_when_finished = False
        self._updating_form = False
        self._form_valid = False

        self._build_interface()
        self.connect("close-request", self._on_close_request)
        self._check_requirements()

    def _build_interface(self) -> None:
        self.toolbar_view = Adw.ToolbarView.new()
        self.set_content(self.toolbar_view)

        header = Adw.HeaderBar.new()
        self.window_title = Adw.WindowTitle.new(APPLICATION_NAME, "")
        header.set_title_widget(self.window_title)

        self.open_header_button = icon_button(
            "document-open-symbolic", "Open Video", "app.open"
        )
        self.open_header_button.set_sensitive(False)
        header.pack_start(self.open_header_button)

        menu = Gio.Menu.new()
        menu.append(f"About {APPLICATION_NAME}", "app.about")
        menu.append("Quit", "app.quit")
        menu_button = Gtk.MenuButton.new()
        menu_button.set_icon_name("open-menu-symbolic")
        menu_button.set_tooltip_text("Main Menu")
        menu_button.update_property([Gtk.AccessibleProperty.LABEL], ["Main Menu"])
        menu_button.set_menu_model(menu)
        header.pack_end(menu_button)
        self.toolbar_view.add_top_bar(header)

        self.toast_overlay = Adw.ToastOverlay.new()
        self.toolbar_view.set_content(self.toast_overlay)

        self.page_stack = Gtk.Stack.new()
        self.page_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.toast_overlay.set_child(self.page_stack)

        self.status_page = Adw.StatusPage.new()
        self.page_stack.add_named(self.status_page, "status")

        self.status_spinner = Gtk.Spinner.new()
        self.status_spinner.start()
        self.status_page.set_icon_name("system-run-symbolic")
        self.status_page.set_title("Checking Requirements")
        self.status_page.set_description("Looking for FFmpeg and FFprobe…")
        self.status_page.set_child(self.status_spinner)

        self.open_status_button = Gtk.Button.new_with_mnemonic("_Open Video…")
        self.open_status_button.add_css_class("suggested-action")
        self.open_status_button.add_css_class("pill")
        self.open_status_button.set_action_name("app.open")

        self.install_ffmpeg_button = Gtk.Button.new_with_mnemonic("_Install FFmpeg")
        self.install_ffmpeg_button.add_css_class("suggested-action")
        self.install_ffmpeg_button.add_css_class("pill")
        self.install_ffmpeg_button.connect("clicked", self._install_ffmpeg)

        self.editor = self._build_editor()
        self.page_stack.add_named(self.editor, "editor")
        self.page_stack.set_visible_child_name("status")

        self.bottom_bar = self._build_bottom_bar()
        self.bottom_bar.set_visible(False)
        self.toolbar_view.add_bottom_bar(self.bottom_bar)

        drop_target = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop_target.connect("drop", self._on_drop)
        self.add_controller(drop_target)

    def _build_editor(self) -> Gtk.ScrolledWindow:
        scroller = Gtk.ScrolledWindow.new()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)

        clamp = Adw.Clamp.new()
        clamp.set_maximum_size(680)
        clamp.set_tightening_threshold(500)
        scroller.set_child(clamp)

        self.settings_box = Gtk.Box.new(Gtk.Orientation.VERTICAL, 18)
        self.settings_box.set_margin_top(24)
        self.settings_box.set_margin_bottom(24)
        self.settings_box.set_margin_start(18)
        self.settings_box.set_margin_end(18)
        clamp.set_child(self.settings_box)

        input_group = Adw.PreferencesGroup.new()
        input_group.set_title("Input Video")
        self.source_row = Adw.ActionRow.new()
        self.source_row.set_title("No video selected")
        source_icon = Gtk.Image.new_from_icon_name("video-x-generic-symbolic")
        self.source_row.add_prefix(source_icon)
        choose_button = icon_button("document-open-symbolic", "Choose Another Video", "app.open")
        choose_button.add_css_class("flat")
        self.source_row.add_suffix(choose_button)
        input_group.add(self.source_row)
        self.settings_box.append(input_group)

        output_group = Adw.PreferencesGroup.new()
        output_group.set_title("Output")
        output_group.set_description("Choose the approximate maximum size of the compressed file.")
        source_size_button = Gtk.Button.new_with_label("Reset")
        source_size_button.set_tooltip_text("Use Source Size")
        source_size_button.add_css_class("flat")
        source_size_button.connect("clicked", self._use_source_size)
        output_group.set_header_suffix(source_size_button)

        self.target_size_row = self._entry_row("Target Size", "MB")
        self.estimated_bitrate_row = Adw.ActionRow.new()
        self.estimated_bitrate_row.set_title("Estimated Video Bitrate")
        self.estimated_bitrate_row.set_subtitle("—")
        self.estimated_bitrate_row.add_css_class("property")
        output_group.add(self.target_size_row)
        output_group.add(self.estimated_bitrate_row)
        self.settings_box.append(output_group)

        video_group = Adw.PreferencesGroup.new()
        video_group.set_title("Video")
        source_video_button = Gtk.Button.new_with_label("Reset")
        source_video_button.set_tooltip_text("Use Source Video Settings")
        source_video_button.add_css_class("flat")
        source_video_button.connect("clicked", self._use_source_video_settings)
        video_group.set_header_suffix(source_video_button)

        self.width_row = self._entry_row("Width", "px")
        self.height_row = self._entry_row("Height", "px")
        self.fps_row = self._entry_row("Frame Rate", "fps")
        self.video_preview_row = Adw.ActionRow.new()
        self.video_preview_row.set_title("Output Video")
        self.video_preview_row.set_subtitle("—")
        self.video_preview_row.add_css_class("property")
        for row in (self.width_row, self.height_row, self.fps_row, self.video_preview_row):
            video_group.add(row)
        self.settings_box.append(video_group)

        audio_group = Adw.PreferencesGroup.new()
        audio_group.set_title("Audio")
        source_audio_button = Gtk.Button.new_with_label("Reset")
        source_audio_button.set_tooltip_text("Use Source Audio Bitrate")
        source_audio_button.add_css_class("flat")
        source_audio_button.connect("clicked", self._use_source_audio_bitrate)
        audio_group.set_header_suffix(source_audio_button)

        self.include_audio_row = Adw.SwitchRow.new()
        self.include_audio_row.set_title("Audio")
        self.include_audio_row.set_subtitle("Include audio in the compressed video")
        self.include_audio_row.set_active(True)
        self.audio_bitrate_row = self._entry_row("Audio Bitrate", "kbps")
        audio_group.add(self.include_audio_row)
        audio_group.add(self.audio_bitrate_row)
        self.settings_box.append(audio_group)

        advanced_group = Adw.PreferencesGroup.new()
        self.advanced_row = Adw.ExpanderRow.new()
        self.advanced_row.set_title("Advanced Options")
        self.advanced_row.set_subtitle("Codec, encoding speed, tuning, and playback speed")

        self.codec_row = self._combo_row("Codec", [label for label, _ in CODEC_OPTIONS])
        self.preset_row = self._combo_row("Encoding Preset", [])
        self.tune_row = self._combo_row("Tune For", [])
        self.speed_row = self._entry_row("Playback Speed", "×")
        self.speed_row.set_text("1")
        for row in (self.codec_row, self.preset_row, self.tune_row, self.speed_row):
            self.advanced_row.add_row(row)
        advanced_group.add(self.advanced_row)
        self.settings_box.append(advanced_group)

        for row in (
            self.target_size_row,
            self.width_row,
            self.height_row,
            self.fps_row,
            self.audio_bitrate_row,
            self.speed_row,
        ):
            row.connect("changed", self._on_form_changed)
        self.include_audio_row.connect("notify::active", self._on_audio_changed)
        self.codec_row.connect("notify::selected", self._on_codec_changed)

        self._configure_encoder_rows()
        return scroller

    def _build_bottom_bar(self) -> Gtk.Box:
        container = Gtk.Box.new(Gtk.Orientation.VERTICAL, 8)
        container.set_margin_top(10)
        container.set_margin_bottom(10)
        container.set_margin_start(12)
        container.set_margin_end(12)

        self.progress_bar = Gtk.ProgressBar.new()
        self.progress_bar.set_show_text(True)
        self.progress_bar.set_text("0%")
        self.progress_bar.set_visible(False)
        container.append(self.progress_bar)

        actions = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 8)
        actions.set_halign(Gtk.Align.END)
        self.compress_button = Gtk.Button.new_with_mnemonic("_Compress")
        self.compress_button.add_css_class("suggested-action")
        self.compress_button.add_css_class("pill")
        self.compress_button.connect("clicked", self._choose_output)
        actions.append(self.compress_button)

        self.cancel_button = Gtk.Button.new_with_mnemonic("_Cancel Compression")
        self.cancel_button.add_css_class("pill")
        self.cancel_button.set_visible(False)
        self.cancel_button.connect("clicked", self._cancel_compression)
        actions.append(self.cancel_button)
        container.append(actions)
        return container

    @staticmethod
    def _entry_row(title: str, unit: str) -> Adw.EntryRow:
        row = Adw.EntryRow.new()
        row.set_title(title)
        row.set_input_purpose(Gtk.InputPurpose.FREE_FORM)
        row.add_css_class("numeric")
        unit_label = Gtk.Label.new(unit)
        unit_label.add_css_class("dim-label")
        row.add_suffix(unit_label)
        return row

    @staticmethod
    def _combo_row(title: str, labels: list[str]) -> Adw.ComboRow:
        row = Adw.ComboRow.new()
        row.set_title(title)
        row.set_model(Gtk.StringList.new(labels))
        return row

    def _set_combo_options(
        self, row: Adw.ComboRow, options: list[tuple[str, object]], selected: int
    ) -> None:
        row.set_model(Gtk.StringList.new([label for label, _ in options]))
        row.set_selected(min(selected, len(options) - 1))

    def _configure_encoder_rows(self, *_args: object) -> None:
        codec = self._selected_value(self.codec_row, CODEC_OPTIONS)
        if codec == "libaom-av1":
            self._preset_options = AV1_PRESETS
            preset_index = 4
            self._tune_options = [("None", None)]
            self.tune_row.set_sensitive(False)
        else:
            self._preset_options = H26X_PRESETS
            preset_index = 2
            self._tune_options = TUNE_OPTIONS
            self.tune_row.set_sensitive(True)
        self._set_combo_options(self.preset_row, self._preset_options, preset_index)
        self._set_combo_options(self.tune_row, self._tune_options, 0)

    @staticmethod
    def _selected_value(row: Adw.ComboRow, options: list[tuple[str, object]]) -> object:
        selected = row.get_selected()
        if selected >= len(options):
            return options[0][1]
        return options[selected][1]

    def _check_requirements(self) -> None:
        def work() -> None:
            toolchain = resolve_ffmpeg_toolchain()
            GLib.idle_add(self._requirements_checked, toolchain)

        threading.Thread(target=work, name="ffmpeg-check", daemon=True).start()

    def _requirements_checked(self, toolchain: FFmpegToolchain | None) -> bool:
        self.status_spinner.stop()
        self._ffmpeg_toolchain = toolchain
        self._ffmpeg_state = "ready" if toolchain is not None else "missing"
        if toolchain is not None:
            self.open_header_button.set_sensitive(True)
            self.status_page.set_icon_name("video-x-generic-symbolic")
            self.status_page.set_title("Choose a Video")
            self.status_page.set_description("Select a video to compress, or drop one here.")
            self.status_page.set_child(self.open_status_button)
            if self._pending_file:
                path, self._pending_file = self._pending_file, None
                self.load_file(path)
        else:
            self.status_page.set_icon_name("dialog-error-symbolic")
            self.status_page.set_title("FFmpeg Is Required")
            if os.name == "nt":
                self.status_page.set_description(
                    f"{APPLICATION_NAME} can install the FFmpeg Essentials Build using "
                    "Windows Package Manager. FFmpeg is a separate GPLv3 package."
                )
                self.status_page.set_child(self.install_ffmpeg_button)
            else:
                self.status_page.set_description(
                    "Install FFmpeg and FFprobe, then reopen the application.\n\n"
                    "On Ubuntu: sudo apt install ffmpeg"
                )
                self.status_page.set_child(None)
        return GLib.SOURCE_REMOVE

    def _install_ffmpeg(self, _button: Gtk.Button | None = None) -> None:
        if os.name != "nt" or self._ffmpeg_state == "installing":
            return

        self._ffmpeg_state = "installing"
        self.install_ffmpeg_button.set_sensitive(False)
        self.status_page.set_icon_name("system-run-symbolic")
        self.status_page.set_title("Installing FFmpeg")
        self.status_page.set_description("Downloading the FFmpeg Essentials Build…")
        self.status_spinner.start()
        self.status_page.set_child(self.status_spinner)

        def work() -> None:
            error = ""
            try:
                winget = shutil.which("winget")
                if winget is None:
                    local_app_data = os.environ.get("LOCALAPPDATA")
                    if local_app_data:
                        candidate = Path(
                            local_app_data, "Microsoft", "WindowsApps", "winget.exe"
                        )
                        if candidate.is_file():
                            winget = str(candidate)
                completed = subprocess.run(
                    [
                        winget or "winget",
                        "install",
                        "--id",
                        "Gyan.FFmpeg.Essentials",
                        "--exact",
                        "--source",
                        "winget",
                        "--scope",
                        "user",
                        "--silent",
                        "--accept-package-agreements",
                        "--accept-source-agreements",
                        "--disable-interactivity",
                    ],
                    capture_output=True,
                    text=True,
                    errors="replace",
                    timeout=15 * 60,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    check=False,
                )
                if completed.returncode != 0:
                    output = completed.stderr.strip() or completed.stdout.strip()
                    detail = (
                        output.splitlines()[-1]
                        if output
                        else "WinGet could not install FFmpeg."
                    )
                    error = detail[-500:]
            except FileNotFoundError:
                error = "Windows Package Manager (winget) is not available."
            except subprocess.TimeoutExpired:
                error = "The FFmpeg installation timed out."
            except OSError as exception:
                error = f"Could not start the FFmpeg installer: {exception}"

            toolchain = resolve_ffmpeg_toolchain()
            if toolchain is not None:
                error = ""
            if not error and toolchain is None:
                error = (
                    "FFmpeg was installed but could not be found. "
                    "Restart the application and try again."
                )
            GLib.idle_add(self._ffmpeg_install_finished, toolchain, error)

        threading.Thread(target=work, name="ffmpeg-install", daemon=True).start()

    def _ffmpeg_install_finished(
        self, toolchain: FFmpegToolchain | None, error: str
    ) -> bool:
        self.install_ffmpeg_button.set_sensitive(True)
        if toolchain is not None:
            self._show_toast("FFmpeg installed")
            return self._requirements_checked(toolchain)

        self._requirements_checked(None)
        if "winget) is not available" in error:
            advice = (
                "Install or update Microsoft App Installer, or install FFmpeg manually "
                f"and restart {APPLICATION_NAME}."
            )
        else:
            advice = (
                "You can also install it from a terminal with:\n"
                "winget install --id Gyan.FFmpeg.Essentials --exact"
            )
        self._show_error("Could Not Install FFmpeg", f"{error}\n\n{advice}")
        return GLib.SOURCE_REMOVE

    def open_file_dialog(self) -> None:
        if self._ffmpeg_state != "ready" or self._runner is not None:
            return
        dialog = Gtk.FileDialog.new()
        dialog.set_title("Open Video")
        video_filter, filters = self._video_filters()
        dialog.set_filters(filters)
        dialog.set_default_filter(video_filter)
        dialog.open(self, None, self._open_file_finished)

    @staticmethod
    def _video_filters() -> tuple[Gtk.FileFilter, Gio.ListStore]:
        video_filter = Gtk.FileFilter.new()
        video_filter.set_name("Video Files")
        video_filter.add_mime_type("video/*")
        for pattern in ("*.mp4", "*.avi", "*.mkv", "*.mov", "*.webm", "*.m4v"):
            video_filter.add_pattern(pattern)
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(video_filter)
        return video_filter, filters

    def _open_file_finished(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        try:
            selected = dialog.open_finish(result)
        except GLib.Error as error:
            if not self._dialog_was_cancelled(error):
                self._show_toast(f"Could not open the file: {error.message}")
            return
        path = selected.get_path()
        if path:
            self.load_file(path)
        else:
            self._show_toast("Choose a local video file.")

    @staticmethod
    def _dialog_was_cancelled(error: GLib.Error) -> bool:
        return error.matches(Gtk.dialog_error_quark(), Gtk.DialogError.DISMISSED) or error.matches(
            Gtk.dialog_error_quark(), Gtk.DialogError.CANCELLED
        ) or error.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED)

    def _on_drop(
        self, _target: Gtk.DropTarget, file_list: Gdk.FileList, _x: float, _y: float
    ) -> bool:
        if self._ffmpeg_state != "ready" or self._runner is not None:
            return False
        files = file_list.get_files()
        if len(files) != 1:
            self._show_toast("Drop one video at a time.")
            return True
        path = files[0].get_path()
        if not path:
            self._show_toast("Choose a local video file.")
            return True
        self.load_file(path)
        return True

    def load_file(self, path: str) -> None:
        if self._ffmpeg_state == "checking":
            self._pending_file = path
            return
        if self._ffmpeg_state != "ready" or self._runner is not None:
            return

        self._probe_generation += 1
        generation = self._probe_generation
        self.open_header_button.set_sensitive(False)
        self.status_page.set_icon_name("video-x-generic-symbolic")
        self.status_page.set_title("Reading Video")
        self.status_page.set_description(Path(path).name)
        self.status_spinner.start()
        self.status_page.set_child(self.status_spinner)
        self.page_stack.set_visible_child_name("status")
        self.bottom_bar.set_visible(False)
        self.progress_bar.set_visible(False)

        def work() -> None:
            try:
                info = probe_source(path, self._ffmpeg_toolchain)
                error: Exception | None = None
            except Exception as caught:  # converted into a user-facing error on the main thread
                info = None
                error = caught
            GLib.idle_add(self._probe_finished, generation, info, error)

        threading.Thread(target=work, name="video-probe", daemon=True).start()

    def _probe_finished(
        self, generation: int, info: SourceInfo | None, error: Exception | None
    ) -> bool:
        if generation != self._probe_generation:
            return GLib.SOURCE_REMOVE
        self.status_spinner.stop()
        self.open_header_button.set_sensitive(True)
        if error is not None or info is None:
            self.status_page.set_icon_name("dialog-error-symbolic")
            self.status_page.set_title("Could Not Open Video")
            self.status_page.set_description(str(error) or "The file could not be read.")
            self.status_page.set_child(self.open_status_button)
            self.page_stack.set_visible_child_name("status")
            return GLib.SOURCE_REMOVE

        self.source = info
        self._populate_source(info)
        self.page_stack.set_visible_child_name("editor")
        self.bottom_bar.set_visible(True)
        return GLib.SOURCE_REMOVE

    def _populate_source(self, info: SourceInfo) -> None:
        self._updating_form = True
        try:
            self.window_title.set_subtitle(Path(info.path).name)
            self.source_row.set_title(Path(info.path).name)
            self.source_row.set_subtitle(
                f"{info.width} × {info.height}  •  {format_decimal(info.fps)} fps  •  "
                f"{format_duration(info.duration)}  •  {info.size_mb:.2f} MB"
            )
            self.target_size_row.set_text(f"{info.size_mb:.2f}")
            self.width_row.set_text(str(info.width))
            self.height_row.set_text(str(info.height))
            self.fps_row.set_text(format_decimal(info.fps))
            self.include_audio_row.set_active(info.has_audio)
            self.include_audio_row.set_sensitive(info.has_audio)
            self.include_audio_row.set_subtitle(
                "Include audio in the compressed video"
                if info.has_audio
                else "The source video does not contain audio"
            )
            audio_bitrate = info.audio_bitrate_kbps or DEFAULT_AUDIO_BITRATE_KBPS
            self.audio_bitrate_row.set_text(str(audio_bitrate))
            self.audio_bitrate_row.set_sensitive(info.has_audio)
            self.speed_row.set_text("1")
        finally:
            self._updating_form = False
        self._update_form()

    def _use_source_size(self, _button: Gtk.Button) -> None:
        if self.source:
            self.target_size_row.set_text(f"{self.source.size_mb:.2f}")

    def _use_source_video_settings(self, _button: Gtk.Button) -> None:
        if self.source:
            self.width_row.set_text(str(self.source.width))
            self.height_row.set_text(str(self.source.height))
            self.fps_row.set_text(format_decimal(self.source.fps))

    def _use_source_audio_bitrate(self, _button: Gtk.Button) -> None:
        if self.source and self.source.has_audio:
            self.include_audio_row.set_active(True)
            self.audio_bitrate_row.set_text(str(self.source.audio_bitrate_kbps))

    def _on_form_changed(self, _row: Adw.EntryRow) -> None:
        if not self._updating_form:
            self._update_form()

    def _on_audio_changed(self, _row: Adw.SwitchRow, _property: object) -> None:
        self.audio_bitrate_row.set_sensitive(self.include_audio_row.get_active())
        if not self._updating_form:
            self._update_form()

    def _on_codec_changed(self, _row: Adw.ComboRow, _property: object) -> None:
        self._configure_encoder_rows()
        if not self._updating_form:
            self._update_form()

    @staticmethod
    def _set_field_state(row: Adw.EntryRow, valid: bool, message: str = "") -> None:
        if valid:
            row.remove_css_class("error")
            row.set_tooltip_text(None)
            row.update_property([Gtk.AccessibleProperty.DESCRIPTION], [""])
        else:
            row.add_css_class("error")
            row.set_tooltip_text(message)
            row.update_property([Gtk.AccessibleProperty.DESCRIPTION], [message])

    def _number(
        self,
        row: Adw.EntryRow,
        *,
        minimum: float,
        maximum: float,
        label: str,
        even: bool = False,
    ) -> float | int | None:
        value = evaluate_expression(row.get_text())
        if value is None or value < minimum or value > maximum:
            self._set_field_state(
                row, False, f"{label} must be between {minimum:g} and {maximum:g}."
            )
            return None
        if even:
            adjusted = ensure_even(value)
            if adjusted is None or adjusted < minimum:
                self._set_field_state(row, False, f"{label} must be a positive even number.")
                return None
            value = adjusted
        self._set_field_state(row, True)
        return value

    def _read_form(self) -> dict[str, object] | None:
        target_mb = self._number(
            self.target_size_row, minimum=0.01, maximum=1_000_000, label="Target size"
        )
        width = self._number(
            self.width_row, minimum=2, maximum=16384, label="Width", even=True
        )
        height = self._number(
            self.height_row, minimum=2, maximum=16384, label="Height", even=True
        )
        fps = self._number(self.fps_row, minimum=0.01, maximum=1000, label="Frame rate")
        speed = self._number(
            self.speed_row, minimum=0.01, maximum=10000, label="Playback speed"
        )
        include_audio = self.include_audio_row.get_active()
        if include_audio:
            audio_bitrate = self._number(
                self.audio_bitrate_row,
                minimum=1,
                maximum=10000,
                label="Audio bitrate",
            )
        else:
            audio_bitrate = 0.0
            self._set_field_state(self.audio_bitrate_row, True)

        values = (target_mb, width, height, fps, speed, audio_bitrate)
        if any(value is None for value in values):
            return None
        return {
            "target_mb": float(target_mb),
            "width": int(width),
            "height": int(height),
            "fps": float(fps),
            "speed": float(speed),
            "audio_bitrate_kbps": float(audio_bitrate),
            "mute_audio": not include_audio,
            "codec": self._selected_value(self.codec_row, CODEC_OPTIONS),
            "preset": self._selected_value(self.preset_row, self._preset_options),
            "tune": self._selected_value(self.tune_row, self._tune_options),
        }

    def _update_form(self) -> None:
        values = self._read_form()
        self._form_valid = values is not None and self.source is not None
        if not self._form_valid or values is None or self.source is None:
            self.estimated_bitrate_row.set_subtitle("—")
            self.video_preview_row.set_subtitle("—")
            self.compress_button.set_sensitive(False)
            return

        width = int(values["width"])
        height = int(values["height"])
        fps = float(values["fps"])
        self.video_preview_row.set_subtitle(
            f"{width} × {height}  •  {format_decimal(fps)} fps"
        )
        try:
            video_bps = calculate_video_bitrate(
                float(values["target_mb"]),
                self.source.duration,
                float(values["speed"]),
                round(float(values["audio_bitrate_kbps"]) * 1000),
                bool(values["mute_audio"]),
            )
        except ValidationError as error:
            self._set_field_state(self.target_size_row, False, str(error))
            self.estimated_bitrate_row.set_subtitle(str(error))
            self._form_valid = False
        else:
            self.estimated_bitrate_row.set_subtitle(f"{video_bps / 1000:,.0f} kbps  •  approximate")
        self.compress_button.set_sensitive(self._form_valid and self._runner is None)

    def _choose_output(self, _button: Gtk.Button) -> None:
        if not self._form_valid or self.source is None or self._runner is not None:
            return
        dialog = Gtk.FileDialog.new()
        dialog.set_title("Save Compressed Video")
        dialog.set_initial_name(f"{Path(self.source.path).stem}_compressed.mp4")
        mp4_filter = Gtk.FileFilter.new()
        mp4_filter.set_name("MP4 Video")
        mp4_filter.add_mime_type("video/mp4")
        mp4_filter.add_pattern("*.mp4")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(mp4_filter)
        dialog.set_filters(filters)
        dialog.set_default_filter(mp4_filter)
        dialog.save(self, None, self._save_file_finished)

    def _save_file_finished(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        try:
            selected = dialog.save_finish(result)
        except GLib.Error as error:
            if not self._dialog_was_cancelled(error):
                self._show_toast(f"Could not choose the output file: {error.message}")
            return
        output_path = selected.get_path()
        if not output_path:
            self._show_toast("Choose a local output folder.")
            return
        if Path(output_path).suffix.lower() != ".mp4":
            output_path = str(Path(output_path).with_suffix(".mp4"))
        self._start_compression(output_path)

    def _start_compression(self, output_path: str) -> None:
        if self.source is None or self._runner is not None:
            return
        values = self._read_form()
        if values is None:
            self._update_form()
            return
        try:
            job = make_job(source=self.source, output_file=output_path, **values)
        except ValidationError as error:
            self._show_error("Check Compression Settings", str(error))
            return

        runner = FFmpegRunner(self._ffmpeg_toolchain)
        self._runner = runner
        self._set_running(True)

        def progress(percent: int) -> None:
            GLib.idle_add(self._set_progress, runner, percent)

        def work() -> None:
            result = runner.run(job, progress)
            GLib.idle_add(self._compression_finished, runner, result.status, result.message)

        self._worker_thread = threading.Thread(
            target=work, name="ffmpeg-compression", daemon=True
        )
        self._worker_thread.start()

    def _set_running(self, running: bool) -> None:
        self.settings_box.set_sensitive(not running)
        self.open_header_button.set_sensitive(not running)
        self.compress_button.set_visible(not running)
        self.compress_button.set_sensitive(not running and self._form_valid)
        self.cancel_button.set_visible(running)
        self.cancel_button.set_sensitive(running)
        self.cancel_button.set_label("Cancel Compression")
        self.progress_bar.set_visible(running)
        if running:
            self.progress_bar.set_fraction(0)
            self.progress_bar.set_text("0%")

    def _set_progress(self, runner: FFmpegRunner, percent: int) -> bool:
        if self._runner is runner:
            self.progress_bar.set_fraction(percent / 100)
            self.progress_bar.set_text(f"{percent}%")
        return GLib.SOURCE_REMOVE

    def _cancel_compression(self, _button: Gtk.Button | None = None) -> None:
        runner = self._runner
        if runner is None:
            return
        self.cancel_button.set_sensitive(False)
        self.cancel_button.set_label("Cancelling…")
        runner.stop()
        GLib.timeout_add_seconds(3, self._force_stop_if_current, runner)

    def _force_stop_if_current(self, runner: FFmpegRunner) -> bool:
        if self._runner is runner and runner.is_running:
            runner.force_stop()
        return GLib.SOURCE_REMOVE

    def _compression_finished(
        self, runner: FFmpegRunner, status: str, message: str
    ) -> bool:
        if self._runner is not runner:
            return GLib.SOURCE_REMOVE
        self._runner = None
        self._worker_thread = None
        self._set_running(False)
        self.progress_bar.set_visible(status == "success")
        if status == "success":
            self.progress_bar.set_fraction(1)
            self.progress_bar.set_text("Complete")
            self._show_toast("Compression complete")
        elif status == "stopped":
            self.progress_bar.set_visible(False)
            if not self._close_when_finished:
                self._show_toast("Compression cancelled")
        else:
            self.progress_bar.set_visible(False)
            self._show_error("Compression Failed", message or "FFmpeg could not compress the video.")

        if self._close_when_finished:
            self._close_when_finished = False
            self.destroy()
        return GLib.SOURCE_REMOVE

    def _show_toast(self, message: str) -> None:
        self.toast_overlay.add_toast(Adw.Toast.new(message))

    def _show_error(self, heading: str, body: str) -> None:
        dialog = Adw.AlertDialog.new(heading, body)
        dialog.add_response("close", "Close")
        dialog.set_close_response("close")
        dialog.set_default_response("close")
        dialog.present(self)

    def _on_close_request(self, _window: Adw.ApplicationWindow) -> bool:
        if self._ffmpeg_state == "installing":
            self._show_toast("Wait for the FFmpeg installation to finish.")
            return True
        if self._runner is None:
            return False
        if self._close_dialog is not None:
            return True

        dialog = Adw.AlertDialog.new(
            "Stop Compression?",
            "Closing the application will stop the current compression.",
        )
        dialog.add_response("continue", "Continue Compressing")
        dialog.add_response("stop", "Stop and Close")
        dialog.set_close_response("continue")
        dialog.set_default_response("continue")
        dialog.set_response_appearance("stop", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", self._close_response)
        self._close_dialog = dialog
        dialog.present(self)
        return True

    def _close_response(self, _dialog: Adw.AlertDialog, response: str) -> None:
        self._close_dialog = None
        if response == "stop":
            self._close_when_finished = True
            self._cancel_compression()


class JoemtVideoCompressorApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id=APPLICATION_ID,
            flags=Gio.ApplicationFlags.HANDLES_OPEN,
        )

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        self._add_action("open", self._open_action, ["<Control>o"])
        self._add_action("about", self._about_action)
        self._add_action("quit", self._quit_action, ["<Control>q"])
        self.set_accels_for_action("window.close", ["<Control>w"])

    def _add_action(
        self,
        name: str,
        callback: object,
        shortcuts: list[str] | None = None,
    ) -> None:
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        if shortcuts:
            self.set_accels_for_action(f"app.{name}", shortcuts)

    def do_activate(self) -> None:
        window = self.props.active_window
        if window is None:
            window = JoemtVideoCompressorWindow(self)
        window.present()

    def do_open(self, files: list[Gio.File], _n_files: int, _hint: str) -> None:
        self.activate()
        window = self.props.active_window
        if isinstance(window, JoemtVideoCompressorWindow) and files:
            path = files[0].get_path()
            if path:
                window.load_file(path)

    def _open_action(self, _action: Gio.SimpleAction, _parameter: object) -> None:
        self.activate()
        window = self.props.active_window
        if isinstance(window, JoemtVideoCompressorWindow):
            window.open_file_dialog()

    def _about_action(self, _action: Gio.SimpleAction, _parameter: object) -> None:
        self.activate()
        window = self.props.active_window
        dialog = Adw.AboutDialog.new()
        dialog.set_application_name(APPLICATION_NAME)
        dialog.set_application_icon(APPLICATION_ID)
        dialog.set_version(VERSION)
        dialog.set_developer_name("Joe")
        dialog.set_developers(["Joe"])
        dialog.set_license_type(Gtk.License.GPL_3_0)
        dialog.set_website("https://github.com/Joedotmt/Qt-Video-Compressor")
        dialog.set_issue_url("https://github.com/Joedotmt/Qt-Video-Compressor/issues")
        dialog.set_comments("Compress videos to a chosen target size.")
        dialog.present(window)

    def _quit_action(self, _action: Gio.SimpleAction, _parameter: object) -> None:
        window = self.props.active_window
        if window is not None:
            window.close()
        else:
            self.quit()


def main(argv: list[str] | None = None) -> int:
    arguments = list(argv if argv is not None else sys.argv)
    smoke_test = "--smoke-test" in arguments
    if smoke_test:
        arguments.remove("--smoke-test")
    application = JoemtVideoCompressorApplication()
    if smoke_test:
        GLib.timeout_add(1500, lambda: application.quit() or GLib.SOURCE_REMOVE)
    return application.run(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
