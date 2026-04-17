import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOCAL_DIR = os.getenv("DEPLOY_LOCAL_DIR", str(PROJECT_ROOT) + "/")
REMOTE_HOST = os.getenv("DEPLOY_REMOTE_HOST", "")
REMOTE_DIR = os.getenv("DEPLOY_REMOTE_DIR", "")
EXCLUDES = [
    ".venv",
    "__pycache__",
    ".env",
    "sessions",
    "data",
    "logs",
    "run",
]


def run(cmd: list[str]) -> None:
    print("==>", " ".join(cmd))
    subprocess.run(cmd, check=True)


def main() -> int:
    if not REMOTE_HOST or not REMOTE_DIR:
        print(
            "错误：请设置环境变量 DEPLOY_REMOTE_HOST 和 DEPLOY_REMOTE_DIR\n"
            "示例：\n"
            "  export DEPLOY_REMOTE_HOST=user@your-server-ip\n"
            "  export DEPLOY_REMOTE_DIR=/home/user/telegram-ai-chat\n",
            file=sys.stderr,
        )
        return 1

    rsync_cmd = ["rsync", "-av"]
    for item in EXCLUDES:
        rsync_cmd.append(f"--exclude={item}")
    rsync_cmd.extend([LOCAL_DIR, f"{REMOTE_HOST}:{REMOTE_DIR}/"])

    remote_cmd = (
        f"cd {REMOTE_DIR} && "
        "docker compose -f infra/docker-compose.yml down && "
        "docker compose -f infra/docker-compose.yml up -d --build"
    )

    print("==> Syncing project to server...")
    run(rsync_cmd)

    print("==> Restarting docker compose on server...")
    run(["ssh", REMOTE_HOST, remote_cmd])

    print("==> Deploy finished")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"Deploy failed with exit code {exc.returncode}", file=sys.stderr)
        raise SystemExit(exc.returncode)
