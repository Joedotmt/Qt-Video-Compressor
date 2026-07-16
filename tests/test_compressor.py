import json
import errno
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest import mock

from compressor import (
    CompressionJob,
    FFmpegToolchain,
    FFmpegRunner,
    ProbeError,
    SourceInfo,
    ValidationError,
    build_atempo_filters,
    build_ffmpeg_command,
    calculate_video_bitrate,
    check_ffmpeg_installed,
    ensure_even,
    evaluate_expression,
    make_job,
    parse_frame_rate,
    parse_progress_seconds,
    probe_source,
    resolve_ffmpeg_toolchain,
)


class ExpressionTests(unittest.TestCase):
    def test_arithmetic_expressions(self):
        self.assertEqual(evaluate_expression("1920 / 2"), 960)
        self.assertEqual(evaluate_expression("(100 + 20) * 1.5"), 180)
        self.assertEqual(evaluate_expression("-2 + 5"), 3)

    def test_rejects_non_arithmetic_and_nonfinite_values(self):
        for expression in ("", "open('file')", "2 ** 8", "1 / 0", "1e3", "[1]"):
            with self.subTest(expression=expression):
                self.assertIsNone(evaluate_expression(expression))

    def test_even_dimensions_round_down(self):
        self.assertEqual(ensure_even(1921), 1920)
        self.assertEqual(ensure_even(1080), 1080)
        self.assertIsNone(ensure_even(None))


class ToolchainTests(unittest.TestCase):
    @staticmethod
    def successful_run(command, **_kwargs):
        return subprocess.CompletedProcess(command, 0)

    def test_directory_hint_resolves_and_checks_both_executables(self):
        suffix = ".exe" if os.name == "nt" else ""
        with tempfile.TemporaryDirectory() as directory, mock.patch(
            "compressor.shutil.which", return_value=None
        ), mock.patch(
            "compressor.subprocess.run", side_effect=self.successful_run
        ) as run:
            toolchain = resolve_ffmpeg_toolchain(directory)

        expected_ffmpeg = str(Path(directory, f"ffmpeg{suffix}").resolve())
        expected_ffprobe = str(Path(directory, f"ffprobe{suffix}").resolve())
        self.assertEqual(toolchain, FFmpegToolchain(expected_ffmpeg, expected_ffprobe))
        self.assertEqual(
            [call.args[0][0] for call in run.call_args_list],
            [expected_ffmpeg, expected_ffprobe],
        )

    def test_path_discovery_returns_absolute_executable_paths(self):
        suffix = ".exe" if os.name == "nt" else ""
        with tempfile.TemporaryDirectory() as directory:
            paths = {
                "ffmpeg": str(Path(directory, f"ffmpeg{suffix}")),
                "ffprobe": str(Path(directory, f"ffprobe{suffix}")),
            }
            with mock.patch(
                "compressor.shutil.which", side_effect=paths.get
            ), mock.patch(
                "compressor.subprocess.run", side_effect=self.successful_run
            ):
                toolchain = resolve_ffmpeg_toolchain()

        self.assertEqual(
            toolchain,
            FFmpegToolchain(
                str(Path(paths["ffmpeg"]).resolve()),
                str(Path(paths["ffprobe"]).resolve()),
            ),
        )

    def test_path_discovery_does_not_mix_installations(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = {
                "ffmpeg": str(Path(directory, "one", "ffmpeg")),
                "ffprobe": str(Path(directory, "two", "ffprobe")),
            }
            with mock.patch(
                "compressor.shutil.which", side_effect=paths.get
            ), mock.patch("compressor._IS_WINDOWS", False), mock.patch(
                "compressor.subprocess.run", side_effect=self.successful_run
            ) as run:
                toolchain = resolve_ffmpeg_toolchain()

        self.assertIsNone(toolchain)
        run.assert_not_called()

    def test_nonzero_version_check_rejects_toolchain(self):
        def version_check(command, **_kwargs):
            return subprocess.CompletedProcess(
                command, 1 if "ffprobe" in Path(command[0]).stem else 0
            )

        with tempfile.TemporaryDirectory() as directory, mock.patch(
            "compressor.shutil.which", return_value=None
        ), mock.patch("compressor._IS_WINDOWS", False), mock.patch(
            "compressor.subprocess.run", side_effect=version_check
        ):
            self.assertIsNone(resolve_ffmpeg_toolchain(directory))
            self.assertFalse(check_ffmpeg_installed(directory))

    def test_windows_winget_links_are_searched(self):
        with tempfile.TemporaryDirectory() as directory:
            local_app_data = Path(directory, "LocalAppData")
            program_files = Path(directory, "ProgramFiles")
            links = local_app_data / "Microsoft" / "WinGet" / "Links"
            with mock.patch("compressor._IS_WINDOWS", True), mock.patch.dict(
                os.environ,
                {
                    "LOCALAPPDATA": str(local_app_data),
                    "ProgramFiles": str(program_files),
                },
            ), mock.patch("compressor.shutil.which", return_value=None), mock.patch(
                "compressor.subprocess.run", side_effect=self.successful_run
            ):
                toolchain = resolve_ffmpeg_toolchain()

        self.assertEqual(
            toolchain,
            FFmpegToolchain(
                str(Path(links, "ffmpeg.exe").resolve()),
                str(Path(links, "ffprobe.exe").resolve()),
            ),
        )


class PlanningTests(unittest.TestCase):
    def setUp(self):
        self.source = SourceInfo(
            path="/tmp/input video.mp4",
            duration=100,
            width=1920,
            height=1080,
            fps=29.97,
            size_mb=50,
            audio_bitrate_kbps=128,
        )

    def test_bitrate_uses_output_duration_after_speed_change(self):
        normal = calculate_video_bitrate(10, 100, 1, 128_000, False)
        fast = calculate_video_bitrate(10, 100, 2, 128_000, False)
        slow = calculate_video_bitrate(10, 100, 0.5, 128_000, False)
        self.assertGreater(fast, normal)
        self.assertLess(slow, normal)

    def test_muted_audio_leaves_more_video_bitrate(self):
        with_audio = calculate_video_bitrate(10, 100, 1, 128_000, False)
        muted = calculate_video_bitrate(10, 100, 1, 128_000, True)
        self.assertGreater(muted, with_audio)

    def test_invalid_target_is_rejected(self):
        with self.assertRaises(ValidationError):
            calculate_video_bitrate(0, 100, 1, 128_000, False)

    def test_make_job_validates_dimensions(self):
        with self.assertRaises(ValidationError):
            make_job(
                source=self.source,
                output_file="/tmp/output.mp4",
                target_mb=10,
                width=1919,
                height=1080,
                fps=30,
                preset="medium",
                audio_bitrate_kbps=128,
                mute_audio=False,
                tune=None,
                speed=1,
                codec="libx264",
            )


class CommandTests(unittest.TestCase):
    def job(self, **changes):
        values = dict(
            input_file="/tmp/input video.mp4",
            output_file="/tmp/output video.mp4",
            video_bitrate_bps=1_000_000,
            width=1280,
            height=720,
            fps=30,
            preset="medium",
            duration=20,
            audio_bitrate_bps=128_000,
            mute_audio=False,
            tune="film",
            speed=1,
            codec="libx264",
        )
        values.update(changes)
        return CompressionJob(**values)

    def test_h264_command(self):
        command = build_ffmpeg_command(self.job())
        self.assertIn("libx264", command)
        self.assertEqual(command[command.index("-preset") + 1], "medium")
        self.assertEqual(command[command.index("-tune") + 1], "film")
        self.assertIn("scale=1280:720,fps=30", command)
        self.assertNotIn("-af", command)
        self.assertEqual(command[-1], "/tmp/output video.mp4")

    def test_command_uses_explicit_ffmpeg_path(self):
        toolchain = FFmpegToolchain("/tools/ffmpeg", "/tools/ffprobe")
        command = build_ffmpeg_command(self.job(), toolchain)
        self.assertEqual(command[0], "/tools/ffmpeg")

    def test_av1_uses_cpu_used_instead_of_preset(self):
        command = build_ffmpeg_command(
            self.job(codec="libaom-av1", preset="4", tune="grain")
        )
        self.assertEqual(command[command.index("-cpu-used") + 1], "4")
        self.assertNotIn("-preset", command)
        self.assertNotIn("-tune", command)

    def test_muted_command_removes_audio(self):
        command = build_ffmpeg_command(self.job(mute_audio=True))
        self.assertIn("-an", command)
        self.assertNotIn("-c:a", command)

    def test_speed_filters_chain_atempo(self):
        command = build_ffmpeg_command(self.job(speed=0.25))
        self.assertEqual(command[command.index("-af") + 1], "atempo=0.5,atempo=0.5")
        self.assertIn("setpts=PTS/0.25", command[command.index("-vf") + 1])
        self.assertEqual(build_atempo_filters(200), ["atempo=100", "atempo=2"])

    def test_progress_parser(self):
        self.assertEqual(parse_progress_seconds("frame=3 time=01:02:03.50 speed=1x"), 3723.5)
        self.assertIsNone(parse_progress_seconds("frame=3"))


class ProbeTests(unittest.TestCase):
    def test_probe_parses_one_video_and_audio_stream(self):
        payload = {
            "streams": [
                {
                    "codec_type": "video",
                    "width": 1920,
                    "height": 1080,
                    "avg_frame_rate": "30000/1001",
                    "r_frame_rate": "30/1",
                },
                {"codec_type": "audio", "bit_rate": "192000"},
            ],
            "format": {"duration": "12.5"},
        }
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory, "sample.mp4")
            video.write_bytes(b"data")
            completed = subprocess.CompletedProcess(
                ["ffprobe"], 0, stdout=json.dumps(payload), stderr=""
            )
            with mock.patch("compressor.subprocess.run", return_value=completed):
                info = probe_source(str(video))
        self.assertEqual(info.width, 1920)
        self.assertEqual(info.height, 1080)
        self.assertAlmostEqual(info.fps, 29.97003, places=4)
        self.assertEqual(info.audio_bitrate_kbps, 192)

    def test_probe_distinguishes_missing_audio(self):
        payload = {
            "streams": [
                {
                    "codec_type": "video",
                    "width": 640,
                    "height": 360,
                    "avg_frame_rate": "24/1",
                }
            ],
            "format": {"duration": "2"},
        }
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory, "silent.mp4")
            video.write_bytes(b"data")
            completed = subprocess.CompletedProcess(
                ["ffprobe"], 0, stdout=json.dumps(payload), stderr=""
            )
            with mock.patch("compressor.subprocess.run", return_value=completed):
                info = probe_source(str(video))
        self.assertFalse(info.has_audio)
        self.assertIsNone(info.audio_bitrate_kbps)

    def test_invalid_frame_rate_is_rejected(self):
        with self.assertRaises(ProbeError):
            parse_frame_rate("0/0")

    def test_probe_uses_explicit_ffprobe_path(self):
        payload = {
            "streams": [
                {
                    "codec_type": "video",
                    "width": 640,
                    "height": 360,
                    "avg_frame_rate": "24/1",
                }
            ],
            "format": {"duration": "2"},
        }
        toolchain = FFmpegToolchain("/tools/ffmpeg", "/tools/ffprobe")
        completed = subprocess.CompletedProcess(
            [toolchain.ffprobe], 0, stdout=json.dumps(payload), stderr=""
        )
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory, "sample.mp4")
            video.write_bytes(b"data")
            with mock.patch(
                "compressor.subprocess.run", return_value=completed
            ) as run:
                probe_source(str(video), toolchain)
        self.assertEqual(run.call_args.args[0][0], toolchain.ffprobe)


class RunnerTests(unittest.TestCase):
    @staticmethod
    def job(output_file):
        return CompressionJob(
            input_file="/tmp/input.mp4",
            output_file=output_file,
            video_bitrate_bps=1_000_000,
            width=640,
            height=360,
            fps=30,
            preset="medium",
            duration=10,
        )

    def test_success_atomically_replaces_output(self):
        commands = []

        class SuccessfulProcess:
            def __init__(self, command, **_kwargs):
                commands.append(command)
                Path(command[-1]).write_bytes(b"complete video")
                self.stderr = iter(["frame=1 time=00:00:05.00 speed=1x\n"])

            def poll(self):
                return 0

            def wait(self):
                return 0

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory, "output.mp4")
            output.write_bytes(b"original")
            updates = []
            toolchain = FFmpegToolchain("/tools/ffmpeg", "/tools/ffprobe")
            with mock.patch("compressor.subprocess.Popen", SuccessfulProcess):
                result = FFmpegRunner(toolchain).run(
                    self.job(str(output)), updates.append
                )
            self.assertEqual(result.status, "success")
            self.assertEqual(output.read_bytes(), b"complete video")
            self.assertEqual(updates, [50, 100])
            self.assertEqual(commands[0][0], toolchain.ffmpeg)

    def test_cancellation_removes_partial_output_and_preserves_destination(self):
        started = threading.Event()
        released = threading.Event()

        class BlockingProcess:
            def __init__(self, command, **_kwargs):
                Path(command[-1]).write_bytes(b"partial video")
                self._stopped = False
                self.stderr = self._lines()
                started.set()

            def _lines(self):
                yield "frame=1 time=00:00:01.00 speed=1x\n"
                released.wait(2)

            def poll(self):
                return -15 if self._stopped else None

            def terminate(self):
                self._stopped = True
                released.set()

            def kill(self):
                self.terminate()

            def wait(self):
                return -15

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory, "output.mp4")
            output.write_bytes(b"original")
            runner = FFmpegRunner()
            result_holder = []
            with mock.patch("compressor.subprocess.Popen", BlockingProcess):
                thread = threading.Thread(
                    target=lambda: result_holder.append(runner.run(self.job(str(output))))
                )
                thread.start()
                self.assertTrue(started.wait(1))
                runner.stop()
                thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(result_holder[0].status, "stopped")
            self.assertEqual(output.read_bytes(), b"original")
            self.assertEqual(list(Path(directory).glob(".*.mp4")), [])

    def test_cross_filesystem_destination_falls_back_to_copy(self):
        class SuccessfulProcess:
            def __init__(self, command, **_kwargs):
                Path(command[-1]).write_bytes(b"complete video")
                self.stderr = iter(())

            def poll(self):
                return 0

            def wait(self):
                return 0

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory, "portal-output.mp4")
            cross_device = OSError(errno.EXDEV, "Cross-device link")
            with mock.patch("compressor.subprocess.Popen", SuccessfulProcess), mock.patch(
                "compressor.os.replace", side_effect=cross_device
            ):
                result = FFmpegRunner().run(self.job(str(output)))
            self.assertEqual(result.status, "success")
            self.assertEqual(output.read_bytes(), b"complete video")


if __name__ == "__main__":
    unittest.main()
