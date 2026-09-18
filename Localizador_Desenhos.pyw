from __future__ import annotations

from datetime import datetime
from pathlib import Path
import ctypes
import os
import sys
import traceback

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def message_box(text: str, title: str = "Localizador de arquivo", error: bool = True) -> None:
    if os.name == "nt":
        flags = 0x10 if error else 0x40
        try:
            ctypes.windll.user32.MessageBoxW(None, text, title, flags)
        except Exception:
            pass


def save_crash_log(exc: BaseException) -> str:
    base = Path(os.environ.get("LOCALAPPDATA", str(ROOT))) / "Localizador de arquivo"
    base.mkdir(parents=True, exist_ok=True)
    path = base / "erro.log"
    with path.open("a", encoding="utf-8-sig") as handle:
        handle.write("\n" + "=" * 72 + "\n")
        handle.write(f"Data: {datetime.now():%Y-%m-%d %H:%M:%S}\n")
        handle.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    return str(path)


try:
    import webview  # noqa: F401
except Exception as exc:
    message_box(
        "A biblioteca da interface ainda nao esta instalada.\n\n"
        "Execute 'Instalar Bibliotecas.bat' uma vez e abra o programa novamente.\n\n"
        f"Detalhe: {exc}"
    )
    raise SystemExit(1)

try:
    from app.main import main
    main()
except SystemExit:
    raise
except BaseException as exc:
    log = save_crash_log(exc)
    message_box(f"O programa encontrou um erro inesperado.\n\nLog: {log}\n\nErro: {exc}")
