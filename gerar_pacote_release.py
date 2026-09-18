from __future__ import annotations

from pathlib import Path
import argparse
import hashlib
import json
import os
import zipfile

from app.updater import APP_FILES, APP_ID, MANIFEST, PACKAGE_PREFIX, UpdateError, sha256_file, version_key


def build_package(root: Path, version: str | None = None, output_dir: Path | None = None) -> Path:
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
        if name.endswith(".py"):
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
    archive.with_suffix(".zip.sha256").write_text(f"{sha256_file(archive)}  {archive.name}\n", encoding="ascii")
    info_path.write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return archive


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera o pacote seguro do Localizador de arquivo.")
    parser.add_argument("--versao", help="Nova versao no formato X.Y.Z")
    parser.add_argument("--saida", type=Path, help="Pasta de saida")
    args = parser.parse_args()
    try:
        package = build_package(Path(__file__).resolve().parent, args.versao, args.saida)
        print(f"Pacote criado: {package}")
        print(f"SHA-256: {sha256_file(package)}")
    except Exception as exc:
        parser.exit(1, f"Pacote nao criado: {exc}\n")


if __name__ == "__main__":
    main()
