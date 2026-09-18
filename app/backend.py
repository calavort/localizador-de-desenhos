from __future__ import annotations

from pathlib import Path
import ctypes
import json
import os
import re
import subprocess
import sys
import tempfile
import threading

from .search_service import (find_latest_pdfs, iter_file_matches, parse_suffixes,
                             relevance, split_terms)
from .updater import UpdateService

DEFAULT_ROOT = r"C:\Users\joliveira\Documents\DETALHAMENTO\GATO DO MATO"


class Backend:
    def __init__(self, app_root: Path):
        self.app_root = app_root
        self.window = None
        self.native_handle: int | None = None
        self.results: list[Path] = []
        self.result_folders: list[Path] = []
        self.result_dwgs: list[list[Path]] = []
        self.result_data: list[dict] = []
        self.config_dir = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Localizador de arquivo"
        self.config_file = self.config_dir / "configuracoes.json"
        self.settings = self._load_settings()
        self.updates = UpdateService(app_root)
        # Guia Especifica: a varredura roda numa thread e a interface busca o
        # que ja apareceu, para nao travar a janela em pasta grande.
        self.file_hits: list[dict] = []
        self.file_lock = threading.Lock()
        self.file_stop = threading.Event()
        self.file_thread: threading.Thread | None = None
        self.file_state = {"running": False, "scanned": 0, "truncated": False, "message": ""}
        self.file_terms: list[str] = []

    def _load_settings(self) -> dict:
        # search_root e a pasta da guia Especifica: fica separada da pasta dos
        # desenhos, senao escolher uma trocaria a outra sem querer.
        settings = {"drawing_root": DEFAULT_ROOT, "topmost": True, "search_root": ""}
        try:
            saved = json.loads(self.config_file.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                settings.update({key: saved[key] for key in settings.keys() & saved.keys()})
        except (OSError, ValueError, TypeError):
            pass
        return settings

    def _save_settings(self) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.config_file.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.settings, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.config_file)

    def ready(self) -> dict:
        # Abrir o programa e a hora certa de arrumar a casa: apagar o que a
        # atualizacao anterior deixou para tras e instalar, sem pedir clique,
        # um pacote que o usuario tenha largado na pasta atualizacao/.
        aviso = self.updates.cleanup_leftovers()
        pendente = self.updates.auto_install_manual()
        if pendente.get("started") and self.window is not None:
            threading.Timer(.25, self.window.destroy).start()
        return {
            "ok": True,
            "root": self.settings["drawing_root"],
            "searchRoot": self.settings.get("search_root", ""),
            "version": self.updates.version,
            "topmost": bool(self.settings["topmost"]),
            "libraryWarning": aviso,
            "autoUpdate": pendente,
        }

    def _apply_topmost(self, enabled: bool) -> bool:
        if self.window is None:
            return False

        enabled = bool(enabled)
        if os.name != "nt":
            try:
                self.window.on_top = enabled
                return True
            except Exception:
                return False

        try:
            hwnd = int(self.native_handle or 0)
            if not hwnd or not ctypes.windll.user32.IsWindow(hwnd):
                return False
            insert_after = -1 if enabled else -2
            flags = 0x0001 | 0x0002 | 0x0040  # SWP_NOSIZE | SWP_NOMOVE | SWP_SHOWWINDOW
            if ctypes.windll.user32.SetWindowPos(hwnd, insert_after, 0, 0, 0, 0, flags):
                style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
                return bool(style & 0x00000008) == enabled  # WS_EX_TOPMOST
        except Exception:
            pass
        return False

    def set_native_handle(self, hwnd: int) -> None:
        self.native_handle = int(hwnd)

    def apply_saved_topmost(self) -> bool:
        return self._apply_topmost(bool(self.settings["topmost"]))

    def set_topmost(self, value: bool) -> dict:
        enabled = bool(value)
        self.settings["topmost"] = enabled
        self._save_settings()
        return {"ok": True, "topmost": enabled, "applied": self._apply_topmost(enabled)}

    @staticmethod
    def _powershell_executable() -> str:
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        candidate = Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        return str(candidate) if candidate.is_file() else "powershell.exe"

    @staticmethod
    def _hidden_creation_flags() -> int:
        return getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if os.name == "nt" else 0

    def _powershell_folder_dialog(self, initial: str) -> str | None:
        initial = initial if Path(initial).is_dir() else str(Path.home())
        with tempfile.TemporaryDirectory(prefix="localizador_pasta_") as temporary:
            result_file = Path(temporary) / "pasta.txt"
            environment = os.environ.copy()
            environment["LOCALIZADOR_RESULTADO"] = str(result_file)
            environment["LOCALIZADOR_INICIAL"] = initial
            # Seletor de pasta no estilo do Explorer (IFileOpenDialog com
            # FOS_PICKFOLDERS). O FolderBrowserDialog do .NET Framework, usado
            # antes, abre a arvorezinha antiga do Windows XP.
            script = r"""
Add-Type -Language CSharp -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

public static class PastaModerna {
  [ComImport, Guid("42f85136-db7e-439c-85f1-e4075d135fc8"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IFileDialog {
    [PreserveSig] int Show(IntPtr parent);
    void SetFileTypes(uint c, IntPtr rg); void SetFileTypeIndex(uint i); void GetFileTypeIndex(out uint i);
    void Advise(IntPtr p, out uint c); void Unadvise(uint c);
    void SetOptions(uint fos); void GetOptions(out uint fos);
    void SetDefaultFolder(IShellItem si); void SetFolder(IShellItem si);
    void GetFolder(out IShellItem si); void GetCurrentSelection(out IShellItem si);
    void SetFileName([MarshalAs(UnmanagedType.LPWStr)] string n);
    void GetFileName([MarshalAs(UnmanagedType.LPWStr)] out string n);
    void SetTitle([MarshalAs(UnmanagedType.LPWStr)] string t);
    void SetOkButtonLabel([MarshalAs(UnmanagedType.LPWStr)] string t);
    void SetFileNameLabel([MarshalAs(UnmanagedType.LPWStr)] string t);
    void GetResult(out IShellItem si);
    void AddPlace(IShellItem si, int alignment); void SetDefaultExtension([MarshalAs(UnmanagedType.LPWStr)] string e);
    void Close(int hr); void SetClientGuid(ref Guid g); void ClearClientData(); void SetFilter(IntPtr f);
  }
  [ComImport, Guid("43826d1e-e718-42ee-bc55-a1e261c37bfe"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IShellItem {
    void BindToHandler(IntPtr bc, ref Guid bhid, ref Guid riid, out IntPtr ppv);
    void GetParent(out IShellItem si);
    void GetDisplayName(uint sigdn, [MarshalAs(UnmanagedType.LPWStr)] out string name);
    void GetAttributes(uint mask, out uint attrs);
    void Compare(IShellItem si, uint hint, out int order);
  }
  [ComImport, Guid("DC1C5A9C-E88A-4dde-A5A1-60F82A20AEF7")] class FileOpenDialog { }

  [DllImport("shell32.dll", CharSet = CharSet.Unicode, PreserveSig = false)]
  static extern void SHCreateItemFromParsingName(string path, IntPtr bc, ref Guid riid,
    [MarshalAs(UnmanagedType.Interface)] out IShellItem item);

  const uint FOS_PICKFOLDERS = 0x20, FOS_FORCEFILESYSTEM = 0x40, FOS_NOCHANGEDIR = 0x8;
  const uint SIGDN_FILESYSPATH = 0x80058000;

  public static string Escolher(string titulo, string inicial) {
    IFileDialog dialogo = (IFileDialog)new FileOpenDialog();
    uint opcoes; dialogo.GetOptions(out opcoes);
    dialogo.SetOptions(opcoes | FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM | FOS_NOCHANGEDIR);
    if (!string.IsNullOrEmpty(titulo)) dialogo.SetTitle(titulo);
    if (!string.IsNullOrEmpty(inicial) && System.IO.Directory.Exists(inicial)) {
      try {
        Guid iid = typeof(IShellItem).GUID; IShellItem item;
        SHCreateItemFromParsingName(inicial, IntPtr.Zero, ref iid, out item);
        dialogo.SetFolder(item);
      } catch { }
    }
    if (dialogo.Show(IntPtr.Zero) != 0) return "";
    IShellItem escolhido; dialogo.GetResult(out escolhido);
    string caminho; escolhido.GetDisplayName(SIGDN_FILESYSPATH, out caminho);
    return caminho ?? "";
  }
}
'@
$selecionada = [PastaModerna]::Escolher('Selecione a pasta de busca', $env:LOCALIZADOR_INICIAL)
[System.IO.File]::WriteAllText($env:LOCALIZADOR_RESULTADO, $selecionada, [System.Text.UTF8Encoding]::new($false))
"""
            completed = subprocess.run(
                [self._powershell_executable(), "-NoLogo", "-NoProfile", "-STA", "-Command", script],
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=self._hidden_creation_flags(),
                timeout=3600,
                check=False,
            )
            if completed.returncode != 0 or not result_file.is_file():
                return None
            return result_file.read_text(encoding="utf-8-sig").strip()

    def _pywebview_folder_dialog(self, initial: str) -> str:
        if self.window is None:
            return ""
        try:
            import webview

            selected = self.window.create_file_dialog(
                webview.FileDialog.FOLDER,
                directory=initial if Path(initial).is_dir() else str(Path.home()),
            )
            if not selected:
                return ""
            return str(selected[0] if isinstance(selected, (list, tuple)) else selected)
        except Exception:
            return ""

    def choose_folder(self, target: str = "drawing_root") -> dict:
        """target diz qual pasta esta sendo escolhida: a dos desenhos (guia
        Geral) ou a da busca livre (guia Especifica)."""
        chave = "search_root" if str(target) == "search_root" else "drawing_root"
        initial = str(self.settings.get(chave) or self.settings["drawing_root"])
        selected: str | None = None
        restore_topmost = bool(self.settings["topmost"])
        if os.name == "nt":
            self._apply_topmost(False)
            try:
                selected = self._powershell_folder_dialog(initial)
            finally:
                self._apply_topmost(restore_topmost)
        if selected is None:
            selected = self._pywebview_folder_dialog(initial)
        if not selected:
            return {"ok": True, "selected": False, "root": initial, "message": "Selecao cancelada."}
        folder = Path(selected)
        if not folder.is_dir():
            return {"ok": False, "selected": False, "root": initial, "message": "A pasta selecionada nao esta acessivel."}
        self.settings[chave] = str(folder)
        self._save_settings()
        return {"ok": True, "selected": True, "root": str(folder), "message": "Pasta registrada."}

    def set_root(self, value: str) -> dict:
        folder = Path(str(value).strip())
        if not folder.is_dir():
            return {"ok": False, "message": "A pasta informada nao existe ou nao esta acessivel."}
        self.settings["drawing_root"] = str(folder)
        self._save_settings()
        return {"ok": True, "root": str(folder)}

    def search(self, query: str, drawing_root: str | None = None) -> dict:
        try:
            if drawing_root is not None:
                root_result = self.set_root(drawing_root)
                if not root_result["ok"]:
                    return root_result
            found = find_latest_pdfs(Path(self.settings["drawing_root"]), query)
            found_indices: list[int] = []
            for item in found:
                dwgs = sorted(
                    (path for path in item.pdf.parent.iterdir() if path.is_file() and path.suffix.casefold() == ".dwg"),
                    key=lambda path: [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", path.name)],
                )
                item_data = item.as_dict()
                item_data["dwgs"] = [{"name": path.name} for path in dwgs]
                try:
                    index = self.results.index(item.pdf)
                except ValueError:
                    self.results.append(item.pdf)
                    self.result_folders.append(item.pdf.parent)
                    self.result_dwgs.append(dwgs)
                    self.result_data.append(item_data)
                    index = len(self.results) - 1
                else:
                    self.result_folders[index] = item.pdf.parent
                    self.result_dwgs[index] = dwgs
                    self.result_data[index] = item_data
                found_indices.append(index)
            return {
                "ok": True,
                "items": list(self.result_data),
                "foundCount": len(found),
                "openIndex": found_indices[0] if len(found_indices) == 1 else None,
            }
        except (ValueError, FileNotFoundError, PermissionError, OSError) as exc:
            return {"ok": False, "message": str(exc)}

    def clear_results(self) -> dict:
        self.results.clear()
        self.result_folders.clear()
        self.result_dwgs.clear()
        self.result_data.clear()
        return {"ok": True}

    def open_result(self, index: int) -> dict:
        try:
            path = self.results[int(index)]
            if not path.is_file():
                return {"ok": False, "message": "O PDF nao esta mais disponivel."}
            if os.name == "nt":
                os.startfile(str(path))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
            return {"ok": True}
        except (IndexError, ValueError, OSError) as exc:
            return {"ok": False, "message": f"Nao foi possivel abrir o PDF: {exc}"}

    def open_result_folder(self, index: int) -> dict:
        try:
            folder = self.result_folders[int(index)]
            if not folder.is_dir():
                return {"ok": False, "message": "A pasta nao esta mais disponivel."}
            if os.name == "nt":
                subprocess.Popen(["explorer", "/select,", str(self.results[int(index)])])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
            return {"ok": True}
        except (IndexError, ValueError, OSError) as exc:
            return {"ok": False, "message": f"Nao foi possivel abrir a pasta: {exc}"}

    def open_dwg(self, result_index: int, dwg_index: int) -> dict:
        try:
            path = self.result_dwgs[int(result_index)][int(dwg_index)]
            if not path.is_file():
                return {"ok": False, "message": "O arquivo DWG nao esta mais disponivel."}
            if os.name == "nt":
                os.startfile(str(path))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
            return {"ok": True}
        except (IndexError, ValueError, OSError) as exc:
            return {"ok": False, "message": f"Nao foi possivel abrir o DWG: {exc}"}

    def open_root(self) -> dict:
        try:
            folder = self.settings["drawing_root"]
            if os.name == "nt":
                os.startfile(folder)
            else:
                subprocess.Popen(["xdg-open", folder])
            return {"ok": True}
        except OSError as exc:
            return {"ok": False, "message": str(exc)}

    def minimize(self) -> None:
        self.window.minimize()

    def close(self) -> None:
        self.window.destroy()

    # ---------------------------------------------------------------- guia Especifica
    FILE_SEARCH_LIMIT = 300

    def start_file_search(self, folder: str, query: str, suffixes: str = "",
                          inside_content: bool = False, mode: str = "contem") -> dict:
        root = Path(str(folder).strip())
        if not root.is_dir():
            return {"ok": False, "message": "A pasta informada nao existe ou nao esta acessivel."}
        # Regra do programa: procura dentro de uma pasta, nunca numa unidade inteira.
        if root.parent == root:
            return {"ok": False, "message": "Escolha uma pasta, e nao a raiz de uma unidade."}
        terms = split_terms(query)
        if not terms:
            return {"ok": False, "message": "Digite parte do nome do arquivo."}
        # Guarda a pasta usada: na proxima abertura ela ja vem preenchida.
        if self.settings.get("search_root") != str(root):
            self.settings["search_root"] = str(root)
            self._save_settings()

        self.cancel_file_search()
        self.file_stop = threading.Event()
        with self.file_lock:
            self.file_hits = []
            self.file_state = {"running": True, "scanned": 0, "truncated": False, "message": ""}
            self.file_terms = terms
        stop = self.file_stop
        limite = self.FILE_SEARCH_LIMIT

        exata = str(mode).strip().casefold() == "exata"

        def varrer() -> None:
            achados = 0
            try:
                for tipo, dado in iter_file_matches(root, terms, parse_suffixes(suffixes),
                                                    True, bool(inside_content), stop, limite, exata):
                    with self.file_lock:
                        if tipo == "achado":
                            self.file_hits.append(dado)
                            achados += 1
                        else:
                            self.file_state["scanned"] = dado
            except Exception as exc:
                with self.file_lock:
                    self.file_state["message"] = f"A busca parou: {exc}"
            finally:
                with self.file_lock:
                    self.file_state["running"] = False
                    self.file_state["truncated"] = achados >= limite

        self.file_thread = threading.Thread(target=varrer, daemon=True)
        self.file_thread.start()
        return {"ok": True}

    def poll_file_search(self, seen: int = 0) -> dict:
        """Devolve o que apareceu depois dos 'seen' resultados ja entregues."""
        with self.file_lock:
            hits = list(self.file_hits)
            estado = dict(self.file_state)
        novos = hits[int(seen):]
        if not estado["running"]:
            # No fim, reordena por relevancia e manda a lista inteira.
            hits.sort(key=lambda item: relevance(item, self.file_terms))
            return {"ok": True, "items": hits, "replace": True, "done": True,
                    "scanned": estado["scanned"], "truncated": estado["truncated"],
                    "message": estado["message"]}
        return {"ok": True, "items": novos, "replace": False, "done": False,
                "scanned": estado["scanned"], "truncated": estado["truncated"],
                "message": estado["message"]}

    def cancel_file_search(self) -> dict:
        self.file_stop.set()
        thread = self.file_thread
        if thread and thread.is_alive():
            thread.join(timeout=2)
        with self.file_lock:
            self.file_state["running"] = False
        return {"ok": True}

    def open_file_hit(self, path: str, reveal: bool = False) -> dict:
        alvo = Path(str(path))
        if not alvo.exists():
            return {"ok": False, "message": "O item nao esta mais disponivel."}
        try:
            if os.name == "nt":
                if reveal:
                    subprocess.Popen(["explorer", "/select,", str(alvo)])
                else:
                    os.startfile(str(alvo))
            else:
                abrir = ["open"] if sys.platform == "darwin" else ["xdg-open"]
                subprocess.Popen(abrir + [str(alvo if not reveal else alvo.parent)])
            return {"ok": True}
        except OSError as exc:
            return {"ok": False, "message": f"Nao foi possivel abrir: {exc}"}

    def scan_manual_update(self) -> dict:
        return self.updates.scan_manual()

    def install_manual_update(self) -> dict:
        result = self.updates.install_manual()
        if result.get("restarting") and self.window is not None:
            threading.Timer(.3, self.window.destroy).start()
        return result

    def open_manual_folder(self) -> dict:
        try:
            pasta = self.updates.manual_folder()
            if os.name == "nt":
                os.startfile(str(pasta))
            else:
                subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(pasta)])
            return {"ok": True}
        except OSError as exc:
            return {"ok": False, "message": f"Nao foi possivel abrir a pasta: {exc}"}

    def check_update(self) -> dict:
        return self.updates.check()

    def install_update(self) -> dict:
        result = self.updates.download_and_install()
        if result.get("ok"):
            threading.Timer(.3, self.window.destroy).start()
        return result
