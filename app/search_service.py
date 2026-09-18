from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import unicodedata

REVISION_RE = re.compile(r"(?i)(?:\brev(?:is[aã]o)?)[\s._-]*(\d+(?:[._-]\d+)*)")


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value))
    return "".join(ch for ch in value if ch.isalnum()).casefold()


def revision_key(name: str) -> tuple[int, ...] | None:
    matches = list(REVISION_RE.finditer(name))
    if not matches:
        return None
    return tuple(int(part) for part in re.split(r"[._-]", matches[-1].group(1)))


@dataclass(frozen=True)
class DrawingResult:
    project: Path
    revision: Path
    pdf: Path
    revision_number: tuple[int, ...]

    def as_dict(self) -> dict:
        return {
            "project": self.project.name,
            "revision": self.revision.name,
            "revisionLabel": ".".join(map(str, self.revision_number)),
            "pdf": self.pdf.name,
            "path": str(self.pdf),
            "folder": str(self.pdf.parent),
        }


def find_latest_pdfs(root: Path, query: str) -> list[DrawingResult]:
    root = root.expanduser()
    needle = normalize(query)
    if not needle:
        raise ValueError("Digite o numero do desenho.")
    if not root.is_dir():
        raise FileNotFoundError("A pasta de desenhos nao foi encontrada. Confira o endereco configurado.")

    projects = [p for p in root.iterdir() if p.is_dir() and needle in normalize(p.name)]
    projects.sort(key=lambda p: (normalize(p.name) != needle, p.name.casefold()))
    results: list[DrawingResult] = []

    for project in projects:
        candidates: list[tuple[tuple[int, ...], float, Path]] = []
        for pdf in project.rglob("*"):
            if not pdf.is_file() or pdf.suffix.casefold() != ".pdf":
                continue
            key = revision_key(pdf.stem)
            current = pdf.parent
            while key is None and current != project.parent:
                key = revision_key(current.name)
                if current == project:
                    break
                current = current.parent
            candidates.append((key or (0,), pdf.stat().st_mtime, pdf))
        if candidates:
            latest_key = max(item[0] for item in candidates)
            latest_pdfs = [item for item in candidates if item[0] == latest_key]
            _, _, selected = max(
                latest_pdfs,
                key=lambda item: (normalize(project.name) in normalize(item[2].stem), item[1]),
            )
            results.append(DrawingResult(project, selected.parent, selected, latest_key))
    return results
