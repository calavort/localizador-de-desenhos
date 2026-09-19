from __future__ import annotations

from pathlib import Path
import ctypes
import os
import shutil

from .backend import Backend
from .instancia import focar_janela_existente, reservar_instancia


def main() -> None:
    import webview

    # Duas janelas disputam a mesma pasta do WebView2 e a segunda abre vazia e
    # travada. Em vez de abrir a segunda, traz para a frente a que ja esta la.
    # Se nao achar a janela anterior, abre assim mesmo: clicar no atalho e nao
    # acontecer nada e pior do que arriscar uma segunda janela.
    if not reservar_instancia() and focar_janela_existente():
        return

    root = Path(__file__).resolve().parents[1]
    interface = root / "interface" / "index.html"
    icon = root / "interface" / "localizador.ico"
    local_app_data = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    app_data = local_app_data / "Localizador de arquivo"
    legacy_app_data = local_app_data / "Localizador de Desenhos"
    if legacy_app_data.is_dir() and not app_data.exists():
        try:
            legacy_app_data.replace(app_data)
        except OSError:
            shutil.copytree(legacy_app_data, app_data, dirs_exist_ok=True)
    if os.name == "nt" and os.environ.get("APPDATA"):
        programs = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        legacy_shortcut = programs / "Localizador de Desenhos.lnk"
        current_shortcut = programs / "Localizador de arquivo.lnk"
        if legacy_shortcut.is_file() and not current_shortcut.exists():
            try:
                legacy_shortcut.replace(current_shortcut)
            except OSError:
                pass
    storage = app_data / "WebView2Data"
    storage.mkdir(parents=True, exist_ok=True)

    if os.name == "nt":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Calavort.LocalizadorDesenhos")
        except Exception:
            pass

    backend = Backend(root)
    window = webview.create_window(
        "Localizador de arquivo",
        url=interface.as_uri(),
        js_api=backend,
        width=620,
        height=572,   # 10% mais alta que os 520 de antes
        min_size=(620, 572),
        resizable=True,
        on_top=bool(backend.settings["topmost"]),
        shadow=True,
        background_color="#f5f5f5",
        text_select=False,
    )
    backend._window = window

    def ajustar_janela_ao_aparecer() -> None:
        """Pega o ``hwnd`` e garante que a janela aparece na frente.

        A moldura e a do Windows: barra de titulo, botoes e tamanho minimo saem
        do proprio pywebview, a partir de ``min_size`` e do ``icon`` passado ao
        ``start``. Reescrever isso depois pelo WinForms era o que prendia a
        janela numa largura unica e apagava o botao de maximizar.

        Sobram duas coisas que so o ``hwnd`` resolve. O "sempre visivel" chama
        ``SetWindowPos`` por fora da thread da janela. E o ``ShowWindow``: a
        primeira janela de um processo nasce no estado que quem chamou pediu,
        entao um atalho antigo gravado como minimizado ou escondido abre o
        programa atras de tudo - ou nao abre nada na tela.
        """
        if os.name != "nt":
            return
        try:
            handle = window.native.Handle
            hwnd = int(handle.ToInt64()) if hasattr(handle, "ToInt64") else int(handle)
            backend._set_native_handle(hwnd)
            user32 = ctypes.windll.user32
            user32.ShowWindow(hwnd, 5)  # SW_SHOW
            user32.SetForegroundWindow(hwnd)
            backend._apply_saved_topmost()
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Falha ao preparar a janela")

    window.events.shown += ajustar_janela_ao_aparecer

    webview.start(debug=False, private_mode=False, storage_path=str(storage),
                  icon=str(icon) if icon.exists() else None)


if __name__ == "__main__":
    main()
