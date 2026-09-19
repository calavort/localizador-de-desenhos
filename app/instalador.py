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


def install_requirements(root: Path) -> dict:
    """Instala as bibliotecas da versao nova.

    So roda quando o requirements.txt mudou de verdade. Se falhar, o programa
    ainda abre: o aviso aparece na guia Atualizacao e o "Instalar
    Bibliotecas.bat" continua servindo de saida manual.
    """
    try:
        resultado = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
            cwd=str(root), capture_output=True, text=True, timeout=900,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "detalhe": str(exc)}
    if resultado.returncode == 0:
        return {"ok": True, "detalhe": ""}
    saida = (resultado.stderr or resultado.stdout or "").strip().splitlines()
    return {"ok": False, "detalhe": " ".join(saida[-3:])[:400]}


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
    from app.updater import (
        LEGACY_RECORD, RECORD, installed_files, safe_member_name, sha256_file, validate_package,
    )

    if sha256_file(package) != args.sha256:
        raise SystemExit("O pacote mudou depois da validacao SHA-256.")
    info = json.loads((root / "versao.json").read_text(encoding="utf-8"))
    # Aqui a conferencia e de integridade, nao de politica: quem decide se a
    # versao pode ser instalada e o programa, antes de chamar o instalador.
    manifest = validate_package(package, info, args.version)
    antes_requisitos = (root / "requirements.txt").read_bytes()
    files = tuple(sorted(manifest["files"]))
    # O que a instalacao anterior gravou e esta versao nao traz mais sai de
    # cena; sem isso um arquivo que mudou de pasta ficaria nos dois lugares.
    obsoletos = tuple(sorted(set(installed_files(root)) - set(files)))
    launcher = str(info.get("launcher") or "Localizador_Desenhos.pyw")
    state = root / ".atualizacoes"
    stage = state / "preparado"
    backup = state / "backup"
    journal = state / "instalacao.json"
    time.sleep(2.5)  # folga para o programa fechar antes de ser reaberto

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

    for name in files + obsoletos:
        source = root / name
        if source.is_file():
            saved = backup / name
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, saved)

    journal.write_text(
        json.dumps({"version": args.version, "files": files, "obsoletos": obsoletos}, indent=2),
        encoding="utf-8",
    )
    replaced: list[str] = []
    removidos: list[str] = []
    try:
        for name in files:
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(stage / name, target)
            replaced.append(name)
        for name in obsoletos:
            alvo = root / safe_member_name(name)
            if alvo.is_file():
                alvo.unlink()
                removidos.append(name)
        (state / RECORD).write_text(
            json.dumps({"version": args.version, "files": files}, indent=2), encoding="utf-8"
        )
        # O registro morava na raiz ate a versao 1.6.0.
        (root / LEGACY_RECORD).unlink(missing_ok=True)
    except Exception:
        for name in reversed(replaced + removidos):
            target = root / name
            saved = backup / name
            if saved.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(saved, target)
            elif name in replaced:
                target.unlink(missing_ok=True)
        launch(root, launcher)
        raise
    else:
        new_info = json.loads((root / "versao.json").read_text(encoding="utf-8"))
        launcher = str(new_info.get("launcher") or launcher)
        if (root / "requirements.txt").read_bytes() != antes_requisitos:
            estado = install_requirements(root)
            estado["version"] = args.version
            (state / "bibliotecas.json").write_text(json.dumps(estado), encoding="utf-8")
        for name in removidos:  # pasta que ficou vazia depois da limpeza
            pasta = (root / name).parent
            while pasta != root and pasta.is_dir() and not any(pasta.iterdir()):
                pasta.rmdir()
                pasta = pasta.parent
        journal.unlink(missing_ok=True)
        shutil.rmtree(stage, ignore_errors=True)
        shutil.rmtree(backup, ignore_errors=True)
        launch(root, launcher)


if __name__ == "__main__":
    main()
