"""Toolkit-independent video probing and FFmpeg execution helpers."""

from __future__ import annotations

import ast
import errno
import json
import math
import os
from dataclasses import dataclass, replace
from fractions import Fraction
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
from typing import Callable


DEFAULT_AUDIO_BITRATE_KBPS = 128
TARGET_SAFETY_MARGIN = 0.97
VIDEO_CODECS = {
    "H.264 (Compatibility)": "libx264",
    "H.265 (Smaller files)": "libx265",
    "AV1 (Smallest files)": "libaom-av1",
}

SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
_IS_WINDOWS = os.name == "nt"
_TIME_PATTERN = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")


class CompressorError(RuntimeError):
    """Base class for errors that can be presented to the user."""


class ProbeError(CompressorError):
    """Raised when FFprobe cannot read a usable video stream."""


class ValidationError(CompressorError):
    """Raised when compression settings are not usable."""


@dataclass(frozen=True)
class FFmpegToolchain:
    """Absolute paths to a validated FFmpeg and FFprobe toolchain."""

    ffmpeg: str
    ffprobe: str


@dataclass(frozen=True)
class SourceInfo:
    path: str
    duration: float
    width: int
    height: int
    fps: float
    size_mb: float
    audio_bitrate_kbps: int | None

    @property
    def has_audio(self) -> bool:
        return self.audio_bitrate_kbps is not None


@dataclass(frozen=True)
class CompressionJob:
    input_file: str
    output_file: str
    video_bitrate_bps: int
    width: int
    height: int
    fps: float
    preset: str
    duration: float
    audio_bitrate_bps: int = DEFAULT_AUDIO_BITRATE_KBPS * 1000
    mute_audio: bool = False
    tune: str | None = None
    speed: float = 1.0
    codec: str = "libx264"

    @property
    def output_duration(self) -> float:
        return self.duration / self.speed


@dataclass(frozen=True)
class RunResult:
    status: str
    message: str = ""


def _toolchain_from_directory(directory: str | os.PathLike[str]) -> FFmpegToolchain:
    suffix = ".exe" if _IS_WINDOWS else ""
    directory_path = Path(directory).expanduser().resolve()
    return FFmpegToolchain(
        ffmpeg=str(directory_path / f"ffmpeg{suffix}"),
        ffprobe=str(directory_path / f"ffprobe{suffix}"),
    )


def _windows_winget_link_directories() -> list[Path]:
    directories = []
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        directories.append(Path(local_app_data, "Microsoft", "WinGet", "Links"))
    program_files = os.environ.get("ProgramFiles")
    if program_files:
        directories.append(Path(program_files, "WinGet", "Links"))
    return directories


def _toolchain_can_run(toolchain: FFmpegToolchain) -> bool:
    for executable in (toolchain.ffmpeg, toolchain.ffprobe):
        try:
            completed = subprocess.run(
                [executable, "-version"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                creationflags=SUBPROCESS_FLAGS,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return False
        if completed.returncode != 0:
            return False
    return True


def resolve_ffmpeg_toolchain(
    directory_hint: str | os.PathLike[str] | None = None,
) -> FFmpegToolchain | None:
    """Find and validate FFmpeg on PATH, in a hint, or in WinGet links."""
    candidates: list[FFmpegToolchain] = []
    if directory_hint is not None:
        candidates.append(_toolchain_from_directory(directory_hint))

    ffmpeg_path = shutil.which("ffmpeg")
    ffprobe_path = shutil.which("ffprobe")
    if ffmpeg_path and ffprobe_path:
        resolved_ffmpeg = Path(ffmpeg_path).resolve()
        resolved_ffprobe = Path(ffprobe_path).resolve()
        if resolved_ffmpeg.parent == resolved_ffprobe.parent:
            candidates.append(
                FFmpegToolchain(
                    ffmpeg=str(resolved_ffmpeg),
                    ffprobe=str(resolved_ffprobe),
                )
            )

    if _IS_WINDOWS:
        candidates.extend(
            _toolchain_from_directory(directory)
            for directory in _windows_winget_link_directories()
        )

    seen: set[tuple[str, str]] = set()
    for toolchain in candidates:
        key = (toolchain.ffmpeg, toolchain.ffprobe)
        if key in seen:
            continue
        seen.add(key)
        if _toolchain_can_run(toolchain):
            return toolchain
    return None


def check_ffmpeg_installed(
    directory_hint: str | os.PathLike[str] | None = None,
) -> bool:
    """Return whether both FFmpeg executables can be found and run."""
    return resolve_ffmpeg_toolchain(directory_hint) is not None


def evaluate_expression(expression: str) -> float | None:
    """Evaluate a small arithmetic expression without using Python ``eval``."""
    expression = str(expression).strip()
    if not expression or len(expression) > 256:
        return None
    if any(character not in "0123456789+-*/.() " for character in expression):
        return None

    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, ValueError):
        return None

    def visit(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return float(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp) and isinstance(
            node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)
        ):
            left = visit(node.left)
            right = visit(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            return left / right
        raise ValueError("Unsupported expression")

    try:
        result = visit(tree)
    except (ArithmeticError, RecursionError, ValueError):
        return None
    return result if math.isfinite(result) else None


def ensure_even(value: float | int | None) -> int | None:
    """Round a numeric value down to the nearest even integer."""
    if value is None:
        return None
    try:
        integer = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return integer if integer % 2 == 0 else integer - 1


def parse_frame_rate(value: str | None) -> float:
    if not value or value == "0/0":
        raise ProbeError("The video does not report a valid frame rate.")
    try:
        fps = float(Fraction(value))
    except (ValueError, ZeroDivisionError) as error:
        raise ProbeError("The video does not report a valid frame rate.") from error
    if not math.isfinite(fps) or fps <= 0:
        raise ProbeError("The video does not report a valid frame rate.")
    return fps


def probe_source(path: str, toolchain: FFmpegToolchain | None = None) -> SourceInfo:
    """Read all source metadata in one FFprobe invocation."""
    source_path = Path(path)
    if not source_path.is_file():
        raise ProbeError("The selected video is not a local file.")

    command = [
        toolchain.ffprobe if toolchain is not None else "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=codec_type,width,height,avg_frame_rate,r_frame_rate,bit_rate",
        "-of",
        "json",
        str(source_path),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=SUBPROCESS_FLAGS,
            check=False,
        )
    except FileNotFoundError as error:
        raise ProbeError("FFprobe is not installed.") from error
    except subprocess.TimeoutExpired as error:
        raise ProbeError("Reading video information timed out.") from error
    except OSError as error:
        raise ProbeError(f"Could not read the video: {error}") from error

    if completed.returncode != 0:
        detail = completed.stderr.strip().splitlines()
        message = detail[-1] if detail else "FFprobe could not read this file."
        raise ProbeError(message)

    try:
        data = json.loads(completed.stdout)
        streams = data.get("streams", [])
        video = next(stream for stream in streams if stream.get("codec_type") == "video")
        duration = float(data["format"]["duration"])
        width = int(video["width"])
        height = int(video["height"])
    except (json.JSONDecodeError, KeyError, StopIteration, TypeError, ValueError) as error:
        raise ProbeError("The selected file does not contain a readable video stream.") from error

    if not math.isfinite(duration) or duration <= 0 or width <= 0 or height <= 0:
        raise ProbeError("The video metadata is incomplete or invalid.")

    fps_value = video.get("avg_frame_rate")
    if not fps_value or fps_value == "0/0":
        fps_value = video.get("r_frame_rate")
    fps = parse_frame_rate(fps_value)

    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    if audio is None:
        audio_bitrate_kbps = None
    else:
        try:
            audio_bitrate_kbps = max(1, round(int(audio.get("bit_rate", 0)) / 1000))
        except (TypeError, ValueError):
            audio_bitrate_kbps = 0
        if audio_bitrate_kbps <= 0:
            audio_bitrate_kbps = DEFAULT_AUDIO_BITRATE_KBPS

    return SourceInfo(
        path=str(source_path.resolve()),
        duration=duration,
        width=width,
        height=height,
        fps=fps,
        size_mb=source_path.stat().st_size / (1024 * 1024),
        audio_bitrate_kbps=audio_bitrate_kbps,
    )


def calculate_video_bitrate(
    target_mb: float,
    source_duration: float,
    speed: float,
    audio_bitrate_bps: int,
    mute_audio: bool,
) -> int:
    """Calculate a target video bitrate using the expected output duration."""
    if not math.isfinite(target_mb) or target_mb <= 0:
        raise ValidationError("Target size must be greater than zero.")
    if not math.isfinite(source_duration) or source_duration <= 0:
        raise ValidationError("Video duration must be greater than zero.")
    if not math.isfinite(speed) or speed <= 0:
        raise ValidationError("Speed must be greater than zero.")
    if audio_bitrate_bps < 0:
        raise ValidationError("Audio bitrate cannot be negative.")

    output_duration = source_duration / speed
    audio_bps = 0 if mute_audio else audio_bitrate_bps
    target_bits = target_mb * 1024 * 1024 * 8
    video_bps = ((target_bits / output_duration) - audio_bps) * TARGET_SAFETY_MARGIN
    if not math.isfinite(video_bps) or video_bps < 1:
        raise ValidationError("The target size is too small for these settings.")
    return int(video_bps)


def make_job(
    *,
    source: SourceInfo,
    output_file: str,
    target_mb: float,
    width: int,
    height: int,
    fps: float,
    preset: str,
    audio_bitrate_kbps: float,
    mute_audio: bool,
    tune: str | None,
    speed: float,
    codec: str,
) -> CompressionJob:
    """Validate UI values and create an immutable compression job."""
    if width < 2 or height < 2 or width > 16384 or height > 16384:
        raise ValidationError("Width and height must be between 2 and 16384 pixels.")
    if width % 2 or height % 2:
        raise ValidationError("Width and height must be even numbers.")
    if not math.isfinite(fps) or fps <= 0 or fps > 1000:
        raise ValidationError("Frame rate must be between 0 and 1000 fps.")
    if not math.isfinite(audio_bitrate_kbps) or not 0 <= audio_bitrate_kbps <= 10000:
        raise ValidationError("Audio bitrate must be between 0 and 10000 kbps.")
    if not math.isfinite(speed) or not 0.01 <= speed <= 10000:
        raise ValidationError("Speed must be between 0.01× and 10000×.")
    if codec not in VIDEO_CODECS.values():
        raise ValidationError("The selected video codec is not supported.")
    if not output_file:
        raise ValidationError("Choose an output file.")

    audio_bitrate_bps = round(audio_bitrate_kbps * 1000)
    video_bitrate_bps = calculate_video_bitrate(
        target_mb, source.duration, speed, audio_bitrate_bps, mute_audio
    )
    return CompressionJob(
        input_file=source.path,
        output_file=output_file,
        video_bitrate_bps=video_bitrate_bps,
        width=width,
        height=height,
        fps=fps,
        preset=preset,
        duration=source.duration,
        audio_bitrate_bps=audio_bitrate_bps,
        mute_audio=mute_audio,
        tune=tune,
        speed=speed,
        codec=codec,
    )


def build_atempo_filters(speed: float) -> list[str]:
    """Split a speed into FFmpeg ``atempo`` factors in its supported range."""
    if speed <= 0 or not math.isfinite(speed):
        raise ValidationError("Speed must be greater than zero.")
    factors: list[float] = []
    remainder = speed
    while remainder < 0.5:
        factors.append(0.5)
        remainder /= 0.5
    while remainder > 100:
        factors.append(100.0)
        remainder /= 100.0
    if not math.isclose(remainder, 1.0):
        factors.append(remainder)
    return [f"atempo={factor:.10g}" for factor in factors]


def build_ffmpeg_command(
    job: CompressionJob, toolchain: FFmpegToolchain | None = None
) -> list[str]:
    """Construct the FFmpeg argument vector for a compression job."""
    video_filters = [f"scale={job.width}:{job.height}", f"fps={job.fps:.10g}"]
    if not math.isclose(job.speed, 1.0):
        video_filters.append(f"setpts=PTS/{job.speed:.10g}")

    command = [
        toolchain.ffmpeg if toolchain is not None else "ffmpeg",
        "-y",
        "-i",
        job.input_file,
        "-c:v",
        job.codec,
    ]
    if job.codec == "libaom-av1":
        command.extend(["-cpu-used", job.preset])
    else:
        command.extend(["-preset", job.preset])
        if job.tune:
            command.extend(["-tune", job.tune])

    command.extend(["-b:v", str(job.video_bitrate_bps)])
    if job.mute_audio:
        command.append("-an")
    else:
        command.extend(["-c:a", "aac", "-b:a", str(job.audio_bitrate_bps)])
        audio_filters = build_atempo_filters(job.speed)
        if audio_filters:
            command.extend(["-af", ",".join(audio_filters)])

    command.extend(["-vf", ",".join(video_filters), "-movflags", "+faststart", job.output_file])
    return command


def parse_progress_seconds(line: str) -> float | None:
    match = _TIME_PATTERN.search(line)
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


class FFmpegRunner:
    """Run one FFmpeg job with thread-safe graceful and forced cancellation."""

    def __init__(self, toolchain: FFmpegToolchain | None = None) -> None:
        self._toolchain = toolchain
        self._stop_requested = threading.Event()
        self._process: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._process is not None and self._process.poll() is None

    def stop(self) -> None:
        self._stop_requested.set()
        with self._lock:
            process = self._process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    def force_stop(self) -> None:
        self._stop_requested.set()
        with self._lock:
            process = self._process
        if process is not None and process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass

    def run(
        self,
        job: CompressionJob,
        progress_callback: Callable[[int], None] | None = None,
    ) -> RunResult:
        output_path = Path(job.output_file)
        temporary_path: Path | None = None
        error_lines: list[str] = []

        try:
            try:
                descriptor, temporary_name = tempfile.mkstemp(
                    prefix=f".{output_path.stem}-",
                    suffix=output_path.suffix or ".mp4",
                    dir=output_path.parent,
                )
            except OSError:
                # A document-portal save grants access to the selected file,
                # but not necessarily to sibling files in its virtual folder.
                descriptor, temporary_name = tempfile.mkstemp(
                    prefix="video-compressor-",
                    suffix=output_path.suffix or ".mp4",
                )
            os.close(descriptor)
            os.unlink(temporary_name)
            temporary_path = Path(temporary_name)
            command = build_ffmpeg_command(
                replace(job, output_file=str(temporary_path)), self._toolchain
            )

            with self._lock:
                if self._stop_requested.is_set():
                    return RunResult("stopped")
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                    creationflags=SUBPROCESS_FLAGS,
                )
                self._process = process

            assert process.stderr is not None
            for line in process.stderr:
                stripped = line.strip()
                if stripped:
                    error_lines.append(stripped)
                    error_lines = error_lines[-12:]
                seconds = parse_progress_seconds(line)
                if seconds is not None and progress_callback is not None:
                    percent = round(seconds / job.output_duration * 100)
                    progress_callback(max(0, min(percent, 99)))

            return_code = process.wait()
            if self._stop_requested.is_set():
                return RunResult("stopped")
            if return_code != 0:
                detail = error_lines[-1] if error_lines else "FFmpeg provided no error details."
                return RunResult("failed", f"FFmpeg exited with code {return_code}.\n\n{detail}")

            try:
                os.replace(temporary_path, output_path)
            except OSError as error:
                if error.errno not in (errno.EXDEV, errno.EACCES, errno.EPERM):
                    raise
                # Portal-backed files can live on a different virtual file
                # system. Copy only after FFmpeg succeeds, so cancellation
                # never exposes a partial encode at the chosen destination.
                shutil.copyfile(temporary_path, output_path)
                temporary_path.unlink()
            temporary_path = None
            if progress_callback is not None:
                progress_callback(100)
            return RunResult("success")
        except (OSError, subprocess.SubprocessError) as error:
            status = "stopped" if self._stop_requested.is_set() else "failed"
            return RunResult(status, "" if status == "stopped" else str(error))
        finally:
            with self._lock:
                self._process = None
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
