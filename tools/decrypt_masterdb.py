"""Decrypt a SQLCipher-4 encrypted rekordbox master.db into a plain SQLite file.

Pure-Python (hashlib + cryptography). Used only because pyrekordbox is not
installable in this sandbox. Read-only: never writes back to the original.

WAL replay (2026-09-16): rekordbox never checkpoints while it is open, so every
edit made during a session sits in master.db-wal until the app exits. SQLCipher
leaves the WAL framing in plaintext and encrypts each page exactly as it does in
the main file (per-page IV + HMAC over ciphertext, IV and page number), so the
same page routine decrypts WAL frames. `decrypt(..., wal=...)` replays the
committed frames over the decrypted pages, which is what SQLite itself does on
open. Torn tails are cut at the first frame whose salt or checksum disagrees.
"""
from __future__ import annotations

import hashlib
import hmac
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

# Well-known rekordbox 6/7 master.db passphrase (same for every install).
PASSPHRASE = "402fd482c38817c35ffa8ffb8c7d93143b749e7d315df7a81732a1ff43608497"

PAGE_SIZE = 4096
KDF_ITER = 256_000          # SQLCipher 4 default
RESERVE = 80                # 16 IV + 64 HMAC-SHA512
SALT_LEN = 16
KEY_LEN = 32

WAL_HDR = 32
FRAME_HDR = 24
WAL_MAGIC_LE, WAL_MAGIC_BE = 0x377F0682, 0x377F0683


def derive_keys(salt: bytes):
    key = hashlib.pbkdf2_hmac("sha512", PASSPHRASE.encode(), salt, KDF_ITER, KEY_LEN)
    hmac_salt = bytes(b ^ 0x3A for b in salt)
    hmac_key = hashlib.pbkdf2_hmac("sha512", key, hmac_salt, 2, KEY_LEN)
    return key, hmac_key


def decrypt_page(key: bytes, hkey: bytes, page: bytes, pgno: int, verify_hmac: bool = True) -> bytes:
    """One SQLCipher page -> one plain SQLite page (reserve bytes zeroed)."""
    start = SALT_LEN if pgno == 1 else 0
    body = page[start:PAGE_SIZE - RESERVE]
    iv = page[PAGE_SIZE - RESERVE:PAGE_SIZE - RESERVE + 16]
    mac = page[PAGE_SIZE - RESERVE + 16:PAGE_SIZE - RESERVE + 16 + 64]
    if verify_hmac:
        m = hmac.new(hkey, digestmod="sha512")
        m.update(body + iv)
        m.update(pgno.to_bytes(4, "little"))
        if m.digest() != mac:
            raise SystemExit(f"HMAC mismatch on page {pgno}: wrong key or cipher settings")
    dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    plain = dec.update(body) + dec.finalize()
    if pgno == 1:
        plain = b"SQLite format 3\x00" + plain
    return plain + bytes(RESERVE)


@dataclass
class WalReplay:
    frames_seen: int = 0        # frames physically present in the file
    frames_applied: int = 0     # frames inside a committed transaction, valid salt/checksum
    commits: int = 0
    db_pages: int | None = None  # database size after the last commit, in pages
    note: str = ""              # why frames were dropped, if any


def _wal_checksum(data: bytes, s0: int, s1: int, big_endian: bool) -> tuple[int, int]:
    fmt = (">" if big_endian else "<") + f"{len(data) // 4}I"
    words = struct.unpack(fmt, data)
    for i in range(0, len(words), 2):
        s0 = (s0 + words[i] + s1) & 0xFFFFFFFF
        s1 = (s1 + words[i + 1] + s0) & 0xFFFFFFFF
    return s0, s1


def committed_wal_frames(wal: bytes, page_size: int) -> tuple[list[tuple[int, bytes]], WalReplay]:
    """Frames SQLite would apply on open: (pgno, raw page) in order, up to the last commit."""
    rep = WalReplay()
    if len(wal) < WAL_HDR:
        return [], rep
    magic, version, wal_page, _ckpt, salt1, salt2, s0, s1 = struct.unpack(">IIIIIIII", wal[:WAL_HDR])
    if magic not in (WAL_MAGIC_LE, WAL_MAGIC_BE) or wal_page != page_size:
        rep.note = f"WAL ヘッダが想定外 (magic={magic:#x}, page={wal_page})"
        return [], rep
    big = magic == WAL_MAGIC_BE
    if _wal_checksum(wal[:24], 0, 0, big) != (s0, s1):
        rep.note = "WAL ヘッダのチェックサム不一致"
        return [], rep
    frame_len = FRAME_HDR + page_size
    rep.frames_seen = (len(wal) - WAL_HDR) // frame_len
    frames: list[tuple[int, bytes]] = []
    last_commit_idx = -1
    off = WAL_HDR
    for i in range(rep.frames_seen):
        hdr = wal[off:off + FRAME_HDR]
        pgno, commit, f_salt1, f_salt2, c0, c1 = struct.unpack(">IIIIII", hdr)
        page = wal[off + FRAME_HDR:off + frame_len]
        if (f_salt1, f_salt2) != (salt1, salt2):
            rep.note = f"frame {i + 1} の salt が不一致 (ここで打ち切り)"
            break
        s0, s1 = _wal_checksum(hdr[:8], s0, s1, big)
        s0, s1 = _wal_checksum(page, s0, s1, big)
        if (s0, s1) != (c0, c1):
            rep.note = f"frame {i + 1} のチェックサム不一致 (ここで打ち切り)"
            break
        frames.append((pgno, page))
        if commit:
            last_commit_idx = len(frames) - 1
            rep.commits += 1
            rep.db_pages = commit
        off += frame_len
    frames = frames[:last_commit_idx + 1]
    rep.frames_applied = len(frames)
    return frames, rep


def replay_wal(pages: list[bytes], wal: bytes, page_size: int,
               decode: Callable[[int, bytes], bytes]) -> tuple[list[bytes], WalReplay]:
    """Overlay committed WAL frames onto a page list. Later frames win."""
    frames, rep = committed_wal_frames(wal, page_size)
    if not frames:
        return pages, rep
    latest: dict[int, bytes] = {}
    for pgno, raw in frames:
        latest[pgno] = raw
    n = rep.db_pages or len(pages)
    out = list(pages[:n]) + [bytes(page_size)] * max(0, n - len(pages))
    for pgno, raw in latest.items():
        if 1 <= pgno <= n:
            out[pgno - 1] = decode(pgno, raw)
    return out, rep


@dataclass
class DecryptResult:
    n_pages: int
    wal: WalReplay | None = None


def decrypt(src: Path, dst: Path, verify_hmac: bool = True, wal: Path | None = None) -> DecryptResult:
    raw = src.read_bytes()
    salt = raw[:SALT_LEN]
    key, hkey = derive_keys(salt)
    n_pages = len(raw) // PAGE_SIZE
    pages = [decrypt_page(key, hkey, raw[i * PAGE_SIZE:(i + 1) * PAGE_SIZE], i + 1, verify_hmac)
             for i in range(n_pages)]
    rep = None
    if wal is not None and wal.exists():
        pages, rep = replay_wal(pages, wal.read_bytes(), PAGE_SIZE,
                                lambda pgno, page: decrypt_page(key, hkey, page, pgno, verify_hmac))
        if rep.db_pages:
            # the header's page count must agree with the file, or SQLite refuses it
            hdr = bytearray(pages[0])
            struct.pack_into(">I", hdr, 28, len(pages))
            pages[0] = bytes(hdr)
    dst.write_bytes(b"".join(pages))
    return DecryptResult(len(pages), rep)


if __name__ == "__main__":
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    wal_p = src.with_name(src.name + "-wal")
    r = decrypt(src, dst, wal=wal_p)
    print(f"decrypted {r.n_pages} pages -> {dst}")
    if r.wal:
        print(f"WAL: {r.wal.frames_applied}/{r.wal.frames_seen} frames, {r.wal.commits} commits {r.wal.note}")
