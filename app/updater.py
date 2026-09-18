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
MAX_PACKAGE = 80 * 1024 * 1024
MAX_EXPANDED = 160 * 1024 * 1024
MAX_FILES = 200
APP_FILES = (
    "Localizador_Desenhos.pyw",
    "instalador.py",
    "versao.json",
    "requirements.txt",
    "README.txt",
    "Instalar Bibliotecas.bat",
    "Iniciar Localizador.bat",
    "Adicionar ao Menu Iniciar.ps1",
    "Instalar no Menu Iniciar.bat",
    "app/__init__.py",
    "app/main.py",
    "app/backend.py",
    "app/search_service.py",
    "app/updater.py",
    "interface/index.html",
    "interface/localizador.ico",
    "interface/localizador.svg",
    "interface/localizador.png",
    "gerar_pacote_release.py",
    "ferramentas/publicar_release.py",
    "GUIA_ATUALIZACAO.md",
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
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise UpdateError("O pacote contem um nome de arquivo invalido.")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise UpdateError("O pacote contem um caminho inseguro.")
    normalized = path.as_posix()
    if normalized not in set(APP_FILES) | {MANIFEST}:
        raise UpdateError(f"Arquivo nao permitido no pacote: {normalized}")
    return normalized


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
        current_requirements = (package.parent.parent / "requirements.txt")
        if current_requirements.is_file() and archive.read("requirements.txt") != current_requirements.read_bytes():
            raise UpdateError("Esta versao altera bibliotecas. Instale o pacote manualmente.")
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
            shutil.copy2(self.root / "instalador.py", installer)
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
