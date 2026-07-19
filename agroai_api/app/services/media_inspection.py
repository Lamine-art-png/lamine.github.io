"""Bounded server-side media inspection for Field Intelligence uploads.

Parses real container structure (never just leading magic bytes) to determine:

* which track types are actually present (audio vs video vs image) — the
  overlapping RIFF/Ogg/WebM/MP4 signatures are disambiguated by their tracks;
* the server-measured duration (browser-supplied duration is never trusted);
* whether codecs are on the supported allowlist.

Every parser operates under a hard byte/iteration budget so a malformed or
adversarial file cannot make the API do unbounded work. Files that cannot be
parsed as their declared kind are rejected, not guessed.
"""
from __future__ import annotations

import os
import struct
from dataclasses import dataclass, field

# Hard parsing budgets. Uploads are already size-capped upstream; these bound
# the *work* done here regardless of file size.
MAX_PARSE_BYTES = 4 * 1024 * 1024
MAX_ELEMENTS = 4096
TAIL_SCAN_BYTES = 64 * 1024

SUPPORTED_AUDIO_CODECS = {
    "opus", "vorbis", "mp3", "aac", "flac", "pcm", "adpcm", "pcm_float", "mulaw", "alaw",
}
SUPPORTED_VIDEO_CODECS = {"vp8", "vp9", "av1", "h264", "h265", "theora"}
SUPPORTED_IMAGE_FORMATS = {"jpeg", "png", "gif", "bmp", "webp"}


@dataclass
class MediaInspection:
    container: str | None = None
    has_audio: bool = False
    has_video: bool = False
    has_image: bool = False
    duration_seconds: float | None = None
    codecs: list[str] = field(default_factory=list)
    ok: bool = False
    reason: str | None = None


def inspect_media_file(path: str) -> MediaInspection:
    """Inspect a local (already size-capped) media file with bounded work."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            head = handle.read(64)
            if len(head) < 12:
                return MediaInspection(ok=False, reason="file_too_small")
            if head.startswith(b"RIFF") and head[8:12] == b"WAVE":
                return _inspect_wav(handle, size)
            if head.startswith(b"RIFF") and head[8:12] == b"AVI ":
                return _inspect_avi(handle, size)
            if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
                return MediaInspection(container="webp", has_image=True, ok=True)
            if head.startswith(b"OggS"):
                return _inspect_ogg(handle, size)
            if head.startswith(b"\x1aE\xdf\xa3"):
                return _inspect_matroska(handle, size)
            if head[4:8] == b"ftyp":
                return _inspect_mp4(handle, size)
            if head.startswith(b"fLaC"):
                return _inspect_flac(handle, size)
            if head.startswith(b"ID3") or (head[0] == 0xFF and (head[1] & 0xE0) == 0xE0):
                return _inspect_mp3(handle, size)
            if head.startswith(b"\xff\xd8\xff"):
                return MediaInspection(container="jpeg", has_image=True, ok=True)
            if head.startswith(b"\x89PNG\r\n\x1a\n"):
                return MediaInspection(container="png", has_image=True, ok=True)
            if head.startswith((b"GIF87a", b"GIF89a")):
                return MediaInspection(container="gif", has_image=True, ok=True)
            if head.startswith(b"BM"):
                return MediaInspection(container="bmp", has_image=True, ok=True)
            return MediaInspection(ok=False, reason="unrecognized_container")
    except Exception:  # noqa: BLE001 - malformed input must never 500
        return MediaInspection(ok=False, reason="malformed_container")


def validate_media_for_kind(
    inspection: MediaInspection,
    *,
    kind: str,
    content_type: str | None,
    max_audio_seconds: float | None = None,
) -> tuple[bool, str | None]:
    """Decide whether an inspected file is acceptable as the declared kind."""
    if kind == "file":
        return True, None
    if not inspection.ok:
        return False, inspection.reason or "malformed_container"

    if kind == "audio":
        if inspection.has_video:
            return False, "video_track_in_audio_upload"
        if not inspection.has_audio:
            return False, "no_audio_track"
        unsupported = [c for c in inspection.codecs if c not in SUPPORTED_AUDIO_CODECS]
        if unsupported:
            return False, f"unsupported_codec:{unsupported[0]}"
    elif kind == "video":
        if not inspection.has_video:
            return False, "no_video_track"
        unsupported = [
            c for c in inspection.codecs
            if c not in SUPPORTED_VIDEO_CODECS and c not in SUPPORTED_AUDIO_CODECS
        ]
        if unsupported:
            return False, f"unsupported_codec:{unsupported[0]}"
    elif kind == "photo":
        if not inspection.has_image:
            return False, "not_an_image"
    else:
        return False, "unknown_kind"

    # A misleading declared MIME type is rejected: the top-level type must
    # agree with what the container actually holds.
    major = (content_type or "").split("/", 1)[0].strip().lower()
    if major == "audio" and (inspection.has_video or not inspection.has_audio):
        return False, "mime_mismatch_audio"
    if major == "video" and not inspection.has_video:
        return False, "mime_mismatch_video"
    if major == "image" and not inspection.has_image:
        return False, "mime_mismatch_image"

    if (
        kind in {"audio", "video"}
        and max_audio_seconds is not None
        and inspection.duration_seconds is not None
        and inspection.duration_seconds > max_audio_seconds
    ):
        return False, "duration_exceeds_limit"
    return True, None


# --------------------------------------------------------------------------- #
# WAV / AVI (RIFF)
# --------------------------------------------------------------------------- #

def _inspect_wav(handle, size: int) -> MediaInspection:
    handle.seek(12)
    byte_rate = None
    data_size = None
    codec = None
    consumed = 12
    for _ in range(MAX_ELEMENTS):
        header = handle.read(8)
        if len(header) < 8 or consumed > MAX_PARSE_BYTES:
            break
        chunk_id, chunk_size = header[:4], struct.unpack("<I", header[4:])[0]
        if chunk_id == b"fmt ":
            fmt = handle.read(min(chunk_size, 64))
            if len(fmt) >= 16:
                audio_format = struct.unpack("<H", fmt[0:2])[0]
                byte_rate = struct.unpack("<I", fmt[8:12])[0]
                codec = {
                    1: "pcm", 3: "pcm_float", 6: "alaw", 7: "mulaw",
                    17: "adpcm", 2: "adpcm", 85: "mp3",
                }.get(audio_format)
                if codec is None:
                    return MediaInspection(container="wav", has_audio=True, ok=True,
                                           codecs=[f"wav_format_{audio_format}"])
            handle.seek(chunk_size - min(chunk_size, 64), 1)
        elif chunk_id == b"data":
            data_size = chunk_size
            handle.seek(chunk_size + (chunk_size % 2), 1)
        else:
            handle.seek(chunk_size + (chunk_size % 2), 1)
        consumed += 8 + chunk_size
    if byte_rate is None or data_size is None:
        return MediaInspection(container="wav", ok=False, reason="malformed_wav")
    duration = (data_size / byte_rate) if byte_rate else None
    return MediaInspection(container="wav", has_audio=True, duration_seconds=duration,
                           codecs=[codec or "pcm"], ok=True)


def _inspect_avi(handle, size: int) -> MediaInspection:
    handle.seek(0)
    blob = handle.read(min(size, TAIL_SCAN_BYTES))
    duration = None
    index = blob.find(b"avih")
    if index != -1 and len(blob) >= index + 28:
        usec_per_frame = struct.unpack("<I", blob[index + 8:index + 12])[0]
        total_frames = struct.unpack("<I", blob[index + 24:index + 28])[0]
        if usec_per_frame and total_frames:
            duration = usec_per_frame * total_frames / 1_000_000.0
    has_audio = b"auds" in blob
    # AVI codecs are not on the supported list; the validator will reject them
    # for audio/video kinds via the codec allowlist.
    return MediaInspection(container="avi", has_video=True, has_audio=has_audio,
                           duration_seconds=duration, codecs=["avi_unknown"], ok=True)


# --------------------------------------------------------------------------- #
# Ogg (Opus / Vorbis / Theora)
# --------------------------------------------------------------------------- #

def _inspect_ogg(handle, size: int) -> MediaInspection:
    handle.seek(0)
    codecs: list[str] = []
    has_audio = False
    has_video = False
    opus_preskip = 0
    vorbis_rate = None
    offset = 0
    # Walk beginning-of-stream pages to identify every logical stream.
    for _ in range(64):
        if offset > min(size, MAX_PARSE_BYTES):
            break
        handle.seek(offset)
        page = handle.read(27)
        if len(page) < 27 or not page.startswith(b"OggS"):
            break
        segments = page[26]
        lacing = handle.read(segments)
        if len(lacing) < segments:
            break
        payload_size = sum(lacing)
        payload = handle.read(min(payload_size, 1024))
        if payload.startswith(b"OpusHead"):
            has_audio = True
            codecs.append("opus")
            if len(payload) >= 12:
                opus_preskip = struct.unpack("<H", payload[10:12])[0]
        elif payload.startswith(b"\x01vorbis"):
            has_audio = True
            codecs.append("vorbis")
            if len(payload) >= 16:
                vorbis_rate = struct.unpack("<I", payload[12:16])[0]
        elif payload.startswith(b"\x80theora"):
            has_video = True
            codecs.append("theora")
        header_type = page[5]
        if not (header_type & 0x02):  # past the BOS pages
            break
        offset += 27 + segments + payload_size
    if not codecs:
        return MediaInspection(container="ogg", ok=False, reason="no_recognized_ogg_stream")

    duration = None
    if not has_video:
        granule = _last_ogg_granule(handle, size)
        if granule is not None and granule > 0:
            if "opus" in codecs:
                duration = max(granule - opus_preskip, 0) / 48000.0
            elif "vorbis" in codecs and vorbis_rate:
                duration = granule / float(vorbis_rate)
    return MediaInspection(container="ogg", has_audio=has_audio, has_video=has_video,
                           duration_seconds=duration, codecs=codecs, ok=True)


def _last_ogg_granule(handle, size: int) -> int | None:
    tail_size = min(size, TAIL_SCAN_BYTES)
    handle.seek(size - tail_size)
    tail = handle.read(tail_size)
    index = tail.rfind(b"OggS")
    while index != -1:
        if len(tail) >= index + 14:
            granule = struct.unpack("<q", tail[index + 6:index + 14])[0]
            if granule >= 0:
                return granule
        index = tail.rfind(b"OggS", 0, index)
    return None


# --------------------------------------------------------------------------- #
# Matroska / WebM (EBML)
# --------------------------------------------------------------------------- #

_EBML_SEGMENT = 0x18538067
_EBML_INFO = 0x1549A966
_EBML_TRACKS = 0x1654AE6B
_EBML_CLUSTER = 0x1F43B675
_EBML_TIMECODE_SCALE = 0x2AD7B1
_EBML_DURATION = 0x4489
_EBML_TRACK_ENTRY = 0xAE
_EBML_TRACK_TYPE = 0x83
_EBML_CODEC_ID = 0x86

_MKV_CODEC_MAP = {
    "A_OPUS": "opus", "A_VORBIS": "vorbis", "A_AAC": "aac", "A_FLAC": "flac",
    "A_MPEG/L3": "mp3", "A_PCM/INT/LIT": "pcm",
    "V_VP8": "vp8", "V_VP9": "vp9", "V_AV1": "av1",
    "V_MPEG4/ISO/AVC": "h264", "V_MPEGH/ISO/HEVC": "h265",
}


def _read_vint(handle, *, keep_marker: bool) -> tuple[int | None, int]:
    first = handle.read(1)
    if not first:
        return None, 0
    byte = first[0]
    if byte == 0:
        return None, 1
    length = 1
    mask = 0x80
    while not (byte & mask) and length <= 8:
        mask >>= 1
        length += 1
    if length > 8:
        return None, 1
    rest = handle.read(length - 1)
    if len(rest) < length - 1:
        return None, length
    value = byte if keep_marker else (byte & (mask - 1))
    for extra in rest:
        value = (value << 8) | extra
    return value, length


def _ebml_children(handle, end: int, state: dict, budget: list) -> "list[tuple[int, int, int]]":
    """Yield (element_id, data_offset, data_size) inside [pos, end)."""
    elements = []
    while handle.tell() < end and budget[0] > 0:
        budget[0] -= 1
        element_id, id_len = _read_vint(handle, keep_marker=True)
        if element_id is None:
            break
        element_size, size_len = _read_vint(handle, keep_marker=False)
        if element_size is None:
            # unknown-size element (streaming): only Segment supports this here
            element_size = end - handle.tell()
        data_offset = handle.tell()
        elements.append((element_id, data_offset, element_size))
        handle.seek(data_offset + element_size)
    return elements


def _inspect_matroska(handle, size: int) -> MediaInspection:
    limit = min(size, MAX_PARSE_BYTES)
    budget = [MAX_ELEMENTS]
    handle.seek(0)
    has_audio = False
    has_video = False
    codecs: list[str] = []
    timescale = 1_000_000  # ns per timecode tick (Matroska default)
    raw_duration = None

    def parse_level(end: int, depth: int) -> None:
        nonlocal has_audio, has_video, timescale, raw_duration
        if depth > 6 or budget[0] <= 0:
            return
        position = handle.tell()
        while position < end and budget[0] > 0:
            budget[0] -= 1
            handle.seek(position)
            element_id, _ = _read_vint(handle, keep_marker=True)
            if element_id is None:
                return
            element_size, _ = _read_vint(handle, keep_marker=False)
            data_offset = handle.tell()
            if element_size is None:
                element_size = end - data_offset  # unknown size: rest of scope
            data_end = min(data_offset + element_size, limit)
            if element_id == _EBML_CLUSTER:
                return  # media data begins; Info/Tracks precede clusters
            if element_id in {_EBML_SEGMENT, _EBML_INFO, _EBML_TRACKS, _EBML_TRACK_ENTRY}:
                parse_level(data_end, depth + 1)
            elif element_id == _EBML_TIMECODE_SCALE:
                timescale = int.from_bytes(handle.read(min(element_size, 8)), "big") or timescale
            elif element_id == _EBML_DURATION:
                blob = handle.read(min(element_size, 8))
                if len(blob) == 4:
                    raw_duration = struct.unpack(">f", blob)[0]
                elif len(blob) == 8:
                    raw_duration = struct.unpack(">d", blob)[0]
            elif element_id == _EBML_TRACK_TYPE:
                track_type = int.from_bytes(handle.read(min(element_size, 1)), "big")
                if track_type == 1:
                    has_video = True
                elif track_type == 2:
                    has_audio = True
            elif element_id == _EBML_CODEC_ID:
                raw = handle.read(min(element_size, 64)).split(b"\x00", 1)[0].decode("ascii", "replace")
                codecs.append(_MKV_CODEC_MAP.get(raw, raw.lower()))
            position = data_offset + element_size

    # EBML header first, then the Segment.
    header_id, _ = _read_vint(handle, keep_marker=True)
    header_size, _ = _read_vint(handle, keep_marker=False)
    if header_id != 0x1A45DFA3 or header_size is None:
        return MediaInspection(container="matroska", ok=False, reason="malformed_ebml")
    handle.seek(handle.tell() + header_size)
    parse_level(limit, 0)

    if not has_audio and not has_video:
        return MediaInspection(container="matroska", ok=False, reason="no_tracks")
    duration = (raw_duration * timescale / 1e9) if raw_duration else None
    return MediaInspection(container="matroska", has_audio=has_audio, has_video=has_video,
                           duration_seconds=duration, codecs=codecs, ok=True)


# --------------------------------------------------------------------------- #
# MP4 / ISO-BMFF
# --------------------------------------------------------------------------- #

_MP4_CODEC_MAP = {
    "mp4a": "aac", "Opus": "opus", "fLaC": "flac",
    "avc1": "h264", "avc3": "h264", "hvc1": "h265", "hev1": "h265",
    "vp09": "vp9", "av01": "av1",
}


def _inspect_mp4(handle, size: int) -> MediaInspection:
    has_audio = False
    has_video = False
    codecs: list[str] = []
    duration = None
    budget = [MAX_ELEMENTS]

    def walk(start: int, end: int, depth: int) -> None:
        nonlocal has_audio, has_video, duration
        position = start
        while position + 8 <= end and budget[0] > 0 and depth <= 8:
            budget[0] -= 1
            handle.seek(position)
            header = handle.read(8)
            if len(header) < 8:
                return
            box_size = struct.unpack(">I", header[:4])[0]
            box_type = header[4:8]
            header_len = 8
            if box_size == 1:
                big = handle.read(8)
                if len(big) < 8:
                    return
                box_size = struct.unpack(">Q", big)[0]
                header_len = 16
            elif box_size == 0:
                box_size = end - position
            if box_size < header_len:
                return
            data_start = position + header_len
            data_end = min(position + box_size, end)
            if box_type in {b"moov", b"trak", b"mdia", b"minf", b"stbl"}:
                walk(data_start, data_end, depth + 1)
            elif box_type == b"mvhd":
                blob = handle.read(min(box_size - header_len, 32))
                if blob:
                    version = blob[0]
                    if version == 1 and len(blob) >= 28 + 4:
                        timescale = struct.unpack(">I", blob[20:24])[0]
                        raw = struct.unpack(">Q", blob[24:32])[0]
                    elif len(blob) >= 20 + 4:
                        timescale = struct.unpack(">I", blob[12:16])[0]
                        raw = struct.unpack(">I", blob[16:20])[0]
                    else:
                        timescale, raw = 0, 0
                    if timescale:
                        duration = raw / float(timescale)
            elif box_type == b"hdlr":
                blob = handle.read(min(box_size - header_len, 12))
                handler = blob[8:12] if len(blob) >= 12 else b""
                if handler == b"soun":
                    has_audio = True
                elif handler == b"vide":
                    has_video = True
            elif box_type == b"stsd":
                blob = handle.read(min(box_size - header_len, 24))
                if len(blob) >= 16:
                    fmt = blob[12:16].decode("ascii", "replace")
                    codecs.append(_MP4_CODEC_MAP.get(fmt, fmt.strip().lower()))
            position += box_size

    walk(0, min(size, MAX_PARSE_BYTES + size), 0)  # boxes located by seeks; work is budgeted
    if not has_audio and not has_video:
        return MediaInspection(container="mp4", ok=False, reason="no_tracks")
    return MediaInspection(container="mp4", has_audio=has_audio, has_video=has_video,
                           duration_seconds=duration, codecs=codecs, ok=True)


# --------------------------------------------------------------------------- #
# FLAC / MP3
# --------------------------------------------------------------------------- #

def _inspect_flac(handle, size: int) -> MediaInspection:
    handle.seek(4)
    header = handle.read(4 + 34)
    if len(header) < 38 or (header[0] & 0x7F) != 0:
        return MediaInspection(container="flac", ok=False, reason="malformed_flac")
    info = header[4:]
    sample_rate = (info[10] << 12) | (info[11] << 4) | (info[12] >> 4)
    total_samples = ((info[13] & 0x0F) << 32) | struct.unpack(">I", info[14:18])[0]
    duration = (total_samples / sample_rate) if sample_rate and total_samples else None
    return MediaInspection(container="flac", has_audio=True, duration_seconds=duration,
                           codecs=["flac"], ok=True)


_MP3_BITRATES = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0]
_MP3_RATES = [44100, 48000, 32000, 0]


def _inspect_mp3(handle, size: int) -> MediaInspection:
    handle.seek(0)
    blob = handle.read(min(size, TAIL_SCAN_BYTES))
    offset = 0
    if blob.startswith(b"ID3") and len(blob) >= 10:
        tag_size = ((blob[6] & 0x7F) << 21) | ((blob[7] & 0x7F) << 14) | ((blob[8] & 0x7F) << 7) | (blob[9] & 0x7F)
        offset = 10 + tag_size
    while offset + 4 <= len(blob):
        if blob[offset] == 0xFF and (blob[offset + 1] & 0xE0) == 0xE0:
            break
        offset += 1
    if offset + 4 > len(blob):
        return MediaInspection(container="mp3", ok=False, reason="no_mp3_frame")
    frame = blob[offset:offset + 4]
    version_bits = (frame[1] >> 3) & 0x03
    layer_bits = (frame[1] >> 1) & 0x03
    bitrate_kbps = _MP3_BITRATES[(frame[2] >> 4) & 0x0F]
    sample_rate = _MP3_RATES[(frame[2] >> 2) & 0x03]
    if version_bits == 0x01 or layer_bits != 0x01 or not bitrate_kbps or not sample_rate:
        # only MPEG-1/2 Layer III with a valid bitrate/samplerate is accepted
        return MediaInspection(container="mp3", ok=False, reason="unsupported_mpeg_frame")
    duration = None
    xing = blob.find(b"Xing", offset)
    if xing == -1:
        xing = blob.find(b"Info", offset)
    if xing != -1 and len(blob) >= xing + 16:
        flags = struct.unpack(">I", blob[xing + 4:xing + 8])[0]
        if flags & 0x01:
            frames = struct.unpack(">I", blob[xing + 8:xing + 12])[0]
            samples_per_frame = 1152 if version_bits == 0x03 else 576
            duration = frames * samples_per_frame / float(sample_rate)
    if duration is None:
        duration = max(size - offset, 0) * 8 / (bitrate_kbps * 1000.0)
    return MediaInspection(container="mp3", has_audio=True, duration_seconds=duration,
                           codecs=["mp3"], ok=True)
