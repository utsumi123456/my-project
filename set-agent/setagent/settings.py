"""Per-user settings, so the tool remembers how the DJ left it.

Deliberately small and forgiving: a corrupt or unreadable settings file must
never stop the app from starting. Every read falls back to a default, and every
write failure is swallowed — losing a remembered playlist is not worth a crash
on someone else's machine.

Stored at %LOCALAPPDATA%\\SetAgent\\settings.json (Windows) or
~/.config/SetAgent/settings.json elsewhere. Override with SETAGENT_HOME.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


def app_home() -> Path:
    env = os.environ.get("SETAGENT_HOME")
    if env:
        return Path(env)
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "SetAgent"
    return Path.home() / ".config" / "SetAgent"


def _dpapi(data: bytes, protect: bool) -> bytes | None:
    """CryptProtectData / CryptUnprotectData. None on any failure (incl. non-Windows)."""
    try:
        import ctypes
        import ctypes.wintypes as wt

        class BLOB(ctypes.Structure):
            _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        buf = ctypes.create_string_buffer(data, len(data))
        src = BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        dst = BLOB()
        crypt32 = ctypes.windll.crypt32
        fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
        desc = ctypes.c_wchar_p("Set Agent LLM key") if protect else None
        if not fn(ctypes.byref(src), desc, None, None, None, 0, ctypes.byref(dst)):
            return None
        try:
            return ctypes.string_at(dst.pbData, dst.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(dst.pbData)
    except Exception:
        return None


@dataclass
class Settings:
    master_db: str = ""              # manual override when auto-detection fails
    playlist: str = ""
    target: str = "60:00"
    preset: str = "one_drop"
    cap32: bool = True
    curve: str = "(none)"
    level: str = "passive"
    last_export_dir: str = ""
    llm_key: str = ""                # stored as "dpapi:<base64>" where possible
    llm_model: str = ""              # "" = the agent's default (cli: sonnet / api: claude-sonnet-5)
    llm_backend: str = ""            # "" = auto (Claude Code sign-in, then API key), cli, api, off
    claude_exe: str = ""             # manual path to claude.exe when the search fails
    rekordbox_exe: str = ""          # remembered path, for relaunch after export
    window: str = ""                 # "x,y,w,h" of the panel when it was last closed
    set_bpm: str = ""                # the set's tempo as typed ("160"); "" = each track's own

    # ------------------------------------------------------------- llm key
    # The key is a credential on someone else's PC, so it is not written in
    # clear text. DPAPI ties the ciphertext to the Windows account; anywhere
    # else (or if DPAPI refuses) we degrade to plain and say so, because a
    # missing key must never be worse than a broken app.
    def llm_key_plain(self) -> str:
        if not self.llm_key:
            return ""
        if not self.llm_key.startswith("dpapi:"):
            return self.llm_key
        import base64
        raw = _dpapi(base64.b64decode(self.llm_key[6:]), protect=False)
        return raw.decode("utf-8", "replace") if raw else ""

    def set_llm_key(self, key: str) -> str:
        """Returns how it ended up stored: 'dpapi', 'plain' or 'empty'."""
        key = (key or "").strip()
        if not key:
            self.llm_key = ""
            return "empty"
        blob = _dpapi(key.encode("utf-8"), protect=True)
        if blob:
            import base64
            self.llm_key = "dpapi:" + base64.b64encode(blob).decode("ascii")
            return "dpapi"
        self.llm_key = key
        return "plain"

    # ------------------------------------------------------------------ io
    @staticmethod
    def path() -> Path:
        return app_home() / "settings.json"

    @classmethod
    def load(cls) -> "Settings":
        s = cls()
        try:
            raw = json.loads(cls.path().read_text(encoding="utf-8"))
        except Exception:
            return s
        if not isinstance(raw, dict):
            return s
        known = {f.name: f.type for f in fields(cls)}
        for k, v in raw.items():
            if k not in known:
                continue
            cur = getattr(s, k)
            if isinstance(cur, bool):
                if isinstance(v, bool):
                    setattr(s, k, v)
            elif isinstance(cur, str) and isinstance(v, str):
                setattr(s, k, v)
        return s

    def save(self) -> bool:
        try:
            p = self.path()
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2),
                           encoding="utf-8")
            tmp.replace(p)
            return True
        except Exception:
            return False
