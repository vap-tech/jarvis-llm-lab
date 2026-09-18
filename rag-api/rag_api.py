#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import default
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import joblib
import numpy as np
from common import (
    ensure_dir,
    load_config,
    load_projects,
    project_data_dir,
    read_json,
    save_config,
)
from scipy import sparse

RU_STOPWORDS = {
    "а",
    "без",
    "бы",
    "в",
    "во",
    "где",
    "для",
    "и",
    "или",
    "как",
    "какой",
    "какая",
    "какие",
    "когда",
    "ли",
    "на",
    "над",
    "не",
    "но",
    "о",
    "об",
    "по",
    "под",
    "при",
    "про",
    "с",
    "со",
    "то",
    "у",
    "что",
    "это",
}

EN_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "what",
    "where",
}


@dataclass
class AppConfig:
    config_path: Path
    data_root: Path
    llm_base_url: str
    host: str
    port: int


@dataclass
class ProjectIndex:
    meta: dict[str, Any]
    chunks: list[dict[str, Any]]
    matrix: sparse.csr_matrix
    vectorizer: Any


def load_chunks(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            rows.append(json.loads(line))
    return rows


def tokenize(text: str) -> list[str]:
    terms = re.findall(r"[a-zA-Z0-9_+-]{3,}|[а-яА-ЯёЁ]{3,}", text.lower())
    return [
        term for term in terms if term not in RU_STOPWORDS and term not in EN_STOPWORDS
    ]


@lru_cache(maxsize=16)
def load_index(
    config_path_str: str, data_root_str: str, project_id: str
) -> ProjectIndex:
    data_root = Path(data_root_str)
    project_dir = project_data_dir(data_root, project_id)
    meta = read_json(project_dir / "meta.json")
    chunks = load_chunks(project_dir / "chunks.jsonl")
    matrix = sparse.load_npz(project_dir / "matrix.npz").tocsr()
    vectorizer = joblib.load(project_dir / "vectorizer.joblib")
    return ProjectIndex(meta=meta, chunks=chunks, matrix=matrix, vectorizer=vectorizer)


def available_projects(config_path: Path, data_root: Path) -> list[dict[str, Any]]:
    config = load_config(config_path)
    projects = []
    for item in config.get("projects", []):
        project_id = item["id"]
        meta_path = project_data_dir(data_root, project_id) / "meta.json"
        indexed = meta_path.exists()
        indexed_at = None
        chunk_count = 0
        if indexed:
            meta = read_json(meta_path)
            indexed_at = meta.get("indexed_at")
            chunk_count = int(meta.get("chunk_count", 0))
        projects.append(
            {
                "id": project_id,
                "label": item.get("label", project_id),
                "path": item["path"],
                "indexed": indexed,
                "indexed_at": indexed_at,
                "chunk_count": chunk_count,
            }
        )
    return projects


def persist_projects(config_path: Path, projects: list[dict[str, Any]]) -> None:
    config = load_config(config_path)
    config["projects"] = projects
    save_config(config_path, config)


def normalize_project_id(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-").lower()
    return cleaned


def validate_project_payload(payload: dict[str, Any]) -> tuple[str, str, str]:
    project_id = normalize_project_id(str(payload.get("id", "")))
    label = str(payload.get("label", "")).strip()
    path = str(payload.get("path", "")).strip()
    if not project_id:
        raise ValueError("missing_project_id")
    if not label:
        label = project_id
    if not path:
        raise ValueError("missing_project_path")
    return project_id, label, path


def parse_multipart(
    headers: dict[str, str], body: bytes
) -> tuple[dict[str, str], tuple[str, bytes] | None]:
    content_type = headers.get("Content-Type", "")
    if "multipart/form-data" not in content_type:
        raise ValueError("invalid_content_type")
    message = BytesParser(policy=default).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8")
        + body
    )
    fields: dict[str, str] = {}
    upload: tuple[str, bytes] | None = None
    for part in message.iter_parts():
        disposition = part.get("Content-Disposition", "")
        if "form-data" not in disposition:
            continue
        raw_name = part.get_param("name", header="content-disposition")
        name = raw_name if isinstance(raw_name, str) else None
        filename = part.get_filename()
        decoded = part.get_payload(decode=True)
        payload = decoded if isinstance(decoded, bytes) else b""
        if filename:
            upload = (filename, payload)
        elif name:
            fields[name] = payload.decode("utf-8", errors="ignore")
    return fields, upload


def safe_extract_zip(zip_path: Path, target_dir: Path) -> None:
    ensure_dir(target_dir)
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            member_path = Path(member.filename)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise ValueError("invalid_zip_path")
            destination = (target_dir / member_path).resolve()
            if not str(destination).startswith(str(target_dir.resolve())):
                raise ValueError("invalid_zip_path")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as src, destination.open("wb") as dst:
                dst.write(src.read())


def replace_directory(target_dir: Path) -> None:
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)


def resolve_active_model(app_config: AppConfig) -> str:
    try:
        with urlopen(f"{app_config.llm_base_url}/v1/models", timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError):
        return ""

    if isinstance(data.get("data"), list) and data["data"]:
        return data["data"][0].get("id", "")
    if isinstance(data.get("models"), list) and data["models"]:
        item = data["models"][0]
        return item.get("id") or item.get("model") or item.get("name") or ""
    return ""


def llm_ready(app_config: AppConfig) -> bool:
    try:
        with urlopen(f"{app_config.llm_base_url}/v1/models", timeout=5) as response:
            return response.status == 200
    except (OSError, URLError):
        return False


def wait_for_llm_ready(app_config: AppConfig, timeout_seconds: int = 300) -> None:
    started_at = time.monotonic()
    while time.monotonic() - started_at < timeout_seconds:
        if llm_ready(app_config):
            return
        time.sleep(2)
    raise TimeoutError("llama-server did not become ready in time")


def call_llm(
    app_config: AppConfig,
    messages: list[dict[str, str]],
    model_name: str,
    max_tokens: int,
    temperature: float = 0.1,
) -> str:
    payload = {
        "model": model_name or resolve_active_model(app_config),
        "stream": False,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    req = Request(
        f"{app_config.llm_base_url}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=180) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()


def expand_query(app_config: AppConfig, question: str, model_name: str) -> str:
    wait_for_llm_ready(app_config, timeout_seconds=300)
    prompt = (
        "Return only up to 10 short code search terms separated by spaces.\n"
        "Do not explain anything.\n"
        "Prefer English identifiers, abbreviations, API names and probable"
        " codebase terms.\n"
        f"Question: {question}"
    )
    raw = call_llm(
        app_config,
        [{"role": "user", "content": prompt}],
        model_name,
        180,
        temperature=0.0,
    )
    terms = tokenize(raw)
    if not terms:
        return question
    return f"{question} {' '.join(terms[:10])}"


def semantic_search(
    app_config: AppConfig,
    project_id: str,
    expanded_query: str,
    limit: int = 8,
) -> list[dict[str, Any]]:
    index_data = load_index(
        str(app_config.config_path), str(app_config.data_root), project_id
    )
    query_vec = index_data.vectorizer.transform([expanded_query])
    scores = (index_data.matrix @ query_vec.T).toarray().ravel()
    if scores.size == 0:
        return []
    top_ids = np.argsort(scores)[::-1][:limit]
    results = []
    for idx in top_ids:
        score = float(scores[idx])
        if score <= 0:
            continue
        chunk = dict(index_data.chunks[int(idx)])
        chunk["semantic_score"] = score
        results.append(chunk)
    return results


def keyword_search(
    app_config: AppConfig,
    project_id: str,
    expanded_query: str,
    limit: int = 8,
) -> list[dict[str, Any]]:
    terms = tokenize(expanded_query)
    if not terms:
        return []

    index_data = load_index(
        str(app_config.config_path), str(app_config.data_root), project_id
    )
    scored: list[tuple[int, dict[str, Any]]] = []
    for chunk in index_data.chunks:
        haystack = " ".join(
            [
                str(chunk.get("path", "")),
                str(chunk.get("symbol", "")),
                str(chunk.get("kind", "")),
                str(chunk.get("text", "")).lower(),
            ]
        )
        score = sum(haystack.count(term.lower()) for term in terms)
        if score:
            entry = dict(chunk)
            entry["keyword_score"] = score
            scored.append((score, entry))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in scored[:limit]]


def merge_results(
    semantic: list[dict[str, Any]],
    lexical: list[dict[str, Any]],
    limit: int = 6,
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for rank, chunk in enumerate(semantic):
        item = dict(chunk)
        item["hybrid_score"] = item.get("semantic_score", 0.0) + max(
            0.0, 1.0 - rank * 0.08
        )
        merged[item["id"]] = item

    for rank, chunk in enumerate(lexical):
        item = merged.get(chunk["id"], dict(chunk))
        item["hybrid_score"] = item.get("hybrid_score", 0.0) + max(
            0.0, 0.8 - rank * 0.08
        )
        merged[item["id"]] = item

    ordered = sorted(
        merged.values(),
        key=lambda item: item.get("hybrid_score", 0.0),
        reverse=True,
    )
    return ordered[:limit]


def fit_chunks_to_budget(
    chunks: list[dict[str, Any]], max_chars: int = 14000
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    used = 0
    for chunk in chunks:
        block = "\n".join(
            [
                f"FILE: {chunk['path']}",
                f"LINES: {chunk['start_line']}-{chunk['end_line']}",
                f"KIND: {chunk.get('kind') or 'unknown'}",
                f"SYMBOL: {chunk.get('symbol') or '-'}",
                chunk["text"],
            ]
        )
        if selected and used + len(block) > max_chars:
            break
        selected.append(chunk)
        used += len(block)
    return selected or chunks[:1]


def prompt_for_project(question: str, chunks: list[dict[str, Any]]) -> str:
    context_blocks = []
    for chunk in chunks:
        context_blocks.append(
            "\n".join(
                [
                    f"FILE: {chunk['path']}",
                    f"LINES: {chunk['start_line']}-{chunk['end_line']}",
                    f"KIND: {chunk.get('kind') or 'unknown'}",
                    f"SYMBOL: {chunk.get('symbol') or '-'}",
                    chunk["text"],
                ]
            )
        )
    joined_context = "\n\n---\n\n".join(context_blocks)
    return (
        "You are a senior software engineer helping with codebase navigation.\n"
        "Answer only from the provided repository context.\n"
        "If the context is insufficient, say so explicitly.\n"
        "Always reference the file paths you used.\n\n"
        f"Question:\n{question}\n\n"
        f"Repository context:\n{joined_context}\n"
    )


def run_indexer(
    app_config: AppConfig, project_id: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "/opt/archsrv-rag/app/index_repo.py",
            "--config",
            str(app_config.config_path),
            "--data-root",
            str(app_config.data_root),
            "--project",
            project_id,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


class Handler(BaseHTTPRequestHandler):
    app_config: AppConfig

    def log_message(self, format: str, *args: object) -> None:
        return

    def send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def do_OPTIONS(self) -> None:
        self.send_json(204, {})

    def do_GET(self) -> None:
        if self.path == "/health":
            self.send_json(200, {"ok": True})
            return
        if self.path == "/projects":
            self.send_json(
                200,
                {
                    "projects": available_projects(
                        self.app_config.config_path, self.app_config.data_root
                    )
                },
            )
            return
        self.send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        if self.path == "/index":
            try:
                payload = self.read_json()
            except json.JSONDecodeError:
                self.send_json(400, {"error": "invalid_json"})
                return
            project_id = payload.get("project", "")
            if project_id not in load_projects(self.app_config.config_path):
                self.send_json(400, {"error": "unknown_project"})
                return
            result = run_indexer(self.app_config, project_id)
            load_index.cache_clear()
            if result.returncode != 0:
                self.send_json(
                    500,
                    {
                        "error": "index_failed",
                        "stdout": result.stdout[-4000:],
                        "stderr": result.stderr[-4000:],
                    },
                )
                return
            meta = read_json(
                project_data_dir(self.app_config.data_root, project_id) / "meta.json"
            )
            self.send_json(200, {"ok": True, "meta": meta})
            return

        if self.path == "/projects/create":
            try:
                payload = self.read_json()
                project_id, label, path = validate_project_payload(payload)
            except json.JSONDecodeError:
                self.send_json(400, {"error": "invalid_json"})
                return
            except ValueError as err:
                self.send_json(400, {"error": str(err)})
                return

            try:
                config = load_config(self.app_config.config_path)
                projects = config.get("projects", [])
                if any(str(item.get("id", "")) == project_id for item in projects):
                    self.send_json(409, {"error": "project_exists"})
                    return

                ensure_dir(Path(path))
                projects.append({"id": project_id, "label": label, "path": path})
                persist_projects(self.app_config.config_path, projects)
                self.send_json(
                    200,
                    {
                        "ok": True,
                        "projects": available_projects(
                            self.app_config.config_path, self.app_config.data_root
                        ),
                    },
                )
                return
            except PermissionError as err:
                self.send_json(
                    500, {"error": "config_write_denied", "detail": str(err)}
                )
                return

        if self.path == "/projects/update":
            try:
                payload = self.read_json()
                project_id, label, path = validate_project_payload(payload)
            except json.JSONDecodeError:
                self.send_json(400, {"error": "invalid_json"})
                return
            except ValueError as err:
                self.send_json(400, {"error": str(err)})
                return

            try:
                config = load_config(self.app_config.config_path)
                projects = config.get("projects", [])
                updated = False
                for item in projects:
                    if str(item.get("id", "")) == project_id:
                        item["label"] = label
                        item["path"] = path
                        updated = True
                        break
                if not updated:
                    self.send_json(404, {"error": "project_not_found"})
                    return

                ensure_dir(Path(path))
                persist_projects(self.app_config.config_path, projects)
                load_index.cache_clear()
                self.send_json(
                    200,
                    {
                        "ok": True,
                        "projects": available_projects(
                            self.app_config.config_path, self.app_config.data_root
                        ),
                    },
                )
                return
            except PermissionError as err:
                self.send_json(
                    500, {"error": "config_write_denied", "detail": str(err)}
                )
                return

        if self.path == "/projects/delete":
            try:
                payload = self.read_json()
            except json.JSONDecodeError:
                self.send_json(400, {"error": "invalid_json"})
                return

            project_id = normalize_project_id(str(payload.get("id", "")))
            purge_files = str(payload.get("purge_files", "")).lower() in (
                "1",
                "true",
                "yes",
                "on",
            )
            if not project_id:
                self.send_json(400, {"error": "missing_project_id"})
                return

            try:
                config = load_config(self.app_config.config_path)
                projects = config.get("projects", [])
                existing = next(
                    (
                        item
                        for item in projects
                        if str(item.get("id", "")) == project_id
                    ),
                    None,
                )
                next_projects = [
                    item for item in projects if str(item.get("id", "")) != project_id
                ]
                if len(next_projects) == len(projects):
                    self.send_json(404, {"error": "project_not_found"})
                    return

                persist_projects(self.app_config.config_path, next_projects)
                if purge_files and existing:
                    project_path = Path(str(existing.get("path", "")))
                    if project_path.exists() and str(project_path).startswith(
                        "/srv/projects/"
                    ):
                        shutil.rmtree(project_path, ignore_errors=True)
                    rag_path = project_data_dir(self.app_config.data_root, project_id)
                    if rag_path.exists():
                        shutil.rmtree(rag_path, ignore_errors=True)
                load_index.cache_clear()
                self.send_json(
                    200,
                    {
                        "ok": True,
                        "projects": available_projects(
                            self.app_config.config_path, self.app_config.data_root
                        ),
                    },
                )
                return
            except PermissionError as err:
                self.send_json(
                    500, {"error": "config_write_denied", "detail": str(err)}
                )
                return

        if self.path == "/projects/import-zip":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length) if length else b""
                fields, upload = parse_multipart(dict(self.headers.items()), body)
                project_id = normalize_project_id(fields.get("id", ""))
                label = fields.get("label", "").strip() or project_id
                replace_existing = fields.get("replace_existing", "").lower() in (
                    "1",
                    "true",
                    "yes",
                    "on",
                )
                if not project_id:
                    self.send_json(400, {"error": "missing_project_id"})
                    return
                if upload is None:
                    self.send_json(400, {"error": "missing_zip"})
                    return
                filename, payload = upload
                if not filename.lower().endswith(".zip"):
                    self.send_json(400, {"error": "invalid_zip_name"})
                    return
            except ValueError as err:
                self.send_json(400, {"error": str(err)})
                return

            target_path = Path("/srv/projects") / project_id
            try:
                config = load_config(self.app_config.config_path)
                projects = config.get("projects", [])
                existing = next(
                    (
                        item
                        for item in projects
                        if str(item.get("id", "")) == project_id
                    ),
                    None,
                )
                if existing and not replace_existing:
                    self.send_json(409, {"error": "project_exists"})
                    return

                with tempfile.TemporaryDirectory(prefix="archsrv-rag-") as tmpdir:
                    zip_path = Path(tmpdir) / "upload.zip"
                    zip_path.write_bytes(payload)
                    replace_directory(target_path)
                    safe_extract_zip(zip_path, target_path)

                if existing:
                    existing["label"] = label
                    existing["path"] = str(target_path)
                else:
                    projects.append(
                        {"id": project_id, "label": label, "path": str(target_path)}
                    )
                persist_projects(self.app_config.config_path, projects)
                load_index.cache_clear()
                result = run_indexer(self.app_config, project_id)
                if result.returncode != 0:
                    self.send_json(
                        500,
                        {
                            "error": "index_failed",
                            "stdout": result.stdout[-4000:],
                            "stderr": result.stderr[-4000:],
                        },
                    )
                    return
                meta = read_json(
                    project_data_dir(self.app_config.data_root, project_id)
                    / "meta.json"
                )
                self.send_json(
                    200,
                    {
                        "ok": True,
                        "project": project_id,
                        "meta": meta,
                        "projects": available_projects(
                            self.app_config.config_path, self.app_config.data_root
                        ),
                    },
                )
                return
            except PermissionError as err:
                self.send_json(
                    500, {"error": "config_write_denied", "detail": str(err)}
                )
                return
            except zipfile.BadZipFile:
                self.send_json(400, {"error": "invalid_zip"})
                return
            except ValueError as err:
                self.send_json(400, {"error": str(err)})
                return
            except OSError as err:
                self.send_json(500, {"error": "import_failed", "detail": str(err)})
                return

        if self.path == "/ask":
            try:
                payload = self.read_json()
            except json.JSONDecodeError:
                self.send_json(400, {"error": "invalid_json"})
                return

            project_id = payload.get("project", "")
            question = str(payload.get("question", "")).strip()
            model_name = str(payload.get("model", "")).strip()
            max_tokens = int(payload.get("max_tokens", 900) or 900)

            if not question:
                self.send_json(400, {"error": "missing_question"})
                return
            if project_id not in load_projects(self.app_config.config_path):
                self.send_json(400, {"error": "unknown_project"})
                return

            project_dir = project_data_dir(self.app_config.data_root, project_id)
            if not (project_dir / "meta.json").exists():
                self.send_json(409, {"error": "project_not_indexed"})
                return

            try:
                expanded_query = expand_query(self.app_config, question, model_name)
                semantic = semantic_search(self.app_config, project_id, expanded_query)
                lexical = keyword_search(self.app_config, project_id, expanded_query)
                chunks = fit_chunks_to_budget(merge_results(semantic, lexical))
                wait_for_llm_ready(self.app_config, timeout_seconds=300)
                answer = call_llm(
                    self.app_config,
                    [{"role": "user", "content": prompt_for_project(question, chunks)}],
                    model_name,
                    max_tokens,
                )
            except TimeoutError as err:
                self.send_json(503, {"error": "model_not_ready", "detail": str(err)})
                return
            except HTTPError as err:
                detail = err.read().decode("utf-8", errors="ignore")
                self.send_json(
                    502,
                    {
                        "error": "llm_request_failed",
                        "status": err.code,
                        "detail": detail or str(err),
                    },
                )
                return
            except (OSError, URLError) as err:
                self.send_json(
                    502,
                    {"error": "llm_unreachable", "detail": str(err)},
                )
                return

            self.send_json(
                200,
                {
                    "answer": answer,
                    "expanded_query": expanded_query,
                    "sources": [
                        {
                            "path": chunk["path"],
                            "start_line": chunk["start_line"],
                            "end_line": chunk["end_line"],
                            "symbol": chunk.get("symbol", ""),
                        }
                        for chunk in chunks
                    ],
                },
            )
            return

        self.send_json(404, {"error": "not_found"})


def parse_args() -> AppConfig:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--llm-base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8082)
    args = parser.parse_args()
    return AppConfig(
        config_path=Path(args.config),
        data_root=Path(args.data_root),
        llm_base_url=args.llm_base_url.rstrip("/"),
        host=args.host,
        port=args.port,
    )


def main() -> int:
    Handler.app_config = parse_args()
    server = ThreadingHTTPServer(
        (Handler.app_config.host, Handler.app_config.port), Handler
    )
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
