from __future__ import annotations

from pathlib import Path, PurePosixPath
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile

APP_ID = "calavort.localizador-desenhos"
PACKAGE_PREFIX = "Localizador_de_Desenhos"
MANIFEST = "manifesto-release.json"
STATE_DIR = ".atualizacoes"
RECORD = "instalado.json"  # registro local do que a ultima instalacao gravou
LEGACY_RECORD = "manifesto-release.json"  # o mesmo registro, antes na raiz
MAX_PACKAGE = 80 * 1024 * 1024
MAX_EXPANDED = 160 * 1024 * 1024
MAX_FILES = 200
MAX_DEPTH = 4
MAX_NAME = 180
# Sublinhado no inicio e valido (__init__.py); ponto no inicio nao, para nao
# deixar passar arquivo oculto nem "." / "..".
SEGMENT = re.compile(r"[A-Za-z0-9_][A-Za-z0-9 ._-]*")
RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{n}" for n in range(1, 10)}
    | {f"LPT{n}" for n in range(1, 10)}
)
# Lista desta versao: e o que o publicador empacota e o que se assume ter
# sido instalado quando ainda nao existe registro de uma instalacao anterior.
APP_FILES = (
    "Localizador_Desenhos.pyw",
    "versao.json",
    "requirements.txt",
    "README.txt",
    "Instalar Bibliotecas.bat",
    "Iniciar Localizador.bat",
    "Instalar no Menu Iniciar.bat",
    "app/__init__.py",
    "app/main.py",
    "app/backend.py",
    "app/instalador.py",
    "app/search_service.py",
    "app/updater.py",
    "atualizacao/LEIA-ME.txt",
    "ferramentas/publicar_release.py",
    "ferramentas/GUIA_ATUALIZACAO.md",
    "interface/index.html",
    "interface/localizador.ico",
    "interface/localizador.png",
    "interface/localizador.svg",
)


class UpdateError(RuntimeError):
    pass


def version_key(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", str(value).strip())
    if not match:
        raise UpdateError("Versao invalida. Use o formato X.Y.Z.")
    return tuple(map(int, match.groups()))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def safe_member_name(value: str) -> str:
    """Aprova o caminho pela forma, e nao por uma lista fixa de nomes.

    A lista fixa travava a organizacao das pastas: quem instalou a versao
    antiga e quem valida o pacote novo, entao qualquer arquivo renomeado ou
    movido era recusado como "nao permitido". O que protegia continua valendo
    - nada de caminho absoluto, unidade, "..", link ou nome reservado do
    Windows - e a lista de arquivos passa a vir do manifesto, ja conferido
    por hash.
    """
    if not isinstance(value, str) or not value or len(value) > MAX_NAME:
        raise UpdateError("O pacote contem um nome de arquivo invalido.")
    if value != value.strip() or "\\" in value or ":" in value:
        raise UpdateError("O pacote contem um nome de arquivo invalido.")
    path = PurePosixPath(value)
    if path.is_absolute() or not 1 <= len(path.parts) <= MAX_DEPTH:
        raise UpdateError("O pacote contem um caminho inseguro.")
    for part in path.parts:
        if part in ("", ".", "..") or part.endswith((" ", ".")):
            raise UpdateError("O pacote contem um caminho inseguro.")
        if not SEGMENT.fullmatch(part):
            raise UpdateError(f"Nome de arquivo invalido no pacote: {value}")
        if part.split(".")[0].upper() in RESERVED_NAMES:
            raise UpdateError(f"Nome reservado pelo Windows no pacote: {value}")
    return path.as_posix()


def installed_files(root: Path) -> tuple[str, ...]:
    """Arquivos gravados pela ultima instalacao.

    E o que permite apagar o que a versao nova nao traz mais: sem esse
    registro, um arquivo removido ou movido de pasta sobrevive para sempre na
    instalacao do usuario. Antes da primeira instalacao feita por este codigo
    nao ha registro, e a lista desta versao e a aposta certa.
    """
    registro = root / STATE_DIR / RECORD
    try:
        nomes = json.loads(registro.read_text(encoding="utf-8"))["files"]
        if isinstance(nomes, list) and 1 <= len(nomes) <= MAX_FILES:
            return tuple(safe_member_name(nome) for nome in nomes)
    except (OSError, ValueError, KeyError, TypeError, UpdateError):
        pass
    return APP_FILES


def validate_package(package: Path, info: dict, expected_version: str) -> dict:
    with zipfile.ZipFile(package) as archive:
        members = [entry for entry in archive.infolist() if not entry.is_dir()]
        if not members or len(members) > MAX_FILES:
            raise UpdateError("Quantidade de arquivos invalida no pacote.")
        if sum(entry.file_size for entry in members) > MAX_EXPANDED:
            raise UpdateError("O pacote expandido excede o limite permitido.")
        names: list[str] = []
        for entry in members:
            name = safe_member_name(entry.filename)
            if name in names:
                raise UpdateError("O pacote contem arquivos duplicados.")
            mode = entry.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise UpdateError("Links nao sao permitidos no pacote.")
            names.append(name)
        required = {"Localizador_Desenhos.pyw", "versao.json", "requirements.txt", MANIFEST}
        if not required.issubset(names):
            raise UpdateError("O pacote de atualizacao esta incompleto.")
        manifest = json.loads(archive.read(MANIFEST).decode("utf-8"))
        if manifest.get("schema") != 1 or manifest.get("app_id") != APP_ID:
            raise UpdateError("Manifesto de atualizacao invalido.")
        if manifest.get("version") != expected_version or manifest.get("repository") != info["repository"]:
            raise UpdateError("O pacote pertence a outra versao ou repositorio.")
        hashes = manifest.get("files")
        payload_names = set(names) - {MANIFEST}
        if not isinstance(hashes, dict) or set(hashes) != payload_names:
            raise UpdateError("A lista de arquivos do manifesto nao confere.")
        for name in payload_names:
            expected = hashes.get(name)
            if not re.fullmatch(r"[0-9a-f]{64}", str(expected)):
                raise UpdateError("Hash invalido no manifesto.")
            if sha256_bytes(archive.read(name)) != expected:
                raise UpdateError(f"Integridade invalida no arquivo {name}.")
        return manifest


class UpdateService:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.version_info = self._read_info()
        self.version = self.version_info["version"]

    def _read_info(self) -> dict:
        try:
            value = json.loads((self.root / "versao.json").read_text(encoding="utf-8"))
            if value.get("app_id") != APP_ID:
                raise ValueError("app_id")
            version_key(value["version"])
            if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value["repository"]):
                raise ValueError("repository")
            value["launcher"] = value.get("launcher") or "Localizador_Desenhos.pyw"
            return value
        except (OSError, ValueError, KeyError, TypeError, UpdateError) as exc:
            raise UpdateError("Nao foi possivel ler a configuracao de atualizacao.") from exc

    def _latest(self) -> dict:
        request = urllib.request.Request(
            f"https://api.github.com/repos/{self.version_info['repository']}/releases/latest",
            headers={"Accept": "application/vnd.github+json", "User-Agent": "LocalizadorDesenhos-Updater"},
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            if response.status != 200:
                raise UpdateError("O GitHub nao retornou um release valido.")
            return json.loads(response.read(2 * 1024 * 1024))

    # ------------------------------------------------ pacote deixado na pasta
    # Caminho para quando a versao nova muda as bibliotecas: o automatico se
    # recusa (instalaria algo que nao abre), entao o pacote e colocado a mao em
    # "atualizacao/" e instalado daqui, com aviso.
    MANUAL_DIR = "atualizacao"

    def manual_folder(self) -> Path:
        pasta = self.root / self.MANUAL_DIR
        pasta.mkdir(exist_ok=True)
        return pasta

    def _manual_packages(self) -> list[Path]:
        return sorted(
            (item for item in self.manual_folder().glob("*.zip") if item.is_file()),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )

    def scan_manual(self) -> dict:
        """Diz o que ha na pasta, sem instalar nada."""
        try:
            pasta = self.manual_folder()
        except OSError as exc:
            return {"ok": False, "message": f"Nao foi possivel abrir a pasta: {exc}"}
        pacotes = self._manual_packages()
        if not pacotes:
            return {"ok": True, "found": False, "folder": str(pasta),
                    "message": "Nenhum pacote na pasta atualizacao."}
        pacote = pacotes[0]
        versao = self._package_version(pacote)
        if not versao:
            return {"ok": True, "found": False, "folder": str(pasta), "file": pacote.name,
                    "message": f"{pacote.name} nao parece um pacote deste programa."}
        if version_key(versao) <= version_key(self.version):
            return {"ok": True, "found": False, "folder": str(pasta), "file": pacote.name,
                    "message": f"O pacote da pasta e a versao {versao}; voce ja tem a {self.version}."}
        return {"ok": True, "found": True, "folder": str(pasta), "file": pacote.name,
                "version": versao, "changesLibraries": self._changes_requirements(pacote),
                "message": f"Pacote da versao {versao} pronto para instalar."}

    def _package_version(self, pacote: Path) -> str:
        try:
            with zipfile.ZipFile(pacote) as arquivo:
                manifesto = json.loads(arquivo.read(MANIFEST).decode("utf-8"))
            if manifesto.get("app_id") != APP_ID:
                return ""
            versao = str(manifesto.get("version", ""))
            version_key(versao)
            return versao
        except (OSError, ValueError, KeyError, zipfile.BadZipFile, UpdateError):
            return ""

    def _changes_requirements(self, pacote: Path) -> bool:
        try:
            atual = (self.root / "requirements.txt").read_bytes()
            with zipfile.ZipFile(pacote) as arquivo:
                return arquivo.read("requirements.txt") != atual
        except (OSError, KeyError, zipfile.BadZipFile):
            return False

    def cleanup_leftovers(self) -> dict:
        """Apaga o que sobra de uma atualizacao e conta como foi o pip.

        O instalador nao consegue apagar a si mesmo enquanto roda, entao quem
        limpa e o programa ja reaberto. Tambem tira da pasta atualizacao/ os
        pacotes de versoes que ja estao instaladas.
        """
        aviso: dict = {}
        estado = self.root / ".atualizacoes"
        try:
            registro = estado / "bibliotecas.json"
            if registro.is_file():
                dados = json.loads(registro.read_text(encoding="utf-8"))
                if not dados.get("ok"):
                    aviso = {
                        "failed": True,
                        "detail": str(dados.get("detalhe", ""))[:400],
                        "message": ("A versao nova foi instalada, mas as bibliotecas nao. "
                                    "Rode o Instalar Bibliotecas.bat uma vez."),
                    }
        except (OSError, ValueError):
            pass
        if estado.is_dir() and not estado.is_symlink():
            shutil.rmtree(estado, ignore_errors=True)
        try:
            for pacote in self._manual_packages():
                versao = self._package_version(pacote)
                if versao and version_key(versao) <= version_key(self.version):
                    pacote.unlink(missing_ok=True)
        except (OSError, UpdateError):
            pass
        return aviso

    def auto_install_manual(self) -> dict:
        """Instala sozinho o pacote deixado na pasta, sem esperar o clique."""
        achado = self.scan_manual()
        if not achado.get("ok") or not achado.get("found"):
            return {"started": False}
        resultado = self.install_manual()
        return {"started": bool(resultado.get("restarting")), "version": achado.get("version", ""),
                "message": resultado.get("message", "")}

    def install_manual(self) -> dict:
        """Instala o pacote da pasta, com as mesmas conferencias do automatico."""
        try:
            if (self.root / ".git").exists():
                raise UpdateError("Atualizacao desativada nesta pasta de desenvolvimento.")
            pacotes = self._manual_packages()
            if not pacotes:
                raise UpdateError("Nenhum pacote na pasta atualizacao.")
            origem = pacotes[0]
            versao = self._package_version(origem)
            if not versao:
                raise UpdateError("O arquivo da pasta nao e um pacote deste programa.")
            if version_key(versao) <= version_key(self.version):
                return {"ok": True, "message": f"Voce ja esta na versao {self.version}."}

            estado = self.root / ".atualizacoes"
            if estado.is_symlink():
                raise UpdateError("A pasta de atualizacoes nao pode ser um link.")
            estado.mkdir(exist_ok=True)
            destino = estado / origem.name
            shutil.copy2(origem, destino)
            validate_package(destino, self.version_info, versao)
            digest = sha256_file(destino)

            instalador = estado / "instalador.py"
            shutil.copy2(self.root / "app" / "instalador.py", instalador)
            subprocess.Popen(
                [sys.executable, str(instalador), "--root", str(self.root), "--package", str(destino),
                 "--sha256", digest, "--version", versao],
                cwd=str(self.root),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return {"ok": True, "restarting": True,
                    "message": f"Pacote {versao} validado. O programa sera reiniciado."}
        except (UpdateError, OSError, ValueError, zipfile.BadZipFile) as exc:
            return {"ok": False, "message": str(exc)}

    def check(self) -> dict:
        try:
            release = self._latest()
            latest = str(release.get("tag_name", "")).lstrip("v")
            version_key(latest)
            if version_key(latest) <= version_key(self.version):
                return {"ok": True, "available": False, "version": self.version, "message": "Voce ja esta usando a versao mais recente."}
            assets = {item.get("name") for item in release.get("assets", [])}
            package_name = f"{PACKAGE_PREFIX}-{latest}.zip"
            if package_name not in assets or package_name + ".sha256" not in assets:
                raise UpdateError("O release nao possui o pacote e o SHA-256 exigidos.")
            return {"ok": True, "available": True, "version": latest, "message": f"A versao {latest} esta disponivel."}
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return {"ok": False, "available": False, "message": "Repositorio ou primeira versao ainda nao publicado no GitHub."}
            return {"ok": False, "available": False, "message": "Nao foi possivel verificar atualizacoes agora."}
        except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError, UpdateError) as exc:
            return {"ok": False, "available": False, "message": str(exc) if isinstance(exc, UpdateError) else "Nao foi possivel verificar atualizacoes agora."}

    def download_and_install(self) -> dict:
        try:
            if (self.root / ".git").exists():
                raise UpdateError("Atualizacao automatica desativada nesta pasta de desenvolvimento.")
            release = self._latest()
            latest = str(release.get("tag_name", "")).lstrip("v")
            if version_key(latest) <= version_key(self.version):
                return {"ok": True, "message": "Voce ja esta usando a versao mais recente."}
            package_name = f"{PACKAGE_PREFIX}-{latest}.zip"
            checksum_name = package_name + ".sha256"
            assets = {item.get("name"): item for item in release.get("assets", [])}
            if package_name not in assets or checksum_name not in assets:
                raise UpdateError("O release nao possui o pacote de atualizacao completo.")
            state = self.root / ".atualizacoes"
            if state.is_symlink():
                raise UpdateError("A pasta de atualizacoes nao pode ser um link.")
            state.mkdir(exist_ok=True)
            package = state / package_name
            expected = self._download_text(assets[checksum_name]["browser_download_url"]).split()[0].lower()
            self._download_file(assets[package_name]["browser_download_url"], package)
            digest = sha256_file(package)
            if not re.fullmatch(r"[0-9a-f]{64}", expected) or digest != expected:
                raise UpdateError("Falha na verificacao SHA-256. Nenhum arquivo foi alterado.")
            validate_package(package, self.version_info, latest)
            installer = state / "instalador.py"
            shutil.copy2(self.root / "app" / "instalador.py", installer)
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.Popen(
                [sys.executable, str(installer), "--root", str(self.root), "--package", str(package), "--sha256", digest, "--version", latest],
                cwd=str(self.root),
                creationflags=creationflags,
            )
            return {"ok": True, "message": "Atualizacao validada. O programa sera reiniciado."}
        except urllib.error.HTTPError as exc:
            message = "Repositorio ou primeira versao ainda nao publicado no GitHub." if exc.code == 404 else "Nao foi possivel baixar a atualizacao."
            return {"ok": False, "message": message}
        except (OSError, urllib.error.URLError, KeyError, ValueError, json.JSONDecodeError, zipfile.BadZipFile, UpdateError) as exc:
            return {"ok": False, "message": str(exc) if isinstance(exc, UpdateError) else "Nao foi possivel baixar a atualizacao."}

    @staticmethod
    def _download_text(url: str) -> str:
        if not url.startswith("https://"):
            raise UpdateError("Endereco de atualizacao inseguro.")
        with urllib.request.urlopen(url, timeout=20) as response:
            return response.read(4096).decode("ascii")

    @staticmethod
    def _download_file(url: str, target: Path) -> None:
        if not url.startswith("https://"):
            raise UpdateError("Endereco de atualizacao inseguro.")
        temporary = target.with_suffix(target.suffix + ".tmp")
        total = 0
        try:
            with urllib.request.urlopen(url, timeout=30) as response, temporary.open("wb") as output:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_PACKAGE:
                        raise UpdateError("O pacote excede o limite de tamanho permitido.")
                    output.write(chunk)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
