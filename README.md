<div align="center">
  <img src="https://raw.githubusercontent.com/Joedotmt/Qt-Video-Compressor/refs/heads/main/logo-dark.png" alt="Qt Video Compressor Logo" width="500" height="auto" />
</div>

# Qt Video Compressor (QtVC)

A user-friendly GUI to make video compression fast and easy like when trying to send a video with Discord's 10MB limit.
Just type in the size and it will compress to that size\
\
Made using Python, PyQt6, and FFmpeg

## Features

* **Target Size Compression:** Input your desired file size (in MB), and the app automatically calculates the necessary video bitrate.
* **Expressions in fields:** You can do math in any fields like for example `1920/2` in the width field to make the video half as wide
* **Simple Interface:** Simply drag your video file into the window to get started.
* **Multiple Codec Support:** * **H.264 (libx264):** Standard compatibility.
    * **H.265 (libx265):** Better compression efficiency.
    * **AV1 (libaom-av1):** Next-gen royalty-free codec.
* **Advanced Controls:**
    * **Resolution:** Resize width/height (auto-adjusts to even numbers).
    * **Framerate:** Change video FPS.
    * **Audio:** Adjust audio bitrate or strip audio entirely (Mute).
    * **Speed:** Speed up or slow down footage (handles audio pitch correction).
* **Quality Tuning:** Select presets (Ultrafast to Slow) and tuning profiles (Film, Animation, Grain).

### FFmpeg Installation

The application requires FFmpeg to function.

* **Windows:** `winget install FFmpeg` or `choco install ffmpeg`
* **macOS:** `brew install ffmpeg`
* **Linux (Ubuntu/Debian):** `sudo apt-get install ffmpeg`
* **Linux (Arch):** `sudo pacman -S ffmpeg`

## Run from source

Python 3.10 or newer and FFmpeg are required. Keep the project's Python
packages isolated in a local virtual environment:

### macOS and Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --requirement requirements.txt
python main.py
```

### Windows PowerShell

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --requirement requirements.txt
python main.py
```

Run `deactivate` when you are finished. The `.venv` directory is local-only
and intentionally excluded from version control.

## Build a desktop executable

Activate the virtual environment, then install the additional build tooling
and run the shared PyInstaller specification:

```bash
python -m pip install --requirement requirements-build.txt
python -m PyInstaller --noconfirm --clean "Qt Video Compressor.spec"
```

The generated application is written to `dist/`. The same command is used on
Windows and Linux; platform packages must be built on their target platform.

## Automated builds

Every push triggers the GitHub Actions workflow in `.github/workflows/build.yml`.
When both jobs finish, the workflow run contains a Windows `.exe` artifact and a
Linux `.AppImage` artifact. You can also start the workflow manually from the
repository's **Actions** tab.

## 🖥️ Usage

1.  Run the application
2.  **Drag and drop** a video file onto the dashed area.
3.  **File Size Tab:** Enter your target size in MB. The bitrate is calculated automatically.
4.  (Optional) Adjust settings in the **Video**, **Audio**, **Fun** (Speed), or **Encoder** tabs.
5.  Click **Compress**.
6.  Select a save location and wait for the progress bar to finish.

## ⚙️ Technical Details

* **Bitrate Calculation:** Uses the formula `(TargetSize / Duration) - AudioBitrate` with a 3% safety margin to ensure the file stays under the limit.
* **Threading:** Uses `QThread` to run FFmpeg processes asynchronously, preventing the GUI from freezing during compression.
* **Input Sanitization:** Automatically ensures dimensions are divisible by 2 (required by many codecs) and validates mathematical expressions in input fields.

## 🤝 PLEASE contribute

Contributions are welcome! Please feel free to submit a Pull Request.

## 📄 License
GNU General Public License v3.0
