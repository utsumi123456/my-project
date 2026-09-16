"""Minimal parser for rekordbox ANLZ analysis files (.DAT / .EXT / .2EX).

Only the sections Set Agent needs:
  PPTH  - path of the audio file
  PQTZ  - beat grid (beat number, tempo, time in ms)
  PSSI  - song structure / phrase analysis (masked since rekordbox 6)

Layout follows the Deep Symmetry "DJ Link Ecosystem Analysis" documentation.
All integers are big-endian.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

# ---------------------------------------------------------------- sections

def iter_sections(data: bytes) -> Iterator[tuple[str, bytes]]:
    """Yield (fourcc, raw_section_bytes) for every tagged section in the file."""
    if data[:4] != b"PMAI":
        raise ValueError("not an ANLZ file (missing PMAI header)")
    head_len, _file_len = struct.unpack(">II", data[4:12])
    pos = head_len
    while pos + 12 <= len(data):
        fourcc = data[pos:pos + 4].decode("ascii", "replace")
        _hlen, tlen = struct.unpack(">II", data[pos + 4:pos + 12])
        if tlen == 0:
            break
        yield fourcc, data[pos:pos + tlen]
        pos += tlen


# ---------------------------------------------------------------- beat grid

@dataclass(frozen=True)
class Beat:
    number: int      # 1..4 within the bar
    tempo: float     # BPM at this beat
    time_ms: int     # position in the source audio


def parse_pqtz(section: bytes) -> list[Beat]:
    head_len, _tlen = struct.unpack(">II", section[4:12])
    n = struct.unpack(">I", section[20:24])[0]
    beats = []
    pos = head_len
    for _ in range(n):
        bnum, tempo, t = struct.unpack(">HHI", section[pos:pos + 8])
        beats.append(Beat(bnum, tempo / 100.0, t))
        pos += 8
    return beats


# ---------------------------------------------------------------- phrases

MOOD_NAMES = {1: "high", 2: "mid", 3: "low"}

# kind -> label, per mood (Deep Symmetry documentation)
PHRASE_KINDS = {
    1: {1: "intro", 2: "up", 3: "down", 5: "chorus", 6: "outro"},
    2: {1: "intro", 2: "verse1", 3: "verse2", 4: "verse3", 5: "verse4", 6: "verse5",
        7: "verse6", 8: "bridge", 9: "chorus", 10: "outro"},
    3: {1: "intro", 2: "verse1", 3: "verse2", 4: "verse3", 5: "verse4", 6: "verse5",
        7: "verse6", 8: "bridge", 9: "chorus", 10: "outro"},
}

_PSSI_MASK = bytes.fromhex("CBE1EEFAE5EEADEEE9D2E9EBE1E9F3E8E9F4E1")


@dataclass(frozen=True)
class Phrase:
    index: int
    beat: int          # starting beat (1-based, beat grid index)
    kind: int
    label: str
    fill_start_beat: int | None = None   # beat where a fill begins before the next phrase


@dataclass
class SongStructure:
    mood: int
    end_beat: int
    bank: int
    phrases: list[Phrase] = field(default_factory=list)

    @property
    def mood_name(self) -> str:
        return MOOD_NAMES.get(self.mood, f"mood{self.mood}")


def _unmask_pssi(section: bytes) -> bytes:
    """rekordbox >= 6 XOR-masks everything after len_entries with a rolling key."""
    lene = struct.unpack(">H", section[16:18])[0]
    key = bytes(((b + lene) & 0xFF) for b in _PSSI_MASK)
    body = bytearray(section)
    for i in range(18, len(body)):
        body[i] ^= key[(i - 18) % len(key)]
    return bytes(body)


def _looks_valid(section: bytes) -> bool:
    lene = struct.unpack(">H", section[16:18])[0]
    mood = struct.unpack(">H", section[18:20])[0]
    if mood not in MOOD_NAMES or lene == 0:
        return False
    idx = [struct.unpack(">H", section[32 + 24 * i:34 + 24 * i])[0] for i in range(min(lene, 4))]
    return idx == list(range(1, len(idx) + 1))


def parse_pssi(section: bytes, masked: bool | None = None) -> SongStructure:
    """masked=None auto-detects: rekordbox 7 local files are unmasked (verified
    on real data 2026-09); USB exports / rekordbox 6 may be masked."""
    if masked is None:
        masked = not _looks_valid(section)
    if masked:
        section = _unmask_pssi(section)
        if not _looks_valid(section):
            raise ValueError("PSSI: neither plain nor masked layout validated")
    lene = struct.unpack(">H", section[16:18])[0]
    mood = struct.unpack(">H", section[18:20])[0]
    end_beat = struct.unpack(">H", section[26:28])[0]
    bank = section[30]
    kinds = PHRASE_KINDS.get(mood, {})
    phrases = []
    pos = 32
    for _ in range(lene):
        e = section[pos:pos + 24]
        index, beat, kind = struct.unpack(">HHH", e[0:6])
        fill = e[21]
        beatfill = struct.unpack(">H", e[22:24])[0]
        phrases.append(Phrase(index, beat, kind, kinds.get(kind, f"kind{kind}"),
                              beatfill if fill else None))
        pos += 24
    return SongStructure(mood, end_beat, bank, phrases)


# ---------------------------------------------------------------- file API

@dataclass
class AnlzFile:
    path: str | None = None
    beats: list[Beat] = field(default_factory=list)
    structure: SongStructure | None = None
    sections: list[str] = field(default_factory=list)

    @property
    def has_phrases(self) -> bool:
        return self.structure is not None and len(self.structure.phrases) > 0


def parse_file(p: Path | str) -> AnlzFile:
    data = Path(p).read_bytes()
    out = AnlzFile()
    for fourcc, sec in iter_sections(data):
        out.sections.append(fourcc)
        if fourcc == "PPTH":
            n = struct.unpack(">I", sec[12:16])[0]
            out.path = sec[16:16 + n].decode("utf-16-be", "replace").rstrip("\x00")
        elif fourcc == "PQTZ":
            out.beats = parse_pqtz(sec)
        elif fourcc == "PSSI":
            out.structure = parse_pssi(sec)
    return out


def load_track_analysis(dat_path: Path | str) -> AnlzFile:
    """Merge DAT (beat grid) + EXT/2EX (phrases) that share one stem.

    `dat_path` is the .DAT file the database points at (e.g. .../ANLZ0001.DAT —
    rekordbox increments the index when a track is re-analysed, so the stem must
    come from the DB, never be assumed to be ANLZ0000)."""
    dat = Path(dat_path)
    merged = AnlzFile()
    for suffix in (".DAT", ".EXT", ".2EX"):
        f = dat.with_suffix(suffix)
        if not f.exists():
            continue
        part = parse_file(f)
        merged.sections += [f"{suffix[1:]}:{s}" for s in part.sections]
        merged.path = merged.path or part.path
        merged.beats = merged.beats or part.beats
        merged.structure = merged.structure or part.structure
    return merged
