"""
실험 종료 시 Slack 알림 (전역 훅 호출).

사용:
    from experiments.shared import notify
    notify.register(version="v8")          # main() 시작부
    ...
    notify.set_summary("50/50 trials, correct=41 (82%)")  # 결과 확정 후

atexit + sys.excepthook 조합으로 정상 종료·Ctrl-C(SIGINT)·SIGTERM·미처리 예외
모두 포착. SIGKILL만 누락.
"""
import atexit
import json
import os
import subprocess
import sys
import time
import traceback
from typing import Optional

_HOOK = "/Users/yumunsang/.claude/hooks/experiment-done-notify.sh"
_started = False
_start_time = 0.0
_state = {
    "version": None,
    "fault": None,
    "trial": None,
    "summary": "",
    "error": None,
}


def register(
    version: str,
    fault: Optional[str] = None,
    trial: Optional[int] = None,
) -> None:
    global _started, _start_time
    if _started:
        return
    _started = True
    _start_time = time.time()
    _state["version"] = version
    _state["fault"] = fault
    _state["trial"] = trial
    atexit.register(_send)
    sys.excepthook = _excepthook


def set_summary(text: str) -> None:
    _state["summary"] = text


def set_context(fault: Optional[str] = None, trial: Optional[int] = None) -> None:
    if fault is not None:
        _state["fault"] = fault
    if trial is not None:
        _state["trial"] = trial


def _excepthook(exc_type, exc, tb):
    _state["error"] = f"{exc_type.__name__}: {exc}"
    traceback.print_exception(exc_type, exc, tb)


def _send():
    if not os.path.exists(_HOOK):
        return
    duration = int(time.time() - _start_time) if _start_time else 0
    payload = {
        "version": _state["version"] or "?",
        "fault": _state["fault"],
        "trial": _state["trial"],
        "duration_s": duration,
        "exit_code": 0 if _state["error"] is None else 1,
        "error": _state["error"],
        "summary": _state["summary"],
    }
    try:
        subprocess.run(
            [_HOOK],
            input=json.dumps(payload, ensure_ascii=False),
            text=True,
            timeout=10,
            check=False,
        )
    except Exception:
        pass
