from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.updater import PACKAGE_PREFIX, UpdateError, sha256_file, version_key  # noqa: E402
from gerar_pacote_release import build_package  # noqa: E402


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
            {"name": name, "description": "Distribuicao e atualizacoes do Localizador de Desenhos", "private": False, "auto_init": True},
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
            "name": "Localizador de Desenhos " + info["version"],
            "draft": True,
            "prerelease": False,
            "target_commitish": repository["default_branch"],
            "body": "Pacote portatil do Localizador de Desenhos para Windows.\n\n"
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
    parser.add_argument("--versao", required=True, help="Nova versao, por exemplo 1.0.3")
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
