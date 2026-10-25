import argparse
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import re
import signal
import socket
import struct
import threading
import time
from urllib.parse import parse_qs
import uuid


LOG = logging.getLogger("rtmp-recorder")
IDENTIFIER = re.compile(r"[A-Za-z0-9_-]+")


@dataclass(frozen=True)
class Settings:
    app: str
    stream: str
    path: Path
    enabled: bool
    unique: bool
    interval_ms: int
    overlap_ms: int
    max_gop_ms: int
    max_buffer_bytes: int
    align_clock: bool
    clock_offset_ms: int
    uid: int
    gid: int

    @classmethod
    def from_env(cls):
        def flag(name, default):
            value = os.environ.get(name, default)
            if value not in ("on", "off"):
                raise ValueError(f"{name} must be on or off")
            return value == "on"

        app = os.environ.get("RTMP_APP_NAME", "live")
        stream = os.environ.get("RTMP_STREAM_NAME", "stream")
        if not IDENTIFIER.fullmatch(app) or not IDENTIFIER.fullmatch(stream):
            raise ValueError("RTMP_APP_NAME and RTMP_STREAM_NAME must use A-Z, a-z, 0-9, _ or -")
        path = Path(os.environ.get("RTMP_RECORD_PATH", "/recordings"))
        if not path.is_absolute() or ".." in path.parts or not path.is_relative_to("/recordings"):
            raise ValueError("RTMP_RECORD_PATH must be /recordings or one of its subdirectories")
        if not re.fullmatch(r"/[A-Za-z0-9_/-]+", str(path)):
            raise ValueError("RTMP_RECORD_PATH contains unsupported characters")
        minutes = int(os.environ.get("RTMP_SEGMENT_MINUTES", "2"))
        overlap = int(os.environ.get("RTMP_OVERLAP_SECONDS", "1"))
        max_gop = int(os.environ.get("RTMP_MAX_GOP_SECONDS", "10"))
        buffer_mb = int(os.environ.get("RTMP_MAX_BUFFER_MB", "64"))
        offset = int(os.environ.get("RTMP_CLOCK_OFFSET_MINUTES", "0"))
        uid = int(os.environ.get("PUID", "1000"))
        gid = int(os.environ.get("PGID", "1000"))
        if minutes < 1 or not 0 <= overlap * 2 < minutes * 60:
            raise ValueError("Use at least 1 minute and an overlap smaller than half the interval")
        if not 1 <= max_gop <= minutes * 60 or buffer_mb < 1:
            raise ValueError("Invalid RTMP_MAX_GOP_SECONDS or RTMP_MAX_BUFFER_MB")
        if uid < 1 or gid < 1:
            raise ValueError("PUID and PGID must be non-root positive IDs")
        if not 0 <= offset < minutes:
            raise ValueError("RTMP_CLOCK_OFFSET_MINUTES must be between 0 and RTMP_SEGMENT_MINUTES - 1")
        return cls(
            app, stream, path,
            flag("RTMP_RECORD_ENABLED", "on"),
            flag("RTMP_RECORD_UNIQUE", "on"),
            minutes * 60_000, overlap * 1000, max_gop * 1000,
            buffer_mb * 1024 * 1024,
            flag("RTMP_ALIGN_CLOCK", "on"), offset * 60_000, uid, gid,
        )


def configure(settings, kind, template, output):
    values = {
        "RTMP_APP_NAME": settings.app,
        "RTMP_STREAM_NAME": settings.stream,
        "RTMP_RECORD_ENABLED": ("all" if kind == "nginx" else "on") if settings.enabled else "off",
        "RTMP_RECORD_PATH": str(settings.path),
        "RTMP_RECORD_UNIQUE": "on" if settings.unique else "off",
        "RTMP_SEGMENT_MINUTES": str(settings.interval_ms // 60_000),
        "RTMP_SEGMENT_SECONDS": str(settings.interval_ms // 1000),
    }
    text = re.sub(r"\$\{([A-Z_]+)\}", lambda match: values[match[1]], template.read_text())
    output.write_text(text)
    for directory in (settings.path, settings.path / "overlap", settings.path / "native"):
        directory.mkdir(parents=True, exist_ok=True)
        if os.geteuid() == 0:
            os.chown(directory, settings.uid, settings.gid)
    if os.geteuid() == 0:
        os.setgroups([])
        os.setgid(settings.gid)
        os.setuid(settings.uid)
    if (os.geteuid(), os.getegid()) != (settings.uid, settings.gid):
        raise ValueError("Recorder must run as PUID:PGID after initialization")


@dataclass(frozen=True)
class Tag:
    kind: int
    timestamp: int
    data: bytes

    @property
    def codec_header(self):
        return len(self.data) >= 2 and (
            (self.kind == 9 and self.data[0] & 15 == 7 and self.data[1] == 0)
            or (self.kind == 8 and self.data[0] >> 4 == 10 and self.data[1] == 0)
        )

    @property
    def keyframe(self):
        return self.kind == 9 and len(self.data) >= 2 and self.data[0] == 0x17 and self.data[1] == 1

    @property
    def size(self):
        return len(self.data) + 15

    def encode(self, origin):
        timestamp = max(0, self.timestamp - origin)
        if timestamp > 0xFFFFFFFF:
            raise ValueError("FLV segment timestamp overflow")
        header = (
            bytes([self.kind]) + len(self.data).to_bytes(3, "big")
            + (timestamp & 0xFFFFFF).to_bytes(3, "big")
            + bytes([timestamp >> 24]) + b"\0\0\0"
        )
        return header + self.data + struct.pack(">I", 11 + len(self.data))


class TimestampUnwrapper:
    def __init__(self):
        self.latest = 0

    def unwrap(self, timestamp):
        modulus = 1 << 32
        base = self.latest // modulus * modulus
        candidates = (base + timestamp, base + timestamp + modulus, base + timestamp - modulus)
        result = min(candidates, key=lambda value: abs(value - self.latest))
        if result < 0:
            result = timestamp
        self.latest = max(self.latest, result)
        return result


def read_exact(source, size, allow_eof=False):
    data = source.read(size)
    if not data and allow_eof:
        return None
    if len(data) != size:
        raise EOFError("Truncated FLV: incomplete header or tag; unfinished files remain as .part")
    return data


def read_header(source):
    header = read_exact(source, 9, allow_eof=True)
    if header is None:
        return None
    if header[:4] != b"FLV\x01":
        raise ValueError("Expected FLV version 1")
    offset = int.from_bytes(header[5:9], "big")
    if not 9 <= offset <= 4096:
        raise ValueError("Invalid FLV header size")
    header += read_exact(source, offset - 9 + 4)
    if header[-4:] != b"\0\0\0\0":
        raise ValueError("Invalid FLV PreviousTagSize0")
    return header


def read_tags(source):
    unwrapper = TimestampUnwrapper()
    while (header := read_exact(source, 11, allow_eof=True)) is not None:
        size = int.from_bytes(header[1:4], "big")
        data = read_exact(source, size)
        previous_size = read_exact(source, 4)
        if int.from_bytes(previous_size, "big") != size + 11:
            raise ValueError("Invalid FLV PreviousTagSize")
        kind = header[0]
        if kind not in (8, 9, 18) or header[8:11] != b"\0\0\0":
            raise ValueError("Unsupported FLV tag")
        if kind == 9 and (len(data) < 2 or data[0] & 15 != 7):
            raise ValueError("Configure the camera for H.264 video (not H.265)")
        if kind == 8 and (len(data) < 2 or data[0] >> 4 != 10):
            raise ValueError("Configure the camera for AAC audio, or disable audio")
        timestamp = int.from_bytes(header[4:7], "big") | header[7] << 24
        yield Tag(kind, unwrapper.unwrap(timestamp), data)


class Clip:
    def __init__(self, path, header, origin, end, cached):
        self.path = path
        self.partial = path.with_suffix(".flv.part")
        self.origin = origin
        self.end = end
        self.file = self.partial.open("xb")
        self.file.write(header)
        for tag in cached:
            self.file.write(tag.encode(tag.timestamp))
        self.last_flush = time.monotonic()

    def write(self, tag):
        self.file.write(tag.encode(self.origin))
        if time.monotonic() - self.last_flush >= 1:
            self.file.flush()
            self.last_flush = time.monotonic()

    def close(self, complete):
        self.file.flush()
        os.fsync(self.file.fileno())
        self.file.close()
        if complete:
            os.replace(self.partial, self.path)
            LOG.info("Completed %s", self.path)


class Splitter:
    def __init__(self, settings, header, now_ms=None):
        self.settings = settings
        self.header = header
        self.now_ms = int(time.time() * 1000) if now_ms is None else now_ms
        self.cached = {}
        self.history = deque()
        self.keyframes = deque()
        self.buffer_size = 0
        self.active = []
        self.next_boundary = None
        self.clock_origin = None
        self.latest = 0
        self.first_timestamp = None
        self.last_keyframe = None
        self.sequence = 0
        stamp = datetime.fromtimestamp(self.now_ms / 1000, timezone.utc).strftime("%Y%m%dT%H%M%S")
        self.directory = settings.path / "overlap" / settings.stream
        if settings.unique:
            self.directory /= f"{stamp}-{uuid.uuid4().hex[:12]}"

    def open_clip(self, tags, end):
        self.sequence += 1
        self.directory.mkdir(parents=True, exist_ok=True)
        origin = min(tag.timestamp for tag in tags)
        start = datetime.fromtimestamp((self.clock_origin + origin) / 1000, timezone.utc)
        name = f"{start:%Y%m%dT%H%M%S}-{self.sequence:06d}.flv"
        clip = Clip(self.directory / name, self.header, origin, end, self.cached.values())
        self.active.append(clip)
        for tag in tags:
            clip.write(tag)

    def feed(self, tag):
        if not self.settings.enabled:
            return
        if tag.kind == 18 or tag.codec_header:
            self.cached[tag.kind] = tag
            for clip in self.active:
                clip.write(tag)
            return
        if self.first_timestamp is not None:
            if tag.timestamp < self.latest - self.settings.max_gop_ms:
                raise ValueError("Camera timestamps moved backwards; reconnect the publisher")
            if tag.timestamp > self.latest + self.settings.interval_ms:
                raise ValueError("Camera timestamps jumped by more than one segment interval")
        if self.first_timestamp is None:
            self.first_timestamp = tag.timestamp
            self.clock_origin = self.now_ms - tag.timestamp
            interval = self.settings.interval_ms
            if self.settings.align_clock:
                offset = self.settings.clock_offset_ms
                self.next_boundary = (
                    ((self.now_ms - offset) // interval + 1) * interval + offset - self.clock_origin
                )
            else:
                self.next_boundary = tag.timestamp + interval
        self.latest = max(self.latest, tag.timestamp)
        if tag.keyframe:
            self.last_keyframe = tag.timestamp
            self.keyframes.append(tag)
        reference = self.first_timestamp if self.last_keyframe is None else self.last_keyframe
        if self.latest - reference > self.settings.max_gop_ms:
            raise ValueError("Camera exceeded RTMP_MAX_GOP_SECONDS without an H.264 keyframe")
        for clip in self.active:
            clip.write(tag)
        self.history.append(tag)
        self.buffer_size += tag.size
        cutoff = self.latest - self.settings.overlap_ms
        while len(self.keyframes) >= 2 and self.keyframes[1].timestamp <= cutoff:
            self.keyframes.popleft()
            while self.history[0] is not self.keyframes[0]:
                self.buffer_size -= self.history.popleft().size
        if self.buffer_size > self.settings.max_buffer_bytes:
            raise ValueError("Overlap buffer exceeded RTMP_MAX_BUFFER_MB; check camera bitrate and GOP")
        if not self.active:
            self.open_clip([tag], self.next_boundary + self.settings.overlap_ms)
        if self.latest >= self.next_boundary - self.settings.overlap_ms:
            target = self.next_boundary - self.settings.overlap_ms
            anchor = next((frame for frame in reversed(self.keyframes) if frame.timestamp <= target), None)
            if anchor is None and not self.keyframes:
                # Keep receiving the initial codec/audio preamble until the first video keyframe.
                return
            anchor = anchor or self.keyframes[0]
            replay = []
            found = False
            for buffered in self.history:
                found = found or buffered is anchor
                if found:
                    replay.append(buffered)
            self.open_clip(replay, self.next_boundary + self.settings.interval_ms + self.settings.overlap_ms)
            self.next_boundary += self.settings.interval_ms
        remaining = []
        for clip in self.active:
            if self.latest > clip.end:
                clip.close(complete=True)
            else:
                remaining.append(clip)
        self.active = remaining

    def close(self, complete=True):
        for clip in self.active:
            clip.close(complete)
        self.active.clear()


def control_handler(settings):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format_string, *args):
            # Callback arguments can contain camera-supplied query parameters.
            return

        def do_GET(self):
            if self.path != "/health":
                self.send_error(404)
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":"ready"}')

        def do_POST(self):
            if self.path != "/publish":
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                LOG.warning("Rejected invalid callback Content-Length")
                self.send_error(400)
                return
            if not 0 < length <= 16_384:
                self.send_error(400)
                return
            body = self.rfile.read(length)
            try:
                if self.headers.get("Content-Type", "").startswith("application/json") or body.startswith(b"{"):
                    request = json.loads(body)
                    if not isinstance(request, dict):
                        raise ValueError("Expected a callback object")
                    app, stream = request.get("app"), request.get("stream")
                else:
                    request = parse_qs(body.decode())
                    app = request.get("app", [None])[0]
                    stream = request.get("name", [None])[0]
            except (ValueError, UnicodeError):
                LOG.warning("Rejected malformed publish callback")
                self.send_error(400)
                return
            allowed = app == settings.app and stream == settings.stream
            if not allowed:
                LOG.warning("Rejected publish: application or stream does not match configuration")
            self.send_response(200 if allowed else 403)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"code":0}' if allowed else b'{"code":1}')

    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=("nginx", "srs"), required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings.from_env()
    configure(settings, args.kind, Path("/templates/server.conf"), Path("/runtime/server.conf"))
    def terminate(*_):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, terminate)
    with socket.create_server(("0.0.0.0", 9000)) as server:
        http = ThreadingHTTPServer(("0.0.0.0", 9001), control_handler(settings))
        threading.Thread(target=http.serve_forever, daemon=True).start()
        LOG.info("Ready for %s/%s; recording=%s", settings.app, settings.stream, settings.enabled)
        try:
            while True:
                connection, _ = server.accept()
                with connection, connection.makefile("rb") as source:
                    header = read_header(source)
                    if header is None:
                        continue
                    splitter = Splitter(settings, header)
                    complete = False
                    try:
                        for tag in read_tags(source):
                            splitter.feed(tag)
                        complete = True
                    except SystemExit:
                        complete = True
                        raise
                    finally:
                        splitter.close(complete)
        finally:
            http.shutdown()
            http.server_close()


if __name__ == "__main__":
    main()
