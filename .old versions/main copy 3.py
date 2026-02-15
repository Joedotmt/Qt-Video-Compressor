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
from PyQt6.QtGui import QGuiApplication

QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
    Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
)



AUDIO_BITRATE = 128_000  # 128 kbps


# -----------------------------
# Worker Thread
# -----------------------------
class FFmpegWorker(QThread):
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(str)

    def __init__(self, input_file, output_file, video_bitrate,
                 resolution, fps, preset, duration):
        super().__init__()
        self.input_file = input_file
        self.output_file = output_file
        self.video_bitrate = video_bitrate
        self.resolution = resolution
        self.fps = fps
        self.preset = preset
        self.duration = duration

    def run(self):

        vf_filters = []

        if self.resolution != "match":
            vf_filters.append(f"scale={self.resolution}")

        if self.fps != "match":
            vf_filters.append(f"fps={self.fps}")

        vf_string = ",".join(vf_filters) if vf_filters else None

        command = [
            "ffmpeg",
            "-y",
            "-i", self.input_file,
            "-c:v", "libx264",
            "-preset", self.preset,
            "-b:v", str(self.video_bitrate),
            "-c:a", "aac",
            "-b:a", str(AUDIO_BITRATE)
        ]

        if vf_string:
            command.extend(["-vf", vf_string])

        command.append(self.output_file)

        process = subprocess.Popen(
            command,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )

        for line in process.stderr:
            if "time=" in line:
                time_match = re.search(r"time=(\d+:\d+:\d+\.\d+)", line)
                if time_match:
                    seconds = self.time_to_seconds(time_match.group(1))
                    percent = int((seconds / self.duration) * 100)
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
        result = subprocess.run(command, stdout=subprocess.PIPE, text=True)
        try:
            return float(result.stdout)
        except:
            return 10.0 # fallback

    def __init__(self):
        super().__init__()

        self.setWindowTitle("Video Compressor")
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
                cursor: pointer;
            }
        """)
        self.label.mousePressEvent = lambda event: self.browse_for_video()
        layout.addWidget(self.label)

        # Create tabbed interface
        self.tabs = QTabWidget()

        # Tab 1: File Size
        tab1 = QWidget()
        tab1.setObjectName("InputPanel")
        tab1_layout = QVBoxLayout()
        self.size_input = QLineEdit()
        self.size_input.setPlaceholderText("Target Size (MB)")
        self.size_input.setMinimumHeight(40)
        tab1_layout.addWidget(self.size_input)
        tab1_layout.addStretch()
        tab1.setLayout(tab1_layout)
        self.tabs.addTab(tab1, "File Size")

        # Tab 2: Video Settings
        tab2 = QWidget()
        tab2.setObjectName("InputPanel")
        tab2_layout = QVBoxLayout()
        tab2_layout.setSpacing(10)

        resolution_layout = QHBoxLayout()
        self.width_input = QLineEdit()
        self.width_input.setPlaceholderText("Width")
        self.width_input.setMinimumHeight(40)
        resolution_layout.addWidget(self.width_input)

        self.height_input = QLineEdit()
        self.height_input.setPlaceholderText("Height")
        self.height_input.setMinimumHeight(40)
        resolution_layout.addWidget(self.height_input)
        tab2_layout.addLayout(resolution_layout)

        self.fps_input = QLineEdit()
        self.fps_input.setPlaceholderText("FPS")
        self.fps_input.setMinimumHeight(40)
        tab2_layout.addWidget(self.fps_input)

        self.source_button = QPushButton("Use Source Settings")
        self.source_button.setMinimumHeight(45)
        self.source_button.clicked.connect(self.load_source_settings)
        tab2_layout.addWidget(self.source_button)
        tab2_layout.addStretch()
        tab2.setLayout(tab2_layout)
        self.tabs.addTab(tab2, "Video Settings")

        # Tab 3: Encoder
        tab3 = QWidget()
        tab3.setObjectName("InputPanel")
        tab3_layout = QVBoxLayout()
        self.preset_box = QComboBox()
        self.preset_box.setMinimumHeight(40)
        self.preset_box.addItems(["ultrafast", "fast", "medium", "slow"])
        tab3_layout.addWidget(self.preset_box)
        tab3_layout.addStretch()
        tab3.setLayout(tab3_layout)
        self.tabs.addTab(tab3, "Encoder")

        layout.addWidget(self.tabs)

        # Progress
        self.progress = QProgressBar()
        self.progress.setMinimumHeight(35)
        layout.addWidget(self.progress)

        # Compress button
        self.button = QPushButton("Compress")
        self.button.setMinimumHeight(50)
        self.button.clicked.connect(self.start_compression)
        layout.addWidget(self.button)

        self.setLayout(layout)

        self.input_file = None
        self.disable_controls()

    def disable_controls(self):
        """Disable all controls"""
        self.size_input.setEnabled(False)
        self.width_input.setEnabled(False)
        self.height_input.setEnabled(False)
        self.fps_input.setEnabled(False)
        self.source_button.setEnabled(False)
        self.preset_box.setEnabled(False)
        self.button.setEnabled(False)

    def enable_controls(self):
        """Enable all controls"""
        self.size_input.setEnabled(True)
        self.width_input.setEnabled(True)
        self.height_input.setEnabled(True)
        self.fps_input.setEnabled(True)
        self.source_button.setEnabled(True)
        self.preset_box.setEnabled(True)
        self.button.setEnabled(True)

    def browse_for_video(self):
        """Open file dialog to select a video"""
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Video", "", "Video Files (*.mp4 *.avi *.mkv *.mov)")
        if file_path:
            self.input_file = file_path
            self.label.setText(os.path.basename(self.input_file))
            self.enable_controls()
            self.load_source_settings()

    # -------------------------
    # Drag & Drop
    # -------------------------
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()

    def dropEvent(self, event):
        self.input_file = event.mimeData().urls()[0].toLocalFile()
        self.label.setText(os.path.basename(self.input_file))
        self.enable_controls()
        self.load_source_settings()

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

        result = subprocess.run(command, stdout=subprocess.PIPE, text=True)
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

    # -------------------------
    # Compression Start
    # -------------------------
    def start_compression(self):
        if not self.input_file:
            QMessageBox.warning(self, "Error", "No video selected.")
            return

        try:
            target_mb = float(self.size_input.text())
            width = int(self.width_input.text())
            height = int(self.height_input.text())
            fps = float(self.fps_input.text())
        except:
            QMessageBox.warning(self, "Error", "Invalid numeric input.")
            return

        duration = self.get_duration(self.input_file)

        target_bits = target_mb * 1024 * 1024 * 8
        video_bitrate = (target_bits / duration) - AUDIO_BITRATE

        video_bitrate *= 0.97  # safety margin

        if video_bitrate < 100_000:
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
            duration
        )

        self.worker.progress_signal.connect(self.progress.setValue)
        self.worker.finished_signal.connect(
            lambda _: QMessageBox.information(self, "Done", "Compression Finished")
        )

        self.worker.start()



is_dark = False
if __name__ == "__main__":
    app = QApplication(sys.argv)
    is_dark = app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    window = VideoCompressor()
    window.show()
    sys.exit(app.exec())


