"""Decrypt a SQLCipher-4 encrypted rekordbox master.db into a plain SQLite file.

Pure-Python (hashlib + cryptography). Used only because pyrekordbox is not
installable in this sandbox. Read-only: never writes back to the original.
"""
import hashlib
import hmac
import sys
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

# Well-known rekordbox 6/7 master.db passphrase (same for every install).
PASSPHRASE = "402fd482c38817c35ffa8ffb8c7d93143b749e7d315df7a81732a1ff43608497"

PAGE_SIZE = 4096
KDF_ITER = 256_000          # SQLCipher 4 default
RESERVE = 80                # 16 IV + 64 HMAC-SHA512
SALT_LEN = 16
KEY_LEN = 32


def derive_keys(salt: bytes):
    key = hashlib.pbkdf2_hmac("sha512", PASSPHRASE.encode(), salt, KDF_ITER, KEY_LEN)
    hmac_salt = bytes(b ^ 0x3A for b in salt)
    hmac_key = hashlib.pbkdf2_hmac("sha512", key, hmac_salt, 2, KEY_LEN)
    return key, hmac_key


def decrypt(src: Path, dst: Path, verify_hmac: bool = True) -> int:
    raw = src.read_bytes()
    salt = raw[:SALT_LEN]
    key, hkey = derive_keys(salt)
    n_pages = len(raw) // PAGE_SIZE
    out = bytearray()
    for i in range(n_pages):
        page = raw[i * PAGE_SIZE:(i + 1) * PAGE_SIZE]
        start = SALT_LEN if i == 0 else 0
        body = page[start:PAGE_SIZE - RESERVE]
        iv = page[PAGE_SIZE - RESERVE:PAGE_SIZE - RESERVE + 16]
        mac = page[PAGE_SIZE - RESERVE + 16:PAGE_SIZE - RESERVE + 16 + 64]
        if verify_hmac:
            m = hmac.new(hkey, digestmod="sha512")
            m.update(body + iv)
            m.update((i + 1).to_bytes(4, "little"))
            if m.digest() != mac:
                raise SystemExit(f"HMAC mismatch on page {i+1}: wrong key or cipher settings")
        dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        plain = dec.update(body) + dec.finalize()
        if i == 0:
            plain = b"SQLite format 3\x00" + plain
        out += plain + bytes(RESERVE)
    dst.write_bytes(bytes(out))
    return n_pages


if __name__ == "__main__":
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    n = decrypt(src, dst)
    print(f"decrypted {n} pages -> {dst}")
