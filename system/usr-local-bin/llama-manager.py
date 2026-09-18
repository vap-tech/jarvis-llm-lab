#!/usr/bin/env python3
import json
import shlex
import shutil
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

CONFIG_DIR = Path("/etc/llama-server")
CURRENT_ENV = CONFIG_DIR / "current.env"


def parse_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key] = unquote_env(value)
    return data


def unquote_env(value: str) -> str:
    text = value.strip()
    if not text:
        return text
    if text[0] == text[-1] and text[0] in ("'", '"'):
        try:
            parts = shlex.split(f"v={text}", posix=True)
            if parts and "=" in parts[0]:
                return parts[0].split("=", 1)[1]
        except ValueError:
            return text[1:-1]
    return text


def load_profiles() -> list[dict[str, object]]:
    profiles: list[dict[str, object]] = []
    for path in sorted(CONFIG_DIR.glob("model-*.env")):
        env = parse_env(path)
        profile_id = env.get("PROFILE_ID")
        if not profile_id:
            continue
        profiles.append(
            {
                "id": profile_id,
                "label": env.get("PROFILE_LABEL", profile_id),
                "model": env.get("MODEL_REPO", ""),
                "file": env.get("MODEL_FILE", ""),
                "context": int(env.get("N_CTX", "0") or "0"),
            }
        )
    return profiles


def current_profile_id() -> str | None:
    if not CURRENT_ENV.exists():
        return None
    return parse_env(CURRENT_ENV).get("PROFILE_ID")


def current_profile() -> dict[str, str]:
    if not CURRENT_ENV.exists():
        return {}
    return parse_env(CURRENT_ENV)


def service_status() -> str:
    result = subprocess.run(
        ["systemctl", "is-active", "llama-server.service"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() or "unknown"


def backend_ready() -> bool:
    try:
        with urlopen("http://127.0.0.1:8080/v1/models", timeout=2) as response:
            return response.status == 200
    except (OSError, URLError):
        return False


def download_in_progress() -> bool:
    env = current_profile()
    model_repo = env.get("MODEL_REPO")
    if not model_repo:
        return False

    cache_key = "models--" + model_repo.replace("/", "--")
    cache_dir = Path("/home/kot/.cache/huggingface/hub") / cache_key / "blobs"
    if not cache_dir.exists():
        return False

    return any(cache_dir.glob("*.downloadInProgress"))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return

    def _send(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self._send(204, {})

    def do_GET(self) -> None:
        if self.path not in ("/profiles", "/state"):
            self._send(404, {"error": "not_found"})
            return
        self._send(
            200,
            {
                "profiles": load_profiles(),
                "active": current_profile_id(),
                "service": service_status(),
                "backend_ready": backend_ready(),
                "downloading": download_in_progress(),
            },
        )

    def do_POST(self) -> None:
        if self.path != "/select":
            self._send(404, {"error": "not_found"})
            return

        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b"{}"

        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self._send(400, {"error": "invalid_json"})
            return

        target = data.get("id")
        profiles = {item["id"]: item for item in load_profiles()}
        if target not in profiles:
            self._send(400, {"error": "unknown_profile"})
            return

        shutil.copyfile(CONFIG_DIR / f"model-{target}.env", CURRENT_ENV)
        subprocess.run(["systemctl", "restart", "llama-server.service"], check=True)

        self._send(
            200,
            {
                "ok": True,
                "active": target,
                "service": service_status(),
                "backend_ready": backend_ready(),
                "downloading": download_in_progress(),
            },
        )


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", 8081), Handler)
    server.serve_forever()
