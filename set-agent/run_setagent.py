"""Entry point for the packaged Set Agent workbench (PyInstaller).

  SetAgent.exe                  open the workbench (WebView2)
  SetAgent.exe --playlist acid  open a specific playlist
  SetAgent.exe --classic        the old tkinter canvas, as a fallback
  SetAgent.exe --doctor         environment check (shown in a dialog too)

The WebView2 runtime ships with Windows 10/11, so the default path needs no
install on a teammate's PC. --classic stays in the bundle for the machine that
cannot start WebView2 at all: the DJ still gets a working tool, and the message
says which one they are looking at.
"""
import sys

import tools.decrypt_masterdb  # noqa: F401  (keep the decryptor in the bundle)


def _playlist_arg(argv) -> str | None:
    if "--playlist" in argv:
        i = argv.index("--playlist")
        if i + 1 < len(argv):
            return argv[i + 1]
    return None


def main() -> int:
    argv = sys.argv[1:]
    if "--compat" in argv:                        # rekordbox compatibility report, no window
        from tools.probe_compat import main as compat
        return compat([a for a in argv if a != "--compat"])
    if "--doctor" in argv or "--classic" in argv:
        from setagent.gui.timeline import main as classic
        return classic()
    try:
        from setagent.webui.app import main as workbench
        workbench(_playlist_arg(argv))
        return 0
    except Exception as ex:                      # never leave the DJ with nothing
        import traceback
        traceback.print_exc()
        try:
            import tkinter.messagebox as mb
            mb.showwarning("Set Agent",
                           f"新しい画面を開けなかった（{type(ex).__name__}: {ex}）。\n"
                           "従来の画面で起動する。--classic を付ければ次回から直接開ける。")
        except Exception:
            pass
        from setagent.gui.timeline import main as classic
        return classic()


if __name__ == "__main__":
    sys.exit(main())
