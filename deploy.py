import subprocess
import sys


LOCAL_DIR = "REDACTED_LOCAL_PATH"
REMOTE_HOST = "root@REDACTED_IP"
REMOTE_DIR = "/root/telegram-ai-chat"
EXCLUDES = [
    ".venv",
    "__pycache__",
    ".env",
    "sessions",
    "chat.log",
    "strategy.log",
    ".bot.pid",
]


def run(cmd: list[str]) -> None:
    print("==>", " ".join(cmd))
    subprocess.run(cmd, check=True)


def main() -> int:
    rsync_cmd = ["rsync", "-av"]
    for item in EXCLUDES:
        rsync_cmd.append(f"--exclude={item}")
    rsync_cmd.extend([LOCAL_DIR, f"{REMOTE_HOST}:{REMOTE_DIR}/"])

    remote_cmd = (
        f"cd {REMOTE_DIR} && "
        "docker compose down && "
        "docker compose up -d --build"
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
