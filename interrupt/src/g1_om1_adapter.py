from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
from urllib.parse import urlparse


DEFAULT_OM1_ROOT_CANDIDATES = (
    Path("/home/unitree/HongTu/OM1"),
    Path("/home/zz/HongTu/OM1"),
    Path("/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/OM1"),
)

DEFAULT_G1_3D_NAV_ROOT_CANDIDATES = (
    Path("/home/unitree/g1_3d_nav_ros2_repo"),
    Path("/home/zz/HongTu/g1_3d_nav_ros2_repo"),
    Path("/home/unitree/g1_3d_nav-main"),
    Path("/home/zz/HongTu/g1_3d_nav-main"),
    Path("/home/unitree/g1_3d_nav"),
    Path("/home/zz/HongTu/g1_3d_nav"),
    Path("/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/g1_3d_nav_ros2_repo"),
    Path("/home/unitree/g1_3d_nav/HongTu/G1Nav2D"),
    Path("/home/zz/HongTu/g1_3d_nav/HongTu/G1Nav2D"),
    Path("/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/G1Nav2D"),
)

DEFAULT_OM1_PYTHON_CANDIDATES = (
    ".venv-g1-runtime/bin/python",
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


def _default_g1_3d_nav_root() -> Path:
    configured = os.getenv("INTERRUPT_G1_3D_NAV_ROOT", "").strip()
    if configured:
        return Path(configured)
    for candidate in DEFAULT_G1_3D_NAV_ROOT_CANDIDATES:
        if candidate.exists():
            return candidate
    return DEFAULT_G1_3D_NAV_ROOT_CANDIDATES[-1]


def _default_om1_python(om1_root: Path) -> str:
    for relative_path in DEFAULT_OM1_PYTHON_CANDIDATES:
        candidate = om1_root / relative_path
        if candidate.exists() and _python_can_run(candidate):
            return str(candidate)
    if _python_can_run(Path(sys.executable)):
        return sys.executable
    return str(om1_root / DEFAULT_OM1_PYTHON_CANDIDATES[-1])


def _python_can_run(path: Path) -> bool:
    try:
        completed = subprocess.run(
            [str(path), "-c", "import sys; print(sys.executable)"],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except OSError:
        return False
    except Exception:
        return False
    return completed.returncode == 0


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


def _normalize_navigation_provider(raw: str) -> str:
    normalized = (raw or "").strip().lower()
    if normalized in {"", "http", "http_bridge", "bridge"}:
        return "http_bridge"
    if normalized in {"ros2", "ros2_goal_pose", "goal_pose"}:
        return "ros2_goal_pose"
    if normalized in {"g1_3d_nav", "g1_3d_nav_bridge", "hongtu_g1_3d_nav"}:
        return "g1_3d_nav"
    return normalized


def _default_navigation_script(om1_root: Path, provider: str) -> Path:
    if provider == "ros2_goal_pose":
        return om1_root / "scripts" / "g1_nav_goal_pose.py"
    return om1_root / "scripts" / "g1_nav_command.py"


def _default_navigation_bridge_runner(provider: str, nav_root: Path) -> str:
    if provider == "g1_3d_nav":
        return str(Path(__file__).resolve().parents[1] / "run_g1_3d_nav_bridge.sh")
    if provider != "http_bridge":
        return ""
    return str(nav_root / "run_nav_bridge.sh")


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
    speak_script: str
    navigation_provider: str
    navigation_script: str
    navigation_stack_root: str
    navigation_bridge_runner: str
    navigation_base_url: str
    navigation_timeout_s: float
    unitree_interface: str
    ld_library_path: str

    @classmethod
    def from_env(cls) -> "G1Om1AdapterConfig":
        om1_root = _default_om1_root()
        g1_3d_nav_root = _default_g1_3d_nav_root()
        configured_python = os.getenv("INTERRUPT_G1_OM1_PYTHON", "").strip()
        if configured_python and _python_can_run(Path(configured_python)):
            python_executable = configured_python
        else:
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
        speak_script = os.getenv(
            "INTERRUPT_G1_SPEAK_SCRIPT",
            "",
        ).strip()
        navigation_provider = _normalize_navigation_provider(
            os.getenv("INTERRUPT_G1_NAV_PROVIDER", "http_bridge")
        )
        default_navigation_script = _default_navigation_script(
            om1_root,
            navigation_provider,
        )
        navigation_script = os.getenv(
            "INTERRUPT_G1_NAVIGATION_SCRIPT",
            str(default_navigation_script),
        ).strip()
        navigation_stack_root = os.getenv(
            "INTERRUPT_G1_NAV_STACK_ROOT",
            str(g1_3d_nav_root),
        ).strip()
        navigation_bridge_runner = os.getenv(
            "INTERRUPT_G1_NAV_BRIDGE_RUNNER",
            _default_navigation_bridge_runner(
                navigation_provider,
                Path(navigation_stack_root),
            ),
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
            speak_script=speak_script,
            navigation_provider=navigation_provider,
            navigation_script=navigation_script,
            navigation_stack_root=navigation_stack_root,
            navigation_bridge_runner=navigation_bridge_runner,
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

    @property
    def navigation_bridge_available(self) -> bool:
        runner = self.config.navigation_bridge_runner.strip()
        return bool(runner) and Path(runner).exists()

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
        speak_script = self.config.speak_script.strip()
        if speak_script:
            return self._run(
                [
                    "bash",
                    speak_script,
                    text,
                ],
                check=check,
            )
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
            "speak_script": self.config.speak_script,
            "navigation_provider": self.config.navigation_provider,
            "navigation_script": self.config.navigation_script,
            "navigation_stack_root": self.config.navigation_stack_root,
            "navigation_bridge_runner": self.config.navigation_bridge_runner,
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
            "speak_script": (not self.config.speak_script) or Path(self.config.speak_script).exists(),
            "navigation_script": Path(self.config.navigation_script).exists(),
            "navigation_stack_root": Path(self.config.navigation_stack_root).exists(),
            "navigation_bridge_runner": (
                (not self.config.navigation_bridge_runner)
                or Path(self.config.navigation_bridge_runner).exists()
            ),
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

    def start_navigation_bridge(self, *, check: bool = False) -> G1Om1CommandResult:
        runner = self.config.navigation_bridge_runner.strip()
        if not runner:
            result = G1Om1CommandResult(
                ok=False,
                returncode=-1,
                stdout="",
                stderr=f"navigation provider {self.config.navigation_provider} does not define a bridge runner",
                command=tuple(),
            )
            if check:
                raise RuntimeError(result.stderr)
            return result
        parsed = urlparse(self.config.navigation_base_url)
        host = parsed.hostname or "127.0.0.1"
        port = str(parsed.port or (443 if parsed.scheme == "https" else 80))
        env = self._subprocess_env()
        env.setdefault("G1_NAV_BRIDGE_HOST", host)
        env.setdefault("G1_NAV_BRIDGE_PORT", port)
        env.setdefault("INTERRUPT_G1_3D_NAV_ROOT", self.config.navigation_stack_root)
        command = ["bash", runner]
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                env=env,
            )
            result = G1Om1CommandResult(
                ok=process.poll() is None,
                returncode=0 if process.poll() is None else int(process.poll() or 1),
                stdout=f"started navigation bridge pid={process.pid} provider={self.config.navigation_provider}",
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
        if check and not result.ok:
            raise RuntimeError(
                "G1 navigation bridge start failed: "
                f"rc={result.returncode} stdout={result.stdout!r} stderr={result.stderr!r}"
            )
        return result

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
        env: dict[str, str] | None = None,
    ) -> G1Om1CommandResult:
        try:
            completed = subprocess.run(
                list(command),
                check=False,
                text=True,
                capture_output=True,
                env=env or self._subprocess_env(),
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
