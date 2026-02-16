import sys
import os
import subprocess
import re
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QLineEdit, QProgressBar, QFileDialog,
    QMessageBox, QCheckBox, QTabWidget
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

AUDIO_BITRATE = 128_000  # 128 kbps

# Windows-specific: suppress console windows
SUBPROCESS_FLAGS = 0

if sys.platform == "win32":
    SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW


# Helper function to check if FFmpeg is installed
def check_ffmpeg_installed():
    """Check if FFmpeg and FFprobe are installed"""
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5, creationflags=SUBPROCESS_FLAGS)
        subprocess.run(["ffprobe", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5, creationflags=SUBPROCESS_FLAGS)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def show_ffmpeg_installation_dialog():
    """Show OS-specific installation instructions for FFmpeg"""
    if sys.platform == "win32":
        message = (
            "FFmpeg is not installed on your system or not included in PATH.\n\n"
            "Please install FFmpeg using one of these methods:\n\n"
            "  • Recommended: winget install FFmpeg\n"
            "  • Using Chocolatey: choco install ffmpeg\n"
            "  • Manual download: https://ffmpeg.org/download.html\n\n"
            "After installation, please restart this application."
        )
    elif sys.platform == "darwin":  # macOS
        message = (
            "FFmpeg is not installed on your system.\n\n"
            "Please install FFmpeg using Homebrew:\n\n"
            "  • brew install ffmpeg\n\n"
            "If you don't have Homebrew installed, visit: https://brew.sh\n\n"
            "After installation, please restart this application."
        )
    else:  # Linux and other Unix-like systems
        message = (
            "FFmpeg is not installed on your system.\n\n"
            "Please install FFmpeg using your package manager:\n\n"
            "Ubuntu/Debian:\n"
            "  • sudo apt-get install ffmpeg\n\n"
            "Fedora/RHEL:\n"
            "  • sudo dnf install ffmpeg\n\n"
            "Arch:\n"
            "  • sudo pacman -S ffmpeg\n\n"
            "After installation, please restart this application."
        )
    QMessageBox.critical(None, "FFmpeg Not Found", message)


def safe_eval_expression(expr_str):
    """Safely evaluate mathematical expressions like '720/2' or '1920-100'"""
    try:
        expr_str = str(expr_str).strip()
        if not expr_str:
            return None
        # Only allow digits, basic operators, and parentheses
        if not all(c in '0123456789+-*/.() ' for c in expr_str):
            return None
        result = eval(expr_str)
        return result
    except:
        return None


def ensure_even(value):
    """Round down to nearest even number (required by libx264)"""
    if value is None:
        return None
    try:
        val = int(value)
        return val if val % 2 == 0 else val - 1
    except:
        return None


# -----------------------------
# Worker Thread
# -----------------------------
class FFmpegCheckWorker(QThread):
    check_complete = pyqtSignal(bool)

    def run(self):
        result = check_ffmpeg_installed()
        self.check_complete.emit(result)


class FFmpegWorker(QThread):
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(str)

    def __init__(self, input_file, output_file, video_bitrate,
             resolution, fps, preset, duration, audio_bitrate=128_000, mute_audio=False,
             tune=None, speed=1.0, codec="libx264"):
        super().__init__()
        self.input_file = input_file
        self.output_file = output_file
        self.video_bitrate = video_bitrate
        self.resolution = resolution
        self.fps = fps
        self.preset = preset
        self.duration = duration
        self.audio_bitrate = audio_bitrate
        self.mute_audio = mute_audio
        self.tune = tune
        self.speed = speed
        self.codec = codec

    def run(self):

        vf_filters = []

        if self.resolution != "match":
            vf_filters.append(f"scale={self.resolution}")

        if self.fps != "match":
            vf_filters.append(f"fps={self.fps}")

        # Add speed control via setpts filter
        if self.speed != 1.0:
            vf_filters.append(f"setpts=PTS/{self.speed}")

        vf_string = ",".join(vf_filters) if vf_filters else None

        # Audio filter for speed control
        af_filters = []
        if self.speed != 1.0 and not self.mute_audio:
            af_filters.append(f"atempo={self.speed}")
        af_string = ",".join(af_filters) if af_filters else None

        command = [
            "ffmpeg",
            "-y",
            "-i", self.input_file,
            "-c:v", self.codec,
            "-preset", self.preset,
            "-b:v", str(self.video_bitrate),
        ]

        if self.tune and self.codec != "libaom-av1":  # AV1 doesn't use -tune
            command.extend(["-tune", self.tune])

        if self.mute_audio:
            command.extend(["-an"])
        else:
            command.extend(["-c:a", "aac", "-b:a", str(self.audio_bitrate)])

        if vf_string:
            command.extend(["-vf", vf_string])

        if af_string:
            command.extend(["-af", af_string])

        command.append(self.output_file)

        # Print the command for debugging
        print("FFmpeg Command:")
        print(" ".join(command))
        print()

        process = subprocess.Popen(
            command,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            creationflags=SUBPROCESS_FLAGS
        )

        # Adjust duration for speed when calculating progress
        adjusted_duration = self.duration / self.speed

        for line in process.stderr:
            if "time=" in line:
                time_match = re.search(r"time=(\d+:\d+:\d+\.\d+)", line)
                if time_match:
                    seconds = self.time_to_seconds(time_match.group(1))
                    percent = int((seconds / adjusted_duration) * 100)
                    self.progress_signal.emit(min(percent, 100))

        process.wait()
        self.finished_signal.emit("Done")

    def time_to_seconds(self, time_str):
        h, m, s = time_str.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)

# -----------------------------
# GUI
# -----------------------------
class VideoCompressor(QWidget):
    @staticmethod
    def get_duration(input_file):
        command = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", input_file
        ]
        result = subprocess.run(command, stdout=subprocess.PIPE, text=True, creationflags=SUBPROCESS_FLAGS, timeout=10)
        try:
            return float(result.stdout)
        except:
            return 10.0 # fallback

    @staticmethod
    def get_source_audio_bitrate(input_file):
        """Extract audio bitrate from source video"""
        command = [
            "ffprobe", "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream=bit_rate",
            "-of", "default=noprint_wrappers=1:nokey=1", input_file
        ]
        result = subprocess.run(command, stdout=subprocess.PIPE, text=True, creationflags=SUBPROCESS_FLAGS, timeout=10)
        try:
            bitrate = int(result.stdout.strip())
            return bitrate // 1000  # Convert to kbps
        except:
            return 128  # fallback

    @staticmethod
    def get_source_file_size(input_file):
        """Get source file size in MB"""
        try:
            file_size_bytes = os.path.getsize(input_file)
            file_size_mb = file_size_bytes / (1024 * 1024)
            return file_size_mb
        except:
            return None

    def __init__(self):
        super().__init__()

        self.setWindowTitle("Qt Video Compressor")
        self.resize(750, 700)
        self.setMinimumSize(650, 600)
        self.setAcceptDrops(True)

        font = self.font()
        font.setPointSize(11)
        self.setFont(font)

        self.setObjectName("MainWindow")

        # Add stylesheet for disabled inputs
        self.setStyleSheet(f"""
            #MainWindow {{
                background-color: {'black' if is_dark else 'white'};
            }}
            QLineEdit:disabled, QComboBox:disabled, QPushButton:disabled {{
                border: 1px solid {'#1f1f1f' if is_dark else '#cccccc'};
                border-radius: 5px;
            }}
            QLineEdit:disabled {{
                padding: 5px;
            }}
            QPushButton:disabled {{
                background-color: {'#2D2D2D' if is_dark else '#e0e0e0'};
            }}
                           

            /* Make the specific panel dark */
            #InputPanel {{
                background-color: {'#111111' if is_dark else '#f0f0f0'};
                border-radius: 5px;
            }}

            /* Force text inside this panel to be white (for the labels) */
            QWidget#InputPanel QLabel {{
                color: {"white" if is_dark else "black"};
            }}
        """)

        layout = QVBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(25, 25, 25, 25)

        # Drag area
        self.label = QLabel("Drag & Drop Video")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setMinimumHeight(130)
        self.label.setStyleSheet("""
            QLabel {
                border: 2px dashed gray;
                border-radius: 10px;
                padding: 25px;
                font-size: 16px;
            }
        """)
        self.label.mousePressEvent = lambda event: self.browse_for_video()
        layout.addWidget(self.label)

        # Create tabbed interface (will be populated on demand)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.tabs.hide()

        # Progress
        self.progress = QProgressBar()
        self.progress.setMinimumHeight(35)
        layout.addWidget(self.progress)
        self.progress.hide()

        # Compress button
        self.button = QPushButton("Compress")
        self.button.setMinimumHeight(50)
        self.button.clicked.connect(self.start_compression)
        layout.addWidget(self.button)
        self.button.hide()

        self.setLayout(layout)

        self.input_file = None
        self.tabs_initialized = False  # Track if tabs have been created

        # --- new cached state ---
        self.duration = None                           # cache ffprobe duration (call once)
        self._source_audio_bitrate_kbps = None         # cache source audio bitrate (kbps)
        self._last_estimate_key = None                 # avoid redundant estimate work

        # Start FFmpeg check in background (non-blocking)
        self.ffmpeg_check = FFmpegCheckWorker()
        self.ffmpeg_check.check_complete.connect(self.on_ffmpeg_check_complete)
        self.ffmpeg_check.start()

    def initialize_tabs(self):
        """Create and setup all tabs (called on first video load)"""
        if self.tabs_initialized:
            return

        # Tab 1: File Size
        tab1 = QWidget()
        tab1.setObjectName("InputPanel")
        tab1_layout = QVBoxLayout()

        # Size input with label
        size_layout = QHBoxLayout()
        self.size_input = QLineEdit()
        self.size_input.setPlaceholderText("Enter target size")
        self.size_input.setMinimumHeight(40)
        size_layout.addWidget(self.size_input)
        size_unit = QLabel("MB")
        size_unit.setMinimumWidth(35)
        size_unit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        size_layout.addWidget(size_unit, 0, Qt.AlignmentFlag.AlignRight)
        tab1_layout.addLayout(size_layout)

        # Bitrate display with label
        bit_layout = QHBoxLayout()
        self.vid_bit_input = QLineEdit()
        self.vid_bit_input.setPlaceholderText("Calculated")
        self.vid_bit_input.setReadOnly(True)
        self.vid_bit_input.setDisabled(True)
        self.vid_bit_input.setMinimumHeight(40)
        bit_layout.addWidget(self.vid_bit_input)
        bit_unit = QLabel("kbps")
        bit_unit.setMinimumWidth(35)
        bit_unit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bit_layout.addWidget(bit_unit, 0, Qt.AlignmentFlag.AlignRight)
        tab1_layout.addLayout(bit_layout)

        self.size_source_button = QPushButton("Match Source")
        self.size_source_button.setMinimumHeight(45)
        self.size_source_button.clicked.connect(self.load_source_file_size)
        tab1_layout.addWidget(self.size_source_button)

        tab1_layout.addStretch()
        tab1.setLayout(tab1_layout)
        self.tabs.addTab(tab1, "File Size")

        # Tab 2: Video Settings
        tab2 = QWidget()
        tab2.setObjectName("InputPanel")
        tab2_layout = QVBoxLayout()
        tab2_layout.setSpacing(10)

        # Resolution with labels
        resolution_layout = QHBoxLayout()
        self.width_input = QLineEdit()
        self.width_input.setPlaceholderText("Width")
        self.width_input.setMinimumHeight(40)
        resolution_layout.addWidget(self.width_input)
        width_unit = QLabel("px")
        width_unit.setMinimumWidth(25)
        width_unit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        resolution_layout.addWidget(width_unit, 0, Qt.AlignmentFlag.AlignRight)

        self.height_input = QLineEdit()
        self.height_input.setPlaceholderText("Height")
        self.height_input.setMinimumHeight(40)
        resolution_layout.addWidget(self.height_input)
        height_unit = QLabel("px")
        height_unit.setMinimumWidth(30)
        height_unit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        resolution_layout.addWidget(height_unit, 0, Qt.AlignmentFlag.AlignRight)
        tab2_layout.addLayout(resolution_layout)

        # FPS with label
        fps_layout = QHBoxLayout()
        self.fps_input = QLineEdit()
        self.fps_input.setPlaceholderText("FPS")
        self.fps_input.setMinimumHeight(40)
        fps_layout.addWidget(self.fps_input)
        fps_unit = QLabel("fps")
        fps_unit.setMinimumWidth(30)
        fps_unit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fps_layout.addWidget(fps_unit, 0, Qt.AlignmentFlag.AlignRight)
        tab2_layout.addLayout(fps_layout)

        # keep the tiny preview updated when inputs change
        self.width_input.textChanged.connect(self.update_video_info_label)
        self.height_input.textChanged.connect(self.update_video_info_label)
        self.fps_input.textChanged.connect(self.update_video_info_label)

        self.source_button = QPushButton("Use Source Settings")
        self.source_button.setMinimumHeight(45)
        self.source_button.clicked.connect(self.load_source_settings)
        tab2_layout.addWidget(self.source_button)

        # tiny size/fps preview (bottom of Video tab)
        self.video_info_label = QLabel("")
        self.video_info_label.setMinimumHeight(14)
        self.video_info_label.setStyleSheet(
            f"font-size:10px; color: {'#CCCCCC' if is_dark else '#666666'};"
        )
        tab2_layout.addWidget(self.video_info_label)

        tab2_layout.addStretch()
        tab2.setLayout(tab2_layout)
        self.tabs.addTab(tab2, "Video")

        # Tab 4: Audio
        tab4 = QWidget()
        tab4.setObjectName("InputPanel")
        tab4_layout = QVBoxLayout()
        tab4_layout.setSpacing(10)

        self.mute_audio = QCheckBox("Mute Audio")
        self.mute_audio.setMinimumHeight(40)
        tab4_layout.addWidget(self.mute_audio)

        # Audio bitrate with label
        audio_layout = QHBoxLayout()
        self.audio_bitrate_input = QLineEdit()
        self.audio_bitrate_input.setPlaceholderText("Enter audio bitrate")
        self.audio_bitrate_input.setMinimumHeight(40)
        self.audio_bitrate_input.setText("")
        audio_layout.addWidget(self.audio_bitrate_input)
        audio_unit = QLabel("kbps")
        audio_unit.setMinimumWidth(35)
        audio_unit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        audio_layout.addWidget(audio_unit, 0, Qt.AlignmentFlag.AlignRight)
        tab4_layout.addLayout(audio_layout)

        self.audio_source_button = QPushButton("Match Source")
        self.audio_source_button.setMinimumHeight(45)
        self.audio_source_button.clicked.connect(self.load_source_audio_bitrate)
        tab4_layout.addWidget(self.audio_source_button)
        tab4_layout.addStretch()
        tab4.setLayout(tab4_layout)
        self.tabs.addTab(tab4, "Audio")

        # Tab 5: Fun
        tab5 = QWidget()
        tab5.setObjectName("InputPanel")
        tab5_layout = QVBoxLayout()
        tab5_layout.setSpacing(10)

        # Speed with label
        speed_layout = QHBoxLayout()
        self.speed_input = QLineEdit()
        self.speed_input.setPlaceholderText("1.0")
        self.speed_input.setMinimumHeight(40)
        speed_layout.addWidget(self.speed_input)
        speed_unit = QLabel("x speed")
        speed_unit.setMinimumWidth(25)
        speed_unit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        speed_layout.addWidget(speed_unit, 0, Qt.AlignmentFlag.AlignRight)
        tab5_layout.addLayout(speed_layout)

        tab5_layout.addStretch()
        tab5.setLayout(tab5_layout)
        self.tabs.addTab(tab5, "Fun")

        # Tab 3: Encoder
        tab3 = QWidget()
        tab3.setObjectName("InputPanel")
        tab3_layout = QVBoxLayout()
        tab3_layout.setSpacing(10)

        self.codec_box = QComboBox()
        self.codec_box.setMinimumHeight(40)
        self.codec_box.addItems(["H.264 (libx264)", "H.265 (libx265)", "AV1 (libaom-av1)"])
        self.codec_box.currentIndexChanged.connect(self.update_encoder_options)
        tab3_layout.addWidget(self.codec_box)

        # Add a label for clarity
        codec_label = QLabel("Video Codec")
        tab3_layout.insertWidget(0, codec_label)

        self.preset_box = QComboBox()
        self.preset_box.setMinimumHeight(40)
        self.preset_box.addItems(["ultrafast", "fast", "medium", "slow"])
        tab3_layout.addWidget(self.preset_box)

        self.tune_box = QComboBox()
        self.tune_box.setMinimumHeight(40)
        self.tune_box.addItems(["None", "film", "animation", "grain", "stillimage"])
        tab3_layout.addWidget(self.tune_box)

        tab3_layout.addStretch()
        tab3.setLayout(tab3_layout)
        self.tabs.addTab(tab3, "Encoder")

        # Setup signal connections for input fields
        self.size_input.textChanged.connect(self.update_estimated_bitrate)
        self.audio_bitrate_input.textChanged.connect(self.update_estimated_bitrate)
        self.mute_audio.stateChanged.connect(lambda _: self.update_estimated_bitrate())

        self.tabs_initialized = True

    def on_ffmpeg_check_complete(self, is_installed):
        """Handle FFmpeg check result"""
        if not is_installed:
            show_ffmpeg_installation_dialog()
            sys.exit(1)

    def show_compression_controls(self):
        """Show tabs, progress bar, and compress button"""
        self.initialize_tabs()  # Create tabs on first video load
        self.tabs.show()
        self.progress.show()
        self.button.show()

    def browse_for_video(self):
        """Open file dialog to select a video"""
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Video", "", "Video Files (*.mp4 *.avi *.mkv *.mov)")
        if file_path:
            self.input_file = file_path
            self.label.setText(os.path.basename(self.input_file))
            self.show_compression_controls()

            # get duration once and cache it (avoid repeated ffprobe)
            self.duration = self.get_duration(self.input_file)

            self.load_source_settings()
            self.load_source_file_size()
            self.update_estimated_bitrate()

    # -------------------------
    # Drag & Drop
    # -------------------------
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()

    def dropEvent(self, event):
        self.input_file = event.mimeData().urls()[0].toLocalFile()
        self.label.setText(os.path.basename(self.input_file))
        self.show_compression_controls()

        # cache duration once
        self.duration = self.get_duration(self.input_file)

        self.load_source_settings()
        self.load_source_file_size()
        self.update_estimated_bitrate()

    # -------------------------
    # Load Source Settings
    # -------------------------
    def load_source_settings(self):
        if not self.input_file:
            QMessageBox.warning(self, "Error", "Load a video first.")
            return

        command = [
            "ffprobe",
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,r_frame_rate",
            "-of", "default=noprint_wrappers=1",
            self.input_file
        ]

        result = subprocess.run(command, stdout=subprocess.PIPE, text=True, creationflags=SUBPROCESS_FLAGS, timeout=10)
        output = result.stdout

        width = re.search(r"width=(\d+)", output)
        height = re.search(r"height=(\d+)", output)
        fps = re.search(r"r_frame_rate=(\d+)/(\d+)", output)

        if width and height:
            self.width_input.setText(width.group(1))
            self.height_input.setText(height.group(1))

        if fps:
            numerator = int(fps.group(1))
            denominator = int(fps.group(2))
            real_fps = round(numerator / denominator, 2)
            self.fps_input.setText(str(real_fps))

        self.load_source_audio_bitrate()

    def load_source_audio_bitrate(self):
        """Load audio bitrate from source video"""
        if not self.input_file:
            QMessageBox.warning(self, "Error", "Load a video first.")
            return

        bitrate = self.get_source_audio_bitrate(self.input_file)
        self._source_audio_bitrate_kbps = bitrate           # cache it (kbps)
        self.audio_bitrate_input.setText(str(bitrate))
        self.update_estimated_bitrate()

    def load_source_file_size(self):
        """Load file size from source video"""
        if not self.input_file:
            QMessageBox.warning(self, "Error", "Load a video first.")
            return

        file_size_mb = self.get_source_file_size(self.input_file)
        if file_size_mb is not None:
            self.size_input.setText(f"{file_size_mb:.2f}")
            self.update_estimated_bitrate()
        else:
            QMessageBox.warning(self, "Error", "Could not read file size.")

    # -------------------------
    # Compression Start
    # -------------------------
    def start_compression(self): 
        if not self.input_file:
            QMessageBox.warning(self, "Error", "No video selected.")      
            return

        try:
            target_mb = safe_eval_expression(self.size_input.text())
            if target_mb is None:
                raise ValueError("Invalid target size")
            
            width = ensure_even(safe_eval_expression(self.width_input.text()))
            if width is None:
                raise ValueError("Invalid width")
            
            height = ensure_even(safe_eval_expression(self.height_input.text()))
            if height is None:
                raise ValueError("Invalid height")
            
            fps = safe_eval_expression(self.fps_input.text())
            if fps is None:
                raise ValueError("Invalid FPS")
            
            audio_bitrate_expr = safe_eval_expression(self.audio_bitrate_input.text()) if not self.mute_audio.isChecked() else 0
            if self.audio_bitrate_input.text().strip() and audio_bitrate_expr is None and not self.mute_audio.isChecked():
                raise ValueError("Invalid audio bitrate")
            audio_bitrate = int(audio_bitrate_expr * 1000) if audio_bitrate_expr else 0

            codec_text = self.codec_box.currentText()
            if "H.264" in codec_text:
                codec = "libx264"
            elif "H.265" in codec_text:
                codec = "libx265"
            elif "AV1" in codec_text:
                codec = "libaom-av1"
            else:
                codec = "libx264"

            # Get tune value
            tune = self.tune_box.currentText()
            if tune == "None":
                tune = None

            # Get speed value
            speed_text = self.speed_input.text().strip()
            if speed_text:
                speed = safe_eval_expression(speed_text)
                if speed is None or speed <= 0:
                    raise ValueError("Invalid speed value")
            else:
                speed = 1.0
        except:
            QMessageBox.warning(self, "Error", "Invalid numeric input.")
            return

        # use cached duration if available; call ffprobe only if we must
        duration = self.duration if self.duration is not None else self.get_duration(self.input_file)
        self.duration = duration

        # Calculate video bitrate
        target_bits = target_mb * 1024 * 1024 * 8
        video_bitrate = (target_bits / duration) - audio_bitrate
        video_bitrate *= 0.97  # safety margin

        if video_bitrate < 1:
            QMessageBox.warning(self, "Error", "Target size too small.")
            return

        suggested_name = os.path.splitext(os.path.basename(self.input_file))[0] + "_c.mp4"
        output = QFileDialog.getSaveFileName(self, "Save File", suggested_name, "MP4 Files (*.mp4)")[0]
        if not output:
            return

        resolution = f"{width}:{height}"
        self.worker = FFmpegWorker(
            self.input_file,
            output,
            int(video_bitrate),
            resolution,
            fps,
            self.preset_box.currentText(),
            duration,
            audio_bitrate,
            self.mute_audio.isChecked(),
            tune,
            speed,
            codec  # Add this parameter
        )

        self.worker.progress_signal.connect(self.progress.setValue)
        self.worker.finished_signal.connect(
            lambda _: QMessageBox.information(self, "Done", "Compression Finished")
        )

        self.worker.start()

    # --- NEW: update the Estimated Bitrate field while typing (uses cached duration/audio) ---
    def update_estimated_bitrate(self, _=None):
        """Compute final video bitrate (kbps) using cached duration + current audio settings.
        Does not call ffprobe repeatedly; uses cached values and skips if inputs didn't change."""
        size_text = self.size_input.text().strip()
        audio_text = self.audio_bitrate_input.text().strip()
        muted = self.mute_audio.isChecked()

        key = (size_text, audio_text, muted, self.duration)
        if key == self._last_estimate_key:
            return
        self._last_estimate_key = key

        # parse size
        target_mb = safe_eval_expression(size_text)
        if target_mb is None:
            self.vid_bit_input.setText("")
            return

        # ensure we have duration (call once if still missing)
        if self.duration is None and self.input_file:
            self.duration = self.get_duration(self.input_file)

        if not self.duration or self.duration <= 0:
            self.vid_bit_input.setText("")
            return

        # determine audio bitrate (bps)
        if muted:
            audio_bps = 0
        else:
            audio_val = safe_eval_expression(audio_text)
            if audio_val is not None:
                audio_bps = int(audio_val * 1000)
            elif self._source_audio_bitrate_kbps:
                audio_bps = self._source_audio_bitrate_kbps * 1000
            else:
                audio_bps = AUDIO_BITRATE

        # compute video bitrate (bps) same formula used in start_compression
        target_bits = target_mb * 1024 * 1024 * 8
        video_bps = (target_bits / self.duration) - audio_bps
        video_bps *= 0.97  # safety margin

        if video_bps <= 0:
            self.vid_bit_input.setText("0")
            return

        # show kbps in the Estimated Bitrate field
        video_kbps = int(video_bps / 1000)
        self.vid_bit_input.setText(str(video_kbps))


        # new: update the tiny "WxH @ FPS" label
        self.update_video_info_label()

    def update_video_info_label(self, _=None):
        """Update the tiny video size + FPS preview label."""
        w = safe_eval_expression(self.width_input.text().strip())
        h = safe_eval_expression(self.height_input.text().strip())
        fps = safe_eval_expression(self.fps_input.text().strip())

        # Apply ensure_even to dimensions
        w = ensure_even(w)
        h = ensure_even(h)

        parts = []
        if w is not None and h is not None:
            try:
                parts.append(f"{int(w)}x{int(h)}")
            except:
                parts.append(f"{w}x{h}")

        if fps is not None:
            if isinstance(fps, float) and fps.is_integer():
                fps_str = str(int(fps))
            else:
                fps_str = ("{:.2f}".format(fps)).rstrip('0').rstrip('.')
            parts.append(f"@ {fps_str}")

        self.video_info_label.setText(" ".join(parts))

    def update_encoder_options(self):
        """Update preset and tune options based on selected codec"""
        codec_text = self.codec_box.currentText()
        
        self.preset_box.clear()
        self.tune_box.clear()
        
        if "H.264" in codec_text:
            self.preset_box.addItems(["ultrafast", "fast", "medium", "slow"])
            self.tune_box.addItems(["None", "film", "animation", "grain", "stillimage"])
        elif "H.265" in codec_text:
            self.preset_box.addItems(["ultrafast", "fast", "medium", "slow"])
            self.tune_box.addItems(["None", "film", "animation", "grain", "stillimage"])
        elif "AV1" in codec_text:
            self.preset_box.addItems(["0", "1", "2", "3", "4", "5", "6"])  # 0=best quality, 6=fastest
            self.tune_box.addItems(["None"])  # AV1 doesn't have tune options
            self.tune_box.setEnabled(False)

is_dark = False
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    # Detect dark mode before creating window
    is_dark = app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    
    window = VideoCompressor()

    window.show()

    sys.exit(app.exec())