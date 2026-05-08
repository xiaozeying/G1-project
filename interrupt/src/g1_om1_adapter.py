from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


DEFAULT_OM1_ROOT_CANDIDATES = (
    Path("/home/unitree/HongTu/OM1"),
    Path("/home/zz/HongTu/OM1"),
    Path("/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/OM1"),
)

DEFAULT_OM1_PYTHON_CANDIDATES = (
    ".venv-g1/bin/python",
    ".venv/bin/python",
)

DEFAULT_OM1_LD_LIBRARY_PREPEND = (
    "/usr/local/lib",
)


def _default_om1_root() -> Path:
    for candidate in DEFAULT_OM1_ROOT_CANDIDATES:
        if candidate.exists():
            return candidate
    return DEFAULT_OM1_ROOT_CANDIDATES[-1]


def _default_om1_python(om1_root: Path) -> str:
    for relative_path in DEFAULT_OM1_PYTHON_CANDIDATES:
        candidate = om1_root / relative_path
        if candidate.exists():
            return str(candidate)
    return str(om1_root / DEFAULT_OM1_PYTHON_CANDIDATES[-1])


def _default_unitree_interface() -> str:
    candidates = (
        "enP8p1s0",
        "eth1",
        "eth0",
        "wlan0",
    )
    for candidate in candidates:
        path = Path("/sys/class/net") / candidate / "operstate"
        try:
            if path.read_text(encoding="utf-8").strip().lower() == "up":
                return candidate
        except OSError:
            continue
    return "eth1"


def _prepend_library_paths(existing: str | None) -> str:
    entries: list[str] = []
    seen: set[str] = set()
    for item in DEFAULT_OM1_LD_LIBRARY_PREPEND:
        cleaned = item.strip()
        if cleaned and cleaned not in seen:
            entries.append(cleaned)
            seen.add(cleaned)
    for item in (existing or "").split(":"):
        cleaned = item.strip()
        if cleaned and cleaned not in seen:
            entries.append(cleaned)
            seen.add(cleaned)
    return ":".join(entries)


@dataclass
class G1Om1CommandResult:
    ok: bool
    returncode: int
    stdout: str
    stderr: str
    command: tuple[str, ...]


@dataclass
class G1Om1AdapterConfig:
    python_executable: str
    direct_command_script: str
    feedback_script: str
    navigation_script: str
    navigation_base_url: str
    navigation_timeout_s: float
    unitree_interface: str
    ld_library_path: str

    @classmethod
    def from_env(cls) -> "G1Om1AdapterConfig":
        om1_root = _default_om1_root()
        python_executable = os.getenv(
            "INTERRUPT_G1_OM1_PYTHON",
            _default_om1_python(om1_root),
        ).strip()
        direct_command_script = os.getenv(
            "INTERRUPT_G1_DIRECT_COMMAND_SCRIPT",
            str(om1_root / "scripts" / "g1_direct_command_fallback.py"),
        ).strip()
        feedback_script = os.getenv(
            "INTERRUPT_G1_FEEDBACK_SCRIPT",
            str(om1_root / "scripts" / "g1_watchdog_feedback.py"),
        ).strip()
        navigation_script = os.getenv(
            "INTERRUPT_G1_NAVIGATION_SCRIPT",
            str(om1_root / "scripts" / "g1_nav_command.py"),
        ).strip()
        navigation_base_url = (
            os.getenv("INTERRUPT_G1_NAV_BASE_URL", "http://localhost:5000").strip()
            or "http://localhost:5000"
        )
        navigation_timeout_raw = os.getenv("INTERRUPT_G1_NAV_TIMEOUT_S", "5").strip() or "5"
        try:
            navigation_timeout_s = float(navigation_timeout_raw)
        except ValueError:
            navigation_timeout_s = 5.0
        unitree_interface = (
            os.getenv("INTERRUPT_G1_INTERFACE", _default_unitree_interface()).strip()
            or _default_unitree_interface()
        )
        ld_library_path = _prepend_library_paths(os.getenv("LD_LIBRARY_PATH"))
        return cls(
            python_executable=python_executable,
            direct_command_script=direct_command_script,
            feedback_script=feedback_script,
            navigation_script=navigation_script,
            navigation_base_url=navigation_base_url,
            navigation_timeout_s=navigation_timeout_s,
            unitree_interface=unitree_interface,
            ld_library_path=ld_library_path,
        )


class G1Om1Adapter:
    def __init__(self, config: G1Om1AdapterConfig | None = None) -> None:
        self.config = config or G1Om1AdapterConfig.from_env()

    @property
    def available(self) -> bool:
        checks = self.validate_paths()
        return all(
            checks[key]
            for key in ("python_executable", "direct_command_script", "feedback_script")
        )

    @property
    def navigation_available(self) -> bool:
        checks = self.validate_paths()
        return all(checks[key] for key in ("python_executable", "navigation_script"))

    def execute_direct_text(self, text: str, *, check: bool = False) -> G1Om1CommandResult:
        if self._looks_like_led_command(text):
            self.stop_breathe_led()
        return self._run(
            [
                self.config.python_executable,
                self.config.direct_command_script,
                text,
                "--interface",
                self.config.unitree_interface,
            ],
            check=check,
        )

    def speak(
        self,
        text: str,
        *,
        speaker_id: int = 0,
        volume: int = 100,
        check: bool = False,
    ) -> G1Om1CommandResult:
        return self._run(
            [
                self.config.python_executable,
                self.config.feedback_script,
                "--interface",
                self.config.unitree_interface,
                "--mode",
                "speak",
                "--speaker-id",
                str(speaker_id),
                "--volume",
                str(volume),
                "--text",
                text,
            ],
            check=check,
        )

    def set_led(self, color: str, *, check: bool = False) -> G1Om1CommandResult:
        self.stop_breathe_led()
        return self._run(
            [
                self.config.python_executable,
                self.config.feedback_script,
                "--interface",
                self.config.unitree_interface,
                "--mode",
                "static",
                "--color",
                color,
            ],
            check=check,
        )

    def stop_breathe_led(self) -> G1Om1CommandResult:
        script_name = os.path.basename(self.config.feedback_script)
        pattern = f"{script_name} --interface {self.config.unitree_interface} --mode breathe"
        result = self._run(
            ["pkill", "-f", pattern],
            check=False,
        )
        if result.returncode == 1:
            return G1Om1CommandResult(
                ok=True,
                returncode=0,
                stdout="no active breathe process",
                stderr="",
                command=result.command,
            )
        return result

    def breathe_led(
        self,
        color: str,
        *,
        period: float = 2.0,
        check: bool = False,
    ) -> G1Om1CommandResult:
        self.stop_breathe_led()
        command = [
            self.config.python_executable,
            self.config.feedback_script,
            "--interface",
            self.config.unitree_interface,
            "--mode",
            "breathe",
            "--color",
            color,
            "--period",
            str(period),
        ]
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                env=self._subprocess_env(),
            )
            return G1Om1CommandResult(
                ok=process.poll() is None,
                returncode=0 if process.poll() is None else int(process.poll() or 1),
                stdout=f"started breathe pid={process.pid} color={color} period={period}",
                stderr="",
                command=tuple(command),
            )
        except OSError as exc:
            result = G1Om1CommandResult(
                ok=False,
                returncode=-1,
                stdout="",
                stderr=str(exc),
                command=tuple(command),
            )
            if check:
                raise RuntimeError(
                    "G1/OM1 breathe command failed: "
                    f"rc={result.returncode} stdout={result.stdout!r} stderr={result.stderr!r}"
                )
            return result

    def script_paths(self) -> dict[str, str]:
        return {
            "python_executable": self.config.python_executable,
            "direct_command_script": self.config.direct_command_script,
            "feedback_script": self.config.feedback_script,
            "navigation_script": self.config.navigation_script,
            "navigation_base_url": self.config.navigation_base_url,
            "navigation_timeout_s": str(self.config.navigation_timeout_s),
            "unitree_interface": self.config.unitree_interface,
            "ld_library_path": self.config.ld_library_path,
        }

    def validate_paths(self) -> dict[str, bool]:
        return {
            "python_executable": Path(self.config.python_executable).exists(),
            "direct_command_script": Path(self.config.direct_command_script).exists(),
            "feedback_script": Path(self.config.feedback_script).exists(),
            "navigation_script": Path(self.config.navigation_script).exists(),
        }

    def list_saved_locations(self, *, compact: bool = False, check: bool = False) -> G1Om1CommandResult:
        command = [
            self.config.python_executable,
            self.config.navigation_script,
            "--base-url",
            self.config.navigation_base_url,
            "--timeout",
            str(self.config.navigation_timeout_s),
            "list",
        ]
        if compact:
            command.append("--compact")
        return self._run(command, check=check)

    def navigate_to_location(self, label: str, *, check: bool = False) -> G1Om1CommandResult:
        return self._run(
            [
                self.config.python_executable,
                self.config.navigation_script,
                "--base-url",
                self.config.navigation_base_url,
                "--timeout",
                str(self.config.navigation_timeout_s),
                "navigate",
                label,
            ],
            check=check,
        )

    def remember_location(
        self,
        label: str,
        *,
        description: str = "",
        map_name: str = "map",
        check: bool = False,
    ) -> G1Om1CommandResult:
        command = [
            self.config.python_executable,
            self.config.navigation_script,
            "--base-url",
            self.config.navigation_base_url,
            "--timeout",
            str(self.config.navigation_timeout_s),
            "remember",
            label,
            "--map-name",
            map_name,
        ]
        if description:
            command.extend(["--description", description])
        return self._run(command, check=check)

    def _looks_like_led_command(self, text: str) -> bool:
        normalized = (text or "").strip().lower()
        if not normalized:
            return False
        keywords = (
            "led",
            "灯",
            "燈",
            "颜色",
            "顏色",
            "蓝",
            "藍",
            "红",
            "紅",
            "绿",
            "綠",
            "紫",
            "黄",
            "黃",
            "白",
            "橙",
            "青",
            "关灯",
            "熄灯",
        )
        return any(keyword in normalized for keyword in keywords)

    def _run(
        self,
        command: Sequence[str],
        *,
        check: bool,
    ) -> G1Om1CommandResult:
        try:
            completed = subprocess.run(
                list(command),
                check=False,
                text=True,
                capture_output=True,
                env=self._subprocess_env(),
            )
            result = G1Om1CommandResult(
                ok=completed.returncode == 0,
                returncode=completed.returncode,
                stdout=(completed.stdout or "").strip(),
                stderr=(completed.stderr or "").strip(),
                command=tuple(command),
            )
        except OSError as exc:
            result = G1Om1CommandResult(
                ok=False,
                returncode=-1,
                stdout="",
                stderr=str(exc),
                command=tuple(command),
            )
        if check and not result.ok:
            raise RuntimeError(
                "G1/OM1 command failed: "
                f"rc={result.returncode} stdout={result.stdout!r} stderr={result.stderr!r}"
            )
        return result

    def _subprocess_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["LD_LIBRARY_PATH"] = self.config.ld_library_path
        return env
