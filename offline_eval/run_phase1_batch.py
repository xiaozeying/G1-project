#!/usr/bin/env python3
import argparse
import asyncio
import csv
import os
import queue
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import websockets


ROOT = Path(__file__).resolve().parents[1]
OM1_DIR = ROOT / "OM1"
DEFAULT_CASES = ROOT / "offline_eval" / "phase1_test_cases.csv"
DEFAULT_RESULTS = ROOT / "offline_eval" / "results_auto.csv"
DEFAULT_LOG = ROOT / "offline_eval" / "batch_runtime.log"

READY_MARKERS = (
    "Mock Input webSocket server started",
    "server listening on",
)

ACTION_PATTERNS = {
    "speak": re.compile(r"本地模拟动作 speak: (?P<value>.+)$"),
    "arm_movement": re.compile(r"本地模拟动作 arm_g1: (?P<value>.+)$"),
    "led_color": re.compile(r"本地模拟动作 led_g1: (?P<value>.+)$"),
}

TIMESTAMP_RE = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})")


@dataclass
class ActionEvent:
    action_type: str
    value: str
    at: float


class RuntimeMonitor:
    def __init__(self, process: subprocess.Popen[str], log_path: Path):
        self.process = process
        self.log_path = log_path
        self.lines: "queue.Queue[tuple[float, str]]" = queue.Queue()
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def _reader(self) -> None:
        assert self.process.stdout is not None
        with self.log_path.open("w", encoding="utf-8") as log_file:
            for raw_line in self.process.stdout:
                line = raw_line.rstrip("\n")
                log_file.write(raw_line)
                log_file.flush()
                self.lines.put((self._parse_timestamp(line) or time.time(), line))

    @staticmethod
    def _parse_timestamp(line: str) -> Optional[float]:
        match = TIMESTAMP_RE.match(line)
        if not match:
            return None
        dt = datetime.strptime(match.group("ts"), "%Y-%m-%d %H:%M:%S.%f")
        return dt.timestamp()

    def wait_until_ready(self, timeout_s: float) -> None:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError("Runtime exited before becoming ready")
            try:
                _, line = self.lines.get(timeout=0.5)
            except queue.Empty:
                continue
            if any(marker in line for marker in READY_MARKERS):
                return
        raise TimeoutError("Timed out waiting for runtime readiness")

    def collect_actions(self, started_at: float, timeout_s: float) -> tuple[list[ActionEvent], list[str]]:
        deadline = time.time() + timeout_s
        events: list[ActionEvent] = []
        captured_lines: list[str] = []
        first_event_wall: Optional[float] = None

        while time.time() < deadline:
            if self.process.poll() is not None:
                break
            try:
                line_ts, line = self.lines.get(timeout=0.5)
            except queue.Empty:
                if first_event_wall is not None and time.time() - first_event_wall > 1.0:
                    break
                continue

            if line_ts < started_at:
                continue

            captured_lines.append(line)

            for action_type, pattern in ACTION_PATTERNS.items():
                match = pattern.search(line)
                if not match:
                    continue
                events.append(
                    ActionEvent(
                        action_type=action_type,
                        value=match.group("value").strip(),
                        at=line_ts,
                    )
                )
                if first_event_wall is None:
                    first_event_wall = time.time()
                break

        return events, captured_lines


async def send_prompt(host: str, port: int, message: str) -> None:
    uri = f"ws://{host}:{port}"
    async with websockets.connect(uri) as websocket:
        await websocket.send(message)
        await websocket.recv()


def load_cases(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def format_actions(events: list[ActionEvent]) -> str:
    return " | ".join(f"{event.action_type}: {event.value}" for event in events)


def required_actions_present(expected_min_actions: str, events: list[ActionEvent]) -> str:
    required = [item.strip() for item in expected_min_actions.split("|") if item.strip()]
    actual = {event.action_type for event in events}
    return "yes" if all(action in actual for action in required) else "no"


def write_results(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = [
        "run_id",
        "model_name",
        "phase",
        "case_id",
        "input_text",
        "request_success",
        "intent_correct",
        "schema_valid",
        "semantic_correct",
        "invalid_action",
        "interrupt_test",
        "interrupt_recovered",
        "first_response_latency_ms",
        "full_turn_latency_ms",
        "cpu_percent",
        "gpu_percent",
        "ram_mb",
        "vram_mb",
        "temperature_c",
        "raw_output",
        "notes",
        "final_case_result",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_runtime_env(args: argparse.Namespace) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": "src",
            "LOCAL_EVAL_MOCK_PORT": str(args.port),
            "OLLAMA_BASE_URL": args.ollama_base_url,
            "OLLAMA_MODEL": args.model,
            "OLLAMA_TEMPERATURE": str(args.temperature),
            "OLLAMA_NUM_CTX": str(args.num_ctx),
            "OLLAMA_TIMEOUT": str(args.timeout),
        }
    )
    return env


def start_runtime(args: argparse.Namespace) -> RuntimeMonitor:
    python_bin = Path(args.python_bin)
    cmd = [str(python_bin), "src/run.py", args.config]
    process = subprocess.Popen(
        cmd,
        cwd=OM1_DIR,
        env=build_runtime_env(args),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    return RuntimeMonitor(process, Path(args.runtime_log))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch-run Phase 1 offline eval cases")
    parser.add_argument("--config", default="unitree_g1_text_arm_led_ollama_local_eval")
    parser.add_argument("--cases", default=str(DEFAULT_CASES))
    parser.add_argument("--results", default=str(DEFAULT_RESULTS))
    parser.add_argument("--runtime-log", default=str(DEFAULT_LOG))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8879)
    parser.add_argument("--model", default=os.environ.get("OLLAMA_MODEL", "gemma4"))
    parser.add_argument(
        "--python-bin",
        default=str(OM1_DIR / ".venv_x86" / "bin" / "python"),
    )
    parser.add_argument("--ollama-base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--num-ctx", type=int, default=4096)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--startup-timeout", type=float, default=30.0)
    parser.add_argument("--case-timeout", type=float, default=180.0)
    parser.add_argument("--pause-between-cases", type=float, default=1.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cases = load_cases(Path(args.cases))
    run_id = f"auto_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{args.model.replace(':', '_')}"
    runtime = start_runtime(args)

    try:
        runtime.wait_until_ready(args.startup_timeout)
        results: list[dict[str, str]] = []

        for case in cases:
            input_text = case["input_text"]
            send_started_at = time.time()
            asyncio.run(send_prompt(args.host, args.port, input_text))
            events, captured_lines = runtime.collect_actions(
                started_at=send_started_at,
                timeout_s=args.case_timeout,
            )

            first_latency_ms = ""
            full_latency_ms = ""
            if events:
                first_latency_ms = str(round((events[0].at - send_started_at) * 1000))
                full_latency_ms = str(round((events[-1].at - send_started_at) * 1000))

            raw_output = format_actions(events)
            request_success = "yes" if events else "no"
            schema_valid = "yes" if events else "no"
            invalid_action = "no" if events else "yes"
            intent_correct = required_actions_present(
                case["expected_min_actions"], events
            )

            results.append(
                {
                    "run_id": run_id,
                    "model_name": args.model,
                    "phase": case["phase"],
                    "case_id": case["case_id"],
                    "input_text": input_text,
                    "request_success": request_success,
                    "intent_correct": intent_correct,
                    "schema_valid": schema_valid,
                    "semantic_correct": "",
                    "invalid_action": invalid_action,
                    "interrupt_test": "no",
                    "interrupt_recovered": "",
                    "first_response_latency_ms": first_latency_ms,
                    "full_turn_latency_ms": full_latency_ms,
                    "cpu_percent": "",
                    "gpu_percent": "",
                    "ram_mb": "",
                    "vram_mb": "",
                    "temperature_c": "",
                    "raw_output": raw_output,
                    "notes": " || ".join(captured_lines[-5:]),
                    "final_case_result": "",
                }
            )

            time.sleep(args.pause_between_cases)

        write_results(Path(args.results), results)
        print(f"[offline-eval] wrote {len(results)} rows to {args.results}")
        print(f"[offline-eval] runtime log: {args.runtime_log}")
        return 0
    finally:
        if runtime.process.poll() is None:
            runtime.process.terminate()
            try:
                runtime.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                runtime.process.kill()


if __name__ == "__main__":
    sys.exit(main())
