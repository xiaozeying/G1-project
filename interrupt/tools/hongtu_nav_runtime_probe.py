#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any


ROS_MAP_EDIT_DIR = Path("/home/unitree/g1_3d_nav/HongTu/G1Nav2D/src/ros_map_edit/maps")
TINYNAV_DIR = Path("/home/unitree/tinynav")


def _iso_mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")


def _list_ros_maps() -> list[dict[str, Any]]:
    if not ROS_MAP_EDIT_DIR.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(ROS_MAP_EDIT_DIR.glob("*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True):
        stem = path.stem
        rows.append(
            {
                "name": stem,
                "yaml": str(path),
                "pgm_exists": (ROS_MAP_EDIT_DIR / f"{stem}.pgm").exists(),
                "json_exists": (ROS_MAP_EDIT_DIR / f"{stem}.json").exists(),
                "region_exists": (ROS_MAP_EDIT_DIR / f"{stem}_region.json").exists(),
                "point_exists": (ROS_MAP_EDIT_DIR / f"{stem}_point.json").exists(),
                "mtime": _iso_mtime(path),
            }
        )
    return rows


def _list_tinynav_workspaces() -> list[dict[str, Any]]:
    if not TINYNAV_DIR.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(TINYNAV_DIR.glob("*/metadata.yaml"), key=lambda item: item.stat().st_mtime, reverse=True):
        rows.append(
            {
                "name": path.parent.name,
                "metadata": str(path),
                "mtime": _iso_mtime(path),
            }
        )
    return rows


def _find_point_files() -> list[dict[str, Any]]:
    roots = [ROS_MAP_EDIT_DIR, TINYNAV_DIR, Path("/home/unitree/HongTu/interrupt/config")]
    rows: list[dict[str, Any]] = []
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*_point.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            rows.append({"path": str(path), "mtime": _iso_mtime(path)})
    return rows


def _ros2_goal_pose_probe() -> dict[str, Any]:
    ros2 = shutil.which("ros2")
    if not ros2:
        return {"available": False, "detail": "ros2 CLI not found"}
    try:
        info = subprocess.run(
            [ros2, "topic", "info", "-v", "/goal_pose"],
            check=False,
            text=True,
            capture_output=True,
            timeout=5.0,
        )
    except Exception as exc:
        return {"available": False, "detail": str(exc)}
    return {
        "available": info.returncode == 0,
        "stdout": (info.stdout or "").strip(),
        "stderr": (info.stderr or "").strip(),
    }


def main() -> int:
    ros_maps = _list_ros_maps()
    workspaces = _list_tinynav_workspaces()
    point_files = _find_point_files()
    payload = {
        "ros_map_edit_dir": str(ROS_MAP_EDIT_DIR),
        "tinynav_dir": str(TINYNAV_DIR),
        "latest_ros_map": ros_maps[0] if ros_maps else None,
        "latest_tinynav_workspace": workspaces[0] if workspaces else None,
        "ros_maps": ros_maps[:10],
        "tinynav_workspaces": workspaces[:10],
        "point_files": point_files[:20],
        "goal_pose_probe": _ros2_goal_pose_probe(),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
