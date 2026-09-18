#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, cast

import joblib
from common import ensure_dir, load_projects, project_data_dir, write_json
from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer

try:
    from tree_sitter_language_pack import get_parser
except Exception:  # pragma: no cover - optional fallback
    get_parser = None


DEFAULT_MAX_CHUNK_LINES = 120
DEFAULT_WINDOW_LINES = 80
DEFAULT_WINDOW_OVERLAP = 20

SUPPORTED_EXTENSIONS = {
    ".c": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cs": "c_sharp",
    ".css": "css",
    ".go": "go",
    ".h": "c",
    ".hpp": "cpp",
    ".html": "html",
    ".java": "java",
    ".js": "javascript",
    ".json": None,
    ".jsx": "javascript",
    ".kt": "kotlin",
    ".lua": "lua",
    ".md": None,
    ".php": "php",
    ".py": "python",
    ".rb": "ruby",
    ".rs": "rust",
    ".sh": "bash",
    ".sql": None,
    ".swift": "swift",
    ".toml": None,
    ".ts": "typescript",
    ".tsx": "tsx",
    ".vue": "vue",
    ".xml": None,
    ".yaml": None,
    ".yml": None,
}

SKIP_DIRS = {
    ".git",
    ".idea",
    ".venv",
    ".vscode",
    "build",
    "dist",
    "node_modules",
    "target",
}

INTERESTING_NODE_TYPES = {
    "arrow_function",
    "class",
    "class_body",
    "class_declaration",
    "class_definition",
    "declaration",
    "export_statement",
    "function",
    "function_declaration",
    "function_definition",
    "impl_item",
    "interface_declaration",
    "lexical_declaration",
    "method_declaration",
    "method_definition",
    "module",
    "object_type",
    "program",
    "struct_item",
    "trait_item",
    "type_alias_declaration",
}


@dataclass
class Chunk:
    id: str
    path: str
    language: str
    kind: str
    symbol: str
    start_line: int
    end_line: int
    text: str

    @property
    def search_text(self) -> str:
        parts = [f"path {self.path}", f"language {self.language}", self.kind]
        if self.symbol:
            parts.append(self.symbol)
        parts.append(self.text)
        return "\n".join(parts)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def iter_repo_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        yield path


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")


def normalize_symbol(text: str) -> str:
    head = " ".join(line.strip() for line in text.splitlines()[:3]).strip()
    return head[:120]


def make_chunk_id(path: str, start_line: int, end_line: int, text: str) -> str:
    digest = hashlib.sha1(
        f"{path}:{start_line}:{end_line}:{text}".encode("utf-8")
    ).hexdigest()
    return digest[:16]


def chunk_from_lines(
    rel_path: str,
    language: str,
    kind: str,
    symbol: str,
    lines: list[str],
    start_line: int,
    end_line: int,
) -> Chunk | None:
    body = "\n".join(lines).strip()
    if not body:
        return None
    return Chunk(
        id=make_chunk_id(rel_path, start_line, end_line, body),
        path=rel_path,
        language=language,
        kind=kind,
        symbol=symbol,
        start_line=start_line,
        end_line=end_line,
        text=body,
    )


def fallback_chunk_file(path: Path, repo_root: Path, language: str) -> list[Chunk]:
    rel_path = path.relative_to(repo_root).as_posix()
    lines = read_text(path).splitlines()
    chunks: list[Chunk] = []
    if not lines:
        return chunks

    if len(lines) <= DEFAULT_WINDOW_LINES:
        chunk = chunk_from_lines(
            rel_path,
            language,
            "file",
            path.name,
            lines,
            1,
            len(lines),
        )
        return [chunk] if chunk else []

    step = max(DEFAULT_WINDOW_LINES - DEFAULT_WINDOW_OVERLAP, 1)
    for start in range(0, len(lines), step):
        end = min(start + DEFAULT_WINDOW_LINES, len(lines))
        chunk = chunk_from_lines(
            rel_path,
            language,
            "window",
            path.name,
            lines[start:end],
            start + 1,
            end,
        )
        if chunk:
            chunks.append(chunk)
        if end >= len(lines):
            break
    return chunks


def walk_named_nodes(node, depth: int = 0):
    if depth > 3:
        return
    for child in getattr(node, "named_children", []):
        yield child
        yield from walk_named_nodes(child, depth + 1)


def parser_for_language(language: str):
    if get_parser is None or language in (None, ""):
        return None
    try:
        return get_parser(cast(Any, language))
    except Exception:
        return None


def tree_sitter_chunk_file(path: Path, repo_root: Path, language: str) -> list[Chunk]:
    parser = parser_for_language(language)
    if parser is None:
        return fallback_chunk_file(path, repo_root, language)

    text = read_text(path)
    if not text.strip():
        return []

    rel_path = path.relative_to(repo_root).as_posix()
    tree = parser.parse(text.encode("utf-8", errors="ignore"))
    lines = text.splitlines()
    chunks: list[Chunk] = []
    seen_ranges: set[tuple[int, int]] = set()

    for node in walk_named_nodes(tree.root_node):
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        line_count = end_line - start_line + 1
        if line_count < 5 or line_count > DEFAULT_MAX_CHUNK_LINES:
            continue
        node_type = getattr(node, "type", "")
        if (
            node_type not in INTERESTING_NODE_TYPES
            and "function" not in node_type
            and "class" not in node_type
            and "method" not in node_type
            and "interface" not in node_type
        ):
            continue
        key = (start_line, end_line)
        if key in seen_ranges:
            continue
        seen_ranges.add(key)
        snippet_lines = lines[start_line - 1 : end_line]
        chunk = chunk_from_lines(
            rel_path,
            language,
            node_type,
            normalize_symbol("\n".join(snippet_lines)),
            snippet_lines,
            start_line,
            end_line,
        )
        if chunk:
            chunks.append(chunk)

    if chunks:
        return chunks
    return fallback_chunk_file(path, repo_root, language)


def chunks_for_file(path: Path, repo_root: Path) -> list[Chunk]:
    language = SUPPORTED_EXTENSIONS.get(
        path.suffix.lower()
    ) or path.suffix.lower().lstrip(".")
    return tree_sitter_chunk_file(path, repo_root, language)


def save_chunks(path: Path, chunks: list[Chunk]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(
                json.dumps(
                    {
                        "id": chunk.id,
                        "path": chunk.path,
                        "language": chunk.language,
                        "kind": chunk.kind,
                        "symbol": chunk.symbol,
                        "start_line": chunk.start_line,
                        "end_line": chunk.end_line,
                        "text": chunk.text,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


def build_vectorizer(chunks: list[Chunk]) -> tuple[TfidfVectorizer, sparse.csr_matrix]:
    vectorizer = TfidfVectorizer(
        lowercase=True,
        ngram_range=(1, 2),
        max_features=50000,
        token_pattern=r"(?u)\b\w+\b",
    )
    matrix = cast(
        sparse.csr_matrix,
        vectorizer.fit_transform([chunk.search_text for chunk in chunks]),
    )
    return vectorizer, matrix


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--project", required=True)
    args = parser.parse_args()

    config_path = Path(args.config)
    data_root = Path(args.data_root)
    projects = load_projects(config_path)
    project = projects.get(args.project)
    if project is None:
        raise SystemExit(f"unknown project: {args.project}")

    repo_root = Path(project["path"]).expanduser().resolve()
    if not repo_root.exists():
        raise SystemExit(f"missing repo path: {repo_root}")

    chunks: list[Chunk] = []
    for file_path in sorted(iter_repo_files(repo_root)):
        chunks.extend(chunks_for_file(file_path, repo_root))

    if not chunks:
        raise SystemExit("no chunks produced")

    vectorizer, matrix = build_vectorizer(chunks)

    out_dir = project_data_dir(data_root, args.project)
    ensure_dir(out_dir)
    sparse.save_npz(out_dir / "matrix.npz", matrix)
    joblib.dump(vectorizer, out_dir / "vectorizer.joblib")
    save_chunks(out_dir / "chunks.jsonl", chunks)
    write_json(
        out_dir / "meta.json",
        {
            "project": args.project,
            "label": project.get("label", args.project),
            "repo_path": str(repo_root),
            "chunk_count": len(chunks),
            "indexed_at": utc_now(),
            "vectorizer_features": int(len(vectorizer.vocabulary_)),
        },
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
