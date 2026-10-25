from dataclasses import replace
import io
import json
import os
from pathlib import Path
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from recorder import (
    Settings, Splitter, Tag, TimestampUnwrapper, configure,
    control_handler, read_header, read_tags, ThreadingHTTPServer,
)


HEADER = b"FLV\x01\x05\0\0\0\x09\0\0\0\0"
VIDEO_CONFIG = Tag(9, 0, b"\x17\0\0\0\0config")
AUDIO_CONFIG = Tag(8, 0, b"\xaf\0config")


def video(timestamp):
    prefix = b"\x17" if timestamp % 2000 == 0 else b"\x27"
    return Tag(9, timestamp, prefix + b"\x01\0\0\0" + struct.pack(">I", timestamp))


def audio(timestamp):
    return Tag(8, timestamp, b"\xaf\x01" + struct.pack(">I", timestamp))


def packets(path):
    with path.open("rb") as source:
        read_header(source)
        return [tag for tag in read_tags(source) if tag.kind != 18 and not tag.codec_header]


class RecorderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        with patch.dict(os.environ, {}, clear=True):
            self.settings = replace(
                Settings.from_env(), path=Path(self.temp.name), align_clock=False,
            )

    def splitter(self, **settings):
        result = Splitter(replace(self.settings, **settings), HEADER, now_ms=0)
        self.addCleanup(result.close)
        result.feed(VIDEO_CONFIG)
        result.feed(AUDIO_CONFIG)
        return result

    def generate(self, splitter, duration):
        expected = set()
        for timestamp in range(0, duration, 20):
            tag = audio(timestamp)
            expected.add((tag.kind, tag.data))
            splitter.feed(tag)
            if timestamp % 40 == 0:
                tag = video(timestamp)
                expected.add((tag.kind, tag.data))
                splitter.feed(tag)
        splitter.close()
        return expected

    def test_every_video_and_audio_packet_survives_rotation_with_overlap(self):
        splitter = self.splitter(interval_ms=4000, overlap_ms=1000)
        expected = self.generate(splitter, 14_000)
        files = sorted(splitter.directory.glob("*.flv"))
        self.assertEqual(4, len(files))
        recorded = [packets(path) for path in files]
        actual = {(tag.kind, tag.data) for clip in recorded for tag in clip}
        self.assertEqual(expected, actual)
        for boundary, (first, second) in enumerate(zip(recorded, recorded[1:]), start=1):
            for kind in (8, 9):
                common = {tag.data for tag in first if tag.kind == kind} & {
                    tag.data for tag in second if tag.kind == kind
                }
                stamps = sorted(int.from_bytes(data[-4:], "big") for data in common)
                self.assertLessEqual(stamps[0], boundary * 4000 - 1000)
                self.assertGreaterEqual(stamps[-1], boundary * 4000 + 1000)
            self.assertTrue(next(tag for tag in second if tag.kind == 9).keyframe)
        self.assertFalse(list(splitter.directory.glob("*.part")))

    def test_default_two_minute_rotation(self):
        splitter = self.splitter()
        self.generate(splitter, 242_000)
        self.assertEqual(3, len(list(splitter.directory.glob("*.flv"))))

    def test_clock_alignment_and_odd_minute_offset(self):
        settings = replace(
            self.settings, align_clock=True, clock_offset_ms=60_000, interval_ms=120_000,
        )
        splitter = Splitter(settings, HEADER, now_ms=54 * 60_000 + 59_000)
        self.addCleanup(splitter.close)
        splitter.feed(video(0))
        self.assertEqual(1000, splitter.next_boundary - settings.interval_ms)
        # With a one-minute offset the next complete core is 00:55:00--00:57:00.
        self.assertEqual(57 * 60_000, splitter.clock_origin + splitter.next_boundary)

    def test_disabled_recording_writes_nothing(self):
        splitter = self.splitter(enabled=False)
        self.generate(splitter, 5000)
        self.assertFalse(splitter.directory.exists())

    def test_memory_is_bounded_across_many_rotations(self):
        splitter = self.splitter(interval_ms=4000, overlap_ms=1000)
        self.generate(splitter, 100_000)
        self.assertLess(splitter.buffer_size, 10_000)
        self.assertLessEqual(len(splitter.keyframes), 2)

    def test_long_gop_and_excessive_bitrate_fail_explicitly(self):
        splitter = self.splitter(max_gop_ms=1000)
        splitter.feed(video(0))
        with self.assertRaisesRegex(ValueError, "without an H.264 keyframe"):
            splitter.feed(video(1040))
        splitter = self.splitter(max_buffer_bytes=10)
        with self.assertRaisesRegex(ValueError, "Overlap buffer"):
            splitter.feed(video(0))

    def test_failed_stream_keeps_recoverable_partial(self):
        splitter = self.splitter()
        splitter.feed(video(0))
        splitter.close(complete=False)
        self.assertEqual(1, len(list(splitter.directory.glob("*.flv.part"))))
        self.assertFalse(list(splitter.directory.glob("*.flv")))

    def test_flv_roundtrip_preserves_payload_and_timestamps(self):
        original = [VIDEO_CONFIG, AUDIO_CONFIG, video(0), audio(20), video(40)]
        source = io.BytesIO(HEADER + b"".join(tag.encode(0) for tag in original))
        self.assertEqual(HEADER, read_header(source))
        self.assertEqual(original, list(read_tags(source)))

    def test_corrupt_and_truncated_input_is_rejected(self):
        with self.assertRaisesRegex(EOFError, "Truncated"):
            read_header(io.BytesIO(b"FLV"))
        encoded = video(0).encode(0)
        with self.assertRaisesRegex(EOFError, "Truncated"):
            list(read_tags(io.BytesIO(encoded[:-1])))
        with self.assertRaisesRegex(ValueError, "PreviousTagSize"):
            list(read_tags(io.BytesIO(encoded[:-4] + b"\0\0\0\0")))

    def test_unsupported_camera_codecs_are_rejected(self):
        for tag, message in ((Tag(9, 0, b"\x1c\x01"), "H.264"), (Tag(8, 0, b"\x70\x01"), "AAC")):
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                list(read_tags(io.BytesIO(tag.encode(0))))

    def test_timestamp_wrap_after_49_days(self):
        unwrapper = TimestampUnwrapper()
        self.assertEqual(0xFFFFFFF0, unwrapper.unwrap(0xFFFFFFF0))
        self.assertEqual(0x100000010, unwrapper.unwrap(0x10))
        self.assertEqual(0xFFFFFFF8, unwrapper.unwrap(0xFFFFFFF8))
        self.assertEqual(0x100000020, unwrapper.unwrap(0x20))

    def test_discontinuous_timestamps_fail_instead_of_corrupting_clips(self):
        splitter = self.splitter()
        splitter.feed(video(20_000))
        with self.assertRaisesRegex(ValueError, "moved backwards"):
            splitter.feed(video(0))
        splitter = self.splitter()
        splitter.feed(video(0))
        with self.assertRaisesRegex(ValueError, "jumped"):
            splitter.feed(video(240_000))

    def test_unique_sessions_and_nonunique_option(self):
        first = self.splitter()
        second = self.splitter()
        self.assertNotEqual(first.directory, second.directory)
        fixed = self.splitter(unique=False)
        self.assertEqual(self.settings.path / "overlap" / "stream", fixed.directory)

    def test_invalid_environment_is_rejected(self):
        cases = {
            "RTMP_APP_NAME": "live;inject",
            "RTMP_STREAM_NAME": "../stream",
            "RTMP_RECORD_PATH": "/recordings/../etc",
            "RTMP_RECORD_ENABLED": "yes",
            "RTMP_RECORD_UNIQUE": "false",
            "RTMP_SEGMENT_MINUTES": "0",
            "RTMP_OVERLAP_SECONDS": "60",
            "RTMP_MAX_GOP_SECONDS": "0",
            "RTMP_MAX_BUFFER_MB": "0",
            "RTMP_CLOCK_OFFSET_MINUTES": "2",
            "PUID": "0",
        }
        for name, value in cases.items():
            with self.subTest(name=name), patch.dict(os.environ, {name: value}, clear=True):
                with self.assertRaises(ValueError):
                    Settings.from_env()

    def test_rendering_maps_on_to_all_only_for_nginx(self):
        template = Path(self.temp.name) / "template"
        output = Path(self.temp.name) / "output"
        template.write_text("record ${RTMP_RECORD_ENABLED}; app ${RTMP_APP_NAME}; $name;")
        for kind, mode in (("nginx", "all"), ("srs", "on")):
            with patch("os.geteuid", return_value=1000), patch("os.getegid", return_value=1000):
                configure(self.settings, kind, template, output)
            self.assertEqual(f"record {mode}; app live; $name;", output.read_text())
        template.write_text("${UNKNOWN}")
        with self.assertRaises(KeyError):
            configure(self.settings, "nginx", template, output)

    def test_publish_callbacks_for_nginx_and_srs(self):
        http = ThreadingHTTPServer(("127.0.0.1", 0), control_handler(self.settings))
        thread = threading.Thread(target=http.serve_forever)
        thread.start()
        self.addCleanup(http.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(http.shutdown)
        url = f"http://127.0.0.1:{http.server_port}/publish"
        bodies = (
            (b"app=live&name=stream", "application/x-www-form-urlencoded"),
            (json.dumps({"app": "live", "stream": "stream"}).encode(), "application/json"),
        )
        for body, content_type in bodies:
            with urlopen(Request(url, data=body, headers={"Content-Type": content_type}), timeout=2) as response:
                self.assertEqual({"code": 0}, json.load(response))
        with self.assertRaises(HTTPError) as error:
            urlopen(Request(url, data=b"app=live&name=wrong"), timeout=2)
        self.assertEqual(403, error.exception.code)
        error.exception.close()


if __name__ == "__main__":
    unittest.main()
