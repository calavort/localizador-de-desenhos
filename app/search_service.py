from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
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


# ---------------------------------------------------------------------------
# Busca livre (guia Especifica): qualquer arquivo ou pasta, por parte do nome.

# Pastas que nunca interessam e so fariam a varredura demorar.
SKIPPED_DIRS = {
    ".git", "__pycache__", "node_modules", ".atualizacoes", ".venv", "venv",
    "$recycle.bin", "system volume information", "windows", "程序文件",
}

# Conteudo legivel sem biblioteca extra. PDF entra so se houver leitor instalado
# (ver read_text_content); assim o requirements.txt segue intocado e o
# atualizador nao recusa a versao nova.
TEXT_SUFFIXES = {".txt", ".csv", ".md", ".log", ".ini", ".cfg", ".json", ".xml",
                 ".html", ".htm", ".css", ".js", ".py", ".pyw", ".bat", ".ps1",
                 ".yml", ".yaml", ".srt", ".sql"}
OFFICE_SUFFIXES = {".docx", ".xlsx", ".pptx"}


def split_terms(query: str) -> list[str]:
    """Cada palavra vira um termo; todos precisam aparecer, em qualquer ordem."""
    return [normalize(part) for part in str(query).split() if normalize(part)]


def parse_suffixes(value: str) -> set[str]:
    """'pdf, .dwg' -> {'.pdf', '.dwg'}. Vazio significa qualquer formato."""
    suffixes = set()
    for part in re.split(r"[\s,;]+", str(value or "")):
        part = part.strip().casefold()
        if part:
            suffixes.add(part if part.startswith(".") else "." + part)
    return suffixes


def name_matches(name: str, terms: list[str]) -> bool:
    normalized = normalize(name)
    return all(term in normalized for term in terms)


def read_text_content(path: Path, limit: int = 400_000) -> str:
    """Texto do arquivo para a busca por conteudo, ou vazio se nao der para ler."""
    suffix = path.suffix.casefold()
    try:
        if suffix in TEXT_SUFFIXES:
            return path.read_text(encoding="utf-8", errors="ignore")[:limit]
        if suffix in OFFICE_SUFFIXES:
            import zipfile
            partes = []
            with zipfile.ZipFile(path) as pacote:
                for nome in pacote.namelist():
                    if not nome.endswith(".xml") or "/media/" in nome:
                        continue
                    bruto = pacote.read(nome).decode("utf-8", errors="ignore")
                    partes.append(re.sub(r"<[^>]+>", " ", bruto))
                    if sum(map(len, partes)) > limit:
                        break
            return " ".join(partes)[:limit]
        if suffix == ".pdf":
            try:
                import fitz
            except ImportError:
                try:
                    from pypdf import PdfReader
                except ImportError:
                    return ""
                leitor = PdfReader(str(path))
                return " ".join((pagina.extract_text() or "") for pagina in leitor.pages[:40])[:limit]
            with fitz.open(str(path)) as documento:
                return " ".join(pagina.get_text() for pagina in documento[:40])[:limit]
    except Exception:
        return ""
    return ""


def content_matches(path: Path, terms: list[str]) -> bool:
    texto = read_text_content(path)
    if not texto:
        return False
    return name_matches(texto, terms)


def iter_file_matches(root: Path, terms, suffixes, include_folders: bool,
                      inside_content: bool, stop, limit: int):
    """Percorre a pasta e entrega cada achado assim que encontra.

    Devolve tuplas ("achado", dados) e ("progresso", total_visitado), para a
    interface mostrar o resultado enquanto a varredura continua.
    """
    encontrados = 0
    visitados = 0
    for atual, pastas, arquivos in os.walk(root, onerror=lambda _: None):
        if stop.is_set():
            return
        pastas[:] = [p for p in pastas if p.casefold() not in SKIPPED_DIRS and not p.startswith("$")]
        pasta_atual = Path(atual)

        if include_folders and not suffixes:
            for nome in pastas:
                if stop.is_set() or encontrados >= limit:
                    return
                if name_matches(nome, terms):
                    encontrados += 1
                    yield "achado", describe_entry(pasta_atual / nome, True)

        for nome in arquivos:
            if stop.is_set():
                return
            visitados += 1
            if visitados % 400 == 0:
                yield "progresso", visitados
            if encontrados >= limit:
                return
            caminho = pasta_atual / nome
            if suffixes and caminho.suffix.casefold() not in suffixes:
                continue
            achou = name_matches(nome, terms)
            if not achou and inside_content:
                achou = content_matches(caminho, terms)
            if achou:
                encontrados += 1
                yield "achado", describe_entry(caminho, False)
    yield "progresso", visitados


def describe_entry(path: Path, is_folder: bool) -> dict:
    try:
        info = path.stat()
        tamanho, modificado = info.st_size, info.st_mtime
    except OSError:
        tamanho, modificado = 0, 0.0
    return {
        "name": path.name,
        "path": str(path),
        "folder": str(path if is_folder else path.parent),
        "isFolder": is_folder,
        "suffix": "" if is_folder else path.suffix.casefold(),
        "size": 0 if is_folder else tamanho,
        "modified": modificado,
    }


def relevance(entry: dict, terms: list[str]) -> tuple:
    """Nome exato primeiro, depois o que comeca com o termo, depois o resto."""
    alvo = normalize(entry["name"])
    junto = "".join(terms)
    if alvo == junto:
        posicao = 0
    elif alvo.startswith(junto):
        posicao = 1
    else:
        posicao = 2
    return (posicao, -entry["modified"], alvo)
