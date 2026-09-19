"""Monta o pacote do Localizador de arquivo e, se pedido, publica no GitHub.

    py -3 ferramentas/publicar_release.py --versao 1.7.0
    py -3 ferramentas/publicar_release.py --versao 1.7.0 --notas NOTAS.md --publicar

Sem ``--publicar`` o script so grava o ZIP e o ``.sha256`` em ``release``, para
conferencia ou instalacao manual.
"""

from __future__ import annotations

from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.updater import (  # noqa: E402
    APP_FILES, APP_ID, MANIFEST, PACKAGE_PREFIX, UpdateError, sha256_file, version_key,
)


def build_package(root: Path, version: str | None = None, output_dir: Path | None = None) -> Path:
    """Empacota os arquivos da versao com um manifesto de hash por arquivo."""
    info_path = root / "versao.json"
    info = json.loads(info_path.read_text(encoding="utf-8"))
    if info.get("app_id") != APP_ID:
        raise UpdateError("app_id diferente do esperado.")
    current = str(info["version"])
    version = version or current
    if version_key(version) < version_key(current):
        raise UpdateError("A nova versao nao pode ser menor que a atual.")
    if not info.get("repository"):
        raise UpdateError("Configure o repositorio em versao.json.")
    info["version"] = version
    payloads: dict[str, bytes] = {}
    for name in APP_FILES:
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise UpdateError(f"Arquivo obrigatorio ausente ou invalido: {name}")
        payloads[name] = path.read_bytes()
        if name.endswith((".py", ".pyw")):
            compile(payloads[name], name, "exec")
    payloads["versao.json"] = json.dumps(info, ensure_ascii=True, indent=2).encode("utf-8")
    manifest = {
        "schema": 1,
        "app_id": APP_ID,
        "version": version,
        "repository": info["repository"],
        "python_min": [3, 11],
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()},
    }
    output_dir = output_dir or root / "release"
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / f"{PACKAGE_PREFIX}-{version}.zip"
    temporary = archive.with_suffix(".zip.tmp")
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as package:
        for name, data in payloads.items():
            package.writestr(name, data)
        package.writestr(MANIFEST, json.dumps(manifest, indent=2))
    os.replace(temporary, archive)
    archive.with_suffix(".zip.sha256").write_text(
        f"{sha256_file(archive)}  {archive.name}\n", encoding="ascii"
    )
    info_path.write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return archive


def github_token() -> str:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        return token
    if shutil.which("gh"):
        result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=15)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    environment = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="Never")
    if shutil.which("git"):
        result = subprocess.run(
            ["git", "credential", "fill"],
            input="protocol=https\nhost=github.com\n\n",
            capture_output=True,
            text=True,
            env=environment,
            timeout=20,
        )
        credential = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        if credential.get("password"):
            return credential["password"]
    raise UpdateError("Entre no GitHub neste computador antes de publicar.")


def api(token: str, url: str, method: str = "GET", data=None, binary: bool = False):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {"api.github.com", "uploads.github.com"}:
        raise UpdateError("Endereco de publicacao invalido.")
    body = data if binary else (json.dumps(data).encode("utf-8") if data is not None else None)
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Authorization": "Bearer " + token,
            "User-Agent": "LocalizadorDesenhos-Publisher",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/octet-stream" if binary else "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def publish(archive: Path, create_repository: bool, notes: str) -> str:
    info = json.loads((ROOT / "versao.json").read_text(encoding="utf-8"))
    token = github_token()
    owner, name = info["repository"].split("/", 1)
    base = f"https://api.github.com/repos/{owner}/{name}"
    try:
        repository = api(token, base)
    except urllib.error.HTTPError as exc:
        if exc.code != 404 or not create_repository:
            raise
        user = api(token, "https://api.github.com/user")
        if user["login"].casefold() != owner.casefold():
            raise UpdateError("A conta autenticada e diferente da conta configurada.")
        repository = api(
            token,
            "https://api.github.com/user/repos",
            "POST",
            {"name": name, "description": "Distribuicao e atualizacoes do Localizador de arquivo", "private": False, "auto_init": True},
        )
    if repository.get("private"):
        raise UpdateError("O atualizador exige um repositorio publico.")
    try:
        latest = api(token, base + "/releases/latest")
        if version_key(info["version"]) <= version_key(latest["tag_name"]):
            raise UpdateError("Esta versao ja foi publicada. Incremente --versao.")
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
    release = api(
        token,
        base + "/releases",
        "POST",
        {
            "tag_name": "v" + info["version"],
            "name": "Localizador de arquivo " + info["version"],
            "draft": True,
            "prerelease": False,
            "target_commitish": repository["default_branch"],
            "body": "Pacote portatil do Localizador de arquivo para Windows.\n\n"
                    "O atualizador preserva o endereco de desenhos salvo no computador."
                    + ("\n\n" + notes if notes else ""),
        },
    )
    upload_url = release["upload_url"].split("{")[0]
    for asset in (archive, archive.with_suffix(".zip.sha256")):
        uploaded = api(
            token,
            upload_url + "?" + urllib.parse.urlencode({"name": asset.name}),
            "POST",
            asset.read_bytes(),
            binary=True,
        )
        expected_digest = "sha256:" + sha256_file(asset)
        if uploaded.get("size") != asset.stat().st_size or (uploaded.get("digest") and uploaded["digest"] != expected_digest):
            raise UpdateError("O upload nao conferiu; o release permaneceu como rascunho.")
    published = api(token, base + "/releases/" + str(release["id"]), "PATCH", {"draft": False, "make_latest": "true"})
    return published["html_url"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera e publica uma versao no GitHub Releases.")
    parser.add_argument("--versao", help="Nova versao, por exemplo 1.7.0; sem ela, reempacota a atual")
    parser.add_argument("--notas", type=Path, help="Arquivo Markdown com notas da versao")
    parser.add_argument("--publicar", action="store_true", help="Publica o pacote no GitHub")
    parser.add_argument("--criar-repositorio", action="store_true", help="Cria o repositorio publico se estiver ausente")
    args = parser.parse_args()
    try:
        archive = build_package(ROOT, args.versao)
        print("Pacote pronto:", archive)
        print("SHA-256:", sha256_file(archive))
        if args.publicar:
            notes = args.notas.read_text(encoding="utf-8") if args.notas else ""
            print("Release publicado:", publish(archive, args.criar_repositorio, notes))
    except Exception as exc:
        parser.exit(1, f"Publicacao nao concluida: {exc}\n")


if __name__ == "__main__":
    main()
