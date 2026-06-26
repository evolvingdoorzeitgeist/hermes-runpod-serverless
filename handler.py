import re
import subprocess
import uuid
from pathlib import Path
from datetime import datetime, timezone

import runpod

OUTPUT_DIR = Path("/workspace/outputs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SIMPLE_FILENAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def run_cmd(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    return {
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def safe_filename(name: str) -> str:
    name = (name or "").strip()

    if not name:
        raise ValueError("Filename is empty")

    if name.startswith("/") or name.startswith("\\"):
        raise ValueError("Absolute paths are not allowed")

    if "/" in name or "\\" in name or ".." in name:
        raise ValueError("Path traversal is not allowed")

    if not SIMPLE_FILENAME_RE.fullmatch(name):
        raise ValueError("Filename contains invalid characters")

    return name


def health():
    gpu_check = run_cmd([
        "nvidia-smi",
        "--query-gpu=name,memory.total,memory.used",
        "--format=csv,noheader",
    ])

    return {
        "status": "ok",
        "worker": "hermes-runpod-serverless",
        "gpu": gpu_check["stdout"] if gpu_check["returncode"] == 0 else None,
        "gpu_error": gpu_check["stderr"] if gpu_check["returncode"] != 0 else None,
        "outputs_path": str(OUTPUT_DIR),
    }


def ffmpeg_check():
    result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True)

    return {
        "status": "ok",
        "ffmpeg": result.stdout.splitlines()[0] if result.stdout else "unknown",
    }


def echo(job_input):
    return {
        "status": "ok",
        "job_id": str(uuid.uuid4()),
        "message": job_input.get("message", ""),
    }


def write_test(job_input):
    filename = safe_filename(job_input.get("filename", "serverless_test.txt"))
    content = job_input.get("content", "")

    target = (OUTPUT_DIR / filename).resolve()

    if target.parent != OUTPUT_DIR.resolve():
        raise ValueError("Invalid output path")

    target.write_text(content, encoding="utf-8")

    return {
        "status": "ok",
        "job_id": str(uuid.uuid4()),
        "path": str(target),
        "filename": filename,
        "size_bytes": target.stat().st_size,
    }


def list_outputs():
    files = []

    if OUTPUT_DIR.exists():
        for p in sorted(
            OUTPUT_DIR.iterdir(),
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        ):
            if not p.is_file():
                continue

            st = p.stat()
            files.append({
                "filename": p.name,
                "path": str(p),
                "size_bytes": st.st_size,
                "modified": datetime.fromtimestamp(
                    st.st_mtime,
                    tz=timezone.utc,
                ).isoformat(),
            })

    return {
        "status": "ok",
        "outputs_path": str(OUTPUT_DIR),
        "files": files,
    }


def handler(job):
    job_input = job.get("input", {}) or {}
    action = job_input.get("action")

    try:
        if action == "health":
            return health()

        if action == "ffmpeg":
            return ffmpeg_check()

        if action == "echo":
            return echo(job_input)

        if action == "write_test":
            return write_test(job_input)

        if action == "list_outputs":
            return list_outputs()

        return {
            "status": "error",
            "error": f"Unknown action: {action}",
            "supported_actions": [
                "health",
                "ffmpeg",
                "echo",
                "write_test",
                "list_outputs",
            ],
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "action": action,
        }


runpod.serverless.start({"handler": handler})
