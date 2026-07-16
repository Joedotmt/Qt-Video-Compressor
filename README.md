<div align="center">
  <img src="data/icons/io.github.Joedotmt.VideoCompressor.svg" alt="Video Compressor icon" width="128" />
</div>

# Video Compressor

Video Compressor is a GNOME application for compressing a video to an
approximate target file size. It is built with Python, GTK 4, libadwaita, and
FFmpeg.

The interface follows the GNOME Human Interface Guidelines, adapts to light,
dark, and high-contrast system themes, and uses the native GNOME file chooser.

## Features

- Calculate video bitrate from a target size in MB.
- Enter arithmetic such as `1920/2` in numeric fields.
- Drop a video onto the window or open one with `Ctrl+O`.
- Resize video, change frame rate, include or remove audio, and alter playback
  speed.
- Encode H.264, H.265/HEVC, or AV1 video.
- Cancel an active compression without leaving a partial output file.
- Keep the interface responsive while FFprobe and FFmpeg run in the background.

Target-size compression uses a single bitrate-controlled encode with a small
safety margin. Final size is therefore approximate and depends on the selected
container and codecs.

## Run on Ubuntu

Ubuntu 24.04 or newer is recommended. Install the system GTK bindings and
FFmpeg:

```bash
sudo apt install python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 ffmpeg
python3 main.py
```

GTK and libadwaita are system libraries, so a virtual environment is usually
unnecessary. If you want one, allow it to use the system PyGObject package:

```bash
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python main.py
```

Installing `requirements.txt` with pip is intended for distributions where the
PyGObject build prerequisites are already installed. On Ubuntu, the apt command
above is simpler and more reliable.

## Build and run the Flatpak

Install Flatpak Builder and the GNOME 50 SDK, then build the included manifest:

```bash
sudo apt install flatpak flatpak-builder
flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
flatpak install flathub org.gnome.Platform//50 org.gnome.Sdk//50
flatpak-builder --user --install --force-clean build-dir io.github.Joedotmt.VideoCompressor.yml
flatpak run io.github.Joedotmt.VideoCompressor
```

The Flatpak uses file chooser portals, so it does not request unrestricted home
directory access.

## Tests

Run the toolkit-independent unit tests with:

```bash
python3 -m unittest discover -v
```

The test suite covers expressions, validation, target bitrate planning,
metadata parsing, FFmpeg command construction, speed filters, and progress
parsing. Continuous integration also validates a headless GTK startup, desktop
metadata, advertised encoders, and the Flatpak build.

## Project structure

- `main.py` contains the GTK 4/libadwaita application and main-thread UI state.
- `compressor.py` contains probing, validation, command planning, progress
  parsing, and cancellable FFmpeg execution without GUI dependencies.
- `data/` contains freedesktop desktop metadata, AppStream metadata, and icons.
- `io.github.Joedotmt.VideoCompressor.yml` builds the Flatpak package.

## Platform support

Linux with GTK 4.10 and libadwaita 1.5 or newer is the primary supported
platform. The former PyQt Windows executable is no longer built; producing a
reliable Windows package would require a separately maintained MSYS2 GTK stack.

## License

GNU General Public License v3.0.
