from __future__ import annotations

import json
from pathlib import Path


def load_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_config(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_projects(path: Path) -> dict[str, dict]:
    config = load_config(path)
    projects = config.get("projects", [])
    return {
        item["id"]: item for item in projects if item.get("id") and item.get("path")
    }


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def project_data_dir(data_root: Path, project_id: str) -> Path:
    return data_root / project_id


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
