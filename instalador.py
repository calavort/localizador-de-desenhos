from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile


def launch(root: Path, launcher: str) -> None:
    executable = sys.executable
    if executable.lower().endswith("python.exe"):
        pythonw = Path(executable).with_name("pythonw.exe")
        if pythonw.is_file():
            executable = str(pythonw)
    subprocess.Popen([executable, str(root / launcher)], cwd=str(root), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--package", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    package = Path(args.package).resolve()
    if (root / ".git").exists():
        raise SystemExit("Atualizacao recusada em pasta de desenvolvimento.")
    sys.path.insert(0, str(root))
    from app.updater import MANIFEST, sha256_file, validate_package

    if sha256_file(package) != args.sha256:
        raise SystemExit("O pacote mudou depois da validacao SHA-256.")
    info = json.loads((root / "versao.json").read_text(encoding="utf-8"))
    manifest = validate_package(package, info, args.version)
    files = tuple(sorted(manifest["files"]))
    launcher = str(info.get("launcher") or "Localizador_Desenhos.pyw")
    state = root / ".atualizacoes"
    stage = state / "preparado"
    backup = state / "backup"
    journal = state / "instalacao.json"
    time.sleep(1.2)

    for target in (stage, backup):
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)

    with zipfile.ZipFile(package) as archive:
        for name in files:
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(name) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)

    for name in files:
        source = root / name
        if source.is_file():
            saved = backup / name
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, saved)

    journal.write_text(json.dumps({"version": args.version, "files": files}, indent=2), encoding="utf-8")
    replaced: list[str] = []
    try:
        for name in files:
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(stage / name, target)
            replaced.append(name)
        (root / MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    except Exception:
        for name in reversed(replaced):
            target = root / name
            saved = backup / name
            if saved.is_file():
                os.replace(saved, target)
            else:
                target.unlink(missing_ok=True)
        launch(root, launcher)
        raise
    else:
        new_info = json.loads((root / "versao.json").read_text(encoding="utf-8"))
        launcher = str(new_info.get("launcher") or launcher)
        journal.unlink(missing_ok=True)
        shutil.rmtree(stage, ignore_errors=True)
        shutil.rmtree(backup, ignore_errors=True)
        launch(root, launcher)


if __name__ == "__main__":
    main()
