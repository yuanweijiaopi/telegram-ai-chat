import json
import os
import subprocess
import sys
import time
from datetime import datetime, time as dt_time

import psutil
from dotenv import dotenv_values
from shared.paths import CHAT_LOG, CHAT_PID_FILE, ENV_FILE, PROJECT_ROOT, ensure_runtime_dirs

ensure_runtime_dirs()
PROJECT_DIR = str(PROJECT_ROOT)
PID_FILE = str(CHAT_PID_FILE)


def load_current_env() -> dict:
    return dict(dotenv_values(ENV_FILE)) if os.path.exists(ENV_FILE) else {}


def save_env(data: dict) -> None:
    with open(ENV_FILE, "w", encoding="utf-8") as f:
        for key, value in data.items():
            encoded = json.dumps("" if value is None else str(value), ensure_ascii=False)
            f.write(f"{key}={encoded}\n")


def append_runtime_log(message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(CHAT_LOG, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {message}\n")


def safe_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _read_pid_file() -> int | None:
    if not os.path.exists(PID_FILE):
        return None
    try:
        return int(open(PID_FILE).read().strip())
    except Exception:
        return None


def _write_pid_file(pid: int) -> None:
    with open(PID_FILE, "w", encoding="utf-8") as f:
        f.write(str(pid))


def _remove_pid_file() -> None:
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)


def _is_project_bot_process(proc: psutil.Process) -> bool:
    try:
        if proc.pid == os.getpid():
            return False
        cmdline = proc.info.get("cmdline") if hasattr(proc, "info") else proc.cmdline()
        cwd = proc.info.get("cwd") if hasattr(proc, "info") else proc.cwd()
        cmdline = cmdline or []
        if not cmdline:
            return False
        if os.path.abspath(cwd or "") == PROJECT_DIR and any(
            part.endswith("main.py") or part == "main.py" for part in cmdline
        ):
            return True
        main_path = os.path.join(PROJECT_DIR, "main.py")
        return any(os.path.abspath(part) == main_path for part in cmdline if part)
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False


def _find_bot_processes() -> list[psutil.Process]:
    return [
        proc
        for proc in psutil.process_iter(["pid", "cmdline", "cwd"])
        if _is_project_bot_process(proc)
    ]


def is_running() -> bool:
    pid = _read_pid_file()
    if pid is not None:
        try:
            proc = psutil.Process(pid)
            if _is_project_bot_process(proc):
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

    bot_processes = _find_bot_processes()
    if bot_processes:
        _write_pid_file(bot_processes[0].pid)
        return True

    _remove_pid_file()
    return False


def start_bot() -> None:
    if is_running():
        return
    proc = subprocess.Popen(
        [sys.executable, "-u", "main.py"],
        stdout=open(CHAT_LOG, "a", encoding="utf-8"),
        stderr=subprocess.STDOUT,
        cwd=PROJECT_DIR,
    )
    _write_pid_file(proc.pid)


def stop_bot() -> None:
    seen_pids = set()
    targets: list[psutil.Process] = []

    pid = _read_pid_file()
    if pid is not None:
        try:
            proc = psutil.Process(pid)
            if _is_project_bot_process(proc):
                targets.append(proc)
                seen_pids.add(proc.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

    for proc in _find_bot_processes():
        if proc.pid not in seen_pids:
            targets.append(proc)
            seen_pids.add(proc.pid)

    for parent in targets:
        try:
            for child in parent.children(recursive=True):
                child.kill()
            parent.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

    _remove_pid_file()


def parse_hhmm(value: str | None, default: str) -> dt_time:
    for candidate in ((value or "").strip(), default):
        if not candidate:
            continue
        try:
            hour_str, minute_str = candidate.split(":", 1)
            return dt_time(hour=int(hour_str), minute=int(minute_str))
        except (ValueError, TypeError):
            continue
    return dt_time(hour=0, minute=0)


def normalize_time_value(value) -> str:
    if hasattr(value, "hour") and hasattr(value, "minute"):
        return f"{value.hour:02d}:{value.minute:02d}"
    return str(value or "").strip()


def _hhmm_to_minutes(value: dt_time) -> int:
    return value.hour * 60 + value.minute


def is_within_schedule_window(current_env: dict) -> bool:
    now = datetime.now()
    if current_env.get("AUTO_SCHEDULE_WEEKDAYS_ONLY", "false") == "true" and now.weekday() >= 5:
        return False

    start_minutes = _hhmm_to_minutes(parse_hhmm(current_env.get("AUTO_SCHEDULE_START"), "09:00"))
    stop_minutes = _hhmm_to_minutes(parse_hhmm(current_env.get("AUTO_SCHEDULE_STOP"), "23:00"))
    if start_minutes == stop_minutes:
        return False

    now_minutes = now.hour * 60 + now.minute
    if start_minutes < stop_minutes:
        return start_minutes <= now_minutes < stop_minutes
    return now_minutes >= start_minutes or now_minutes < stop_minutes


def scheduler_loop() -> None:
    last_error = None
    while True:
        try:
            current_env = load_current_env()
            if current_env.get("AUTO_SCHEDULE_ENABLED", "false") == "true":
                should_run = is_within_schedule_window(current_env)
                running = is_running()
                if should_run and not running:
                    start_bot()
                    append_runtime_log("[定时任务] 到达开启时间，已自动启动机器人")
                elif not should_run and running:
                    stop_bot()
                    append_runtime_log("[定时任务] 到达关闭时间，已自动停止机器人")
            last_error = None
        except Exception as exc:
            error_signature = repr(exc)
            if last_error != error_signature:
                append_runtime_log(f"[定时任务] 调度器异常：{exc}")
                last_error = error_signature
        time.sleep(20)
