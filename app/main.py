from __future__ import annotations

from pathlib import Path
import ctypes
import os
import shutil

from .backend import Backend
from .instancia import aviso, encerrar_webview_preso, focar_janela_existente, reservar_instancia


def main() -> None:
    import webview

    # Duas janelas disputam a mesma pasta do WebView2 e a segunda abre vazia e
    # travada. Em vez de abrir a segunda, traz para a frente a que ja esta la.
    if not reservar_instancia():
        focar_janela_existente()
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
    backend.window = window
    def apply_native_window_settings() -> None:
        if os.name != "nt":
            return
        try:
            from System import Action
            from System.Drawing import Icon, Size

            def assign() -> None:
                if icon.exists():
                    native_icon = Icon(str(icon))
                    window.native.Icon = native_icon
                    window.native.ShowIcon = True
                    window._localizador_icon = native_icon
                locked_width = window.native.Width
                window.native.MinimumSize = Size(locked_width, 572)
                window.native.MaximumSize = Size(locked_width, 32767)
                window.native.MaximizeBox = False
                handle = window.native.Handle
                backend.set_native_handle(int(handle.ToInt64()) if hasattr(handle, "ToInt64") else int(handle))

            if window.native.InvokeRequired:
                window.native.Invoke(Action(assign))
            else:
                assign()
            backend.apply_saved_topmost()
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Falha ao configurar a janela nativa")

    window.events.shown += apply_native_window_settings

    def vigiar_carregamento(janela) -> None:
        """Janela em branco e travada nao pode ficar sem explicacao.

        Se a pagina nao carregou, o WebView2 nao subiu - na pratica, sobrou um
        msedgewebview2.exe da execucao anterior segurando a pasta de dados.
        A varredura so acontece aqui, no caminho de falha, para nao custar
        nada na abertura normal.
        """
        try:
            if janela.events.loaded.wait(12):
                return
        except Exception:
            return
        encerrados = encerrar_webview_preso(str(storage))
        aviso(
            "A interface nao carregou porque a pasta de dados do WebView2 estava "
            "em uso por um processo da execucao anterior.\n\n"
            + (f"Ja encerrei {encerrados} processo(s). " if encerrados else "")
            + "Abra o Localizador de arquivo novamente."
        )
        try:
            janela.destroy()
        except Exception:
            pass

    webview.start(vigiar_carregamento, window, debug=False, private_mode=False,
                  storage_path=str(storage), icon=str(icon) if icon.exists() else None)


if __name__ == "__main__":
    main()
