#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


def main() -> int:
    env = os.environ.copy()
    env["INTERRUPT_WAKE_WORD_FACTORY"] = "src.mock_wakeword:factory"
    env["INTERRUPT_FRONTGATE_SESSION_COMMAND"] = "python3 -c 'print(\"session ok from smoke test\")'"
    command = [
        str(ROOT_DIR / "run_frontgate_session.sh"),
        "--once",
        "--wakeword",
        "笨笨同学",
    ]
    completed = subprocess.run(
        command,
        input="笨笨同学\n",
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    required_markers = [
        "[FrontGate] wake_detected",
        "session ok from smoke test",
        "[FrontGate] session_exit returncode=0",
    ]
    missing = [marker for marker in required_markers if marker not in stdout]
    if completed.returncode != 0 or missing:
        print("frontgate smoke test failed", file=sys.stderr)
        print(f"returncode={completed.returncode}", file=sys.stderr)
        if missing:
            print(f"missing={missing}", file=sys.stderr)
        if stdout:
            print("stdout:", file=sys.stderr)
            print(stdout, file=sys.stderr)
        if stderr:
            print("stderr:", file=sys.stderr)
            print(stderr, file=sys.stderr)
        return 1

    print("frontgate smoke test passed")
    print(stdout.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
