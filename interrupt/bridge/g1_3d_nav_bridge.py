#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import os
import shlex
import shutil
import subprocess
import threading
import textwrap
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import yaml

try:
    import actionlib
    import rospy
    from geometry_msgs.msg import PoseWithCovarianceStamped
    from move_base_msgs.msg import MoveBaseAction, MoveBaseGoal
except ImportError as exc:  # pragma: no cover
    actionlib = None
    rospy = None
    PoseWithCovarianceStamped = None
    MoveBaseAction = None
    MoveBaseGoal = None
    ROS1_IMPORT_ERROR = exc
else:  # pragma: no cover
    ROS1_IMPORT_ERROR = None

try:
    import rclpy
    from geometry_msgs.msg import PoseStamped
    from nav2_msgs.action import NavigateToPose
    from rclpy.action import ActionClient
    from rclpy.node import Node
except ImportError as exc:  # pragma: no cover
    rclpy = None
    PoseStamped = None
    NavigateToPose = None
    ActionClient = None
    Node = None
    ROS2_IMPORT_ERROR = exc
else:  # pragma: no cover
    ROS2_IMPORT_ERROR = None


ROOT_DIR = Path(__file__).resolve().parents[2]


def _candidate_nav_roots() -> tuple[Path, ...]:
    return (
        Path("/home/unitree/g1_3d_nav_ros2_repo"),
        Path("/home/zz/HongTu/g1_3d_nav_ros2_repo"),
        Path("/home/unitree/g1_3d_nav-main"),
        Path("/home/zz/HongTu/g1_3d_nav-main"),
        Path("/home/unitree/g1_3d_nav"),
        Path("/home/zz/HongTu/g1_3d_nav"),
        ROOT_DIR.parent / "g1_3d_nav_ros2_repo",
        ROOT_DIR.parent / "g1_3d_nav-main",
        ROOT_DIR.parent / "g1_3d_nav",
    )


def _default_nav_root() -> Path:
    for candidate in _candidate_nav_roots():
        if candidate.exists():
            return candidate
    return _candidate_nav_roots()[-1]


def _default_map_file(nav_root: Path) -> Path:
    candidates = (
        nav_root / "maps" / "accumulated_grid.yaml",
        nav_root / "maps" / "map.yaml",
        nav_root / "src/ros1_ws_src/tools/ros_map_edit/maps/map.yaml",
        nav_root / "src/ros1_ws_src/tools/ros_map_edit/maps/25030901.yaml",
        nav_root / "deepglint_ws/src/tools/ros_map_edit/maps/map.yaml",
        nav_root / "deepglint_ws/src/tools/ros_map_edit/maps/25030901.yaml",
        nav_root / "ros_map_edit/maps/map.yaml",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    for maps_dir in (
        nav_root / "src/ros1_ws_src/tools/ros_map_edit/maps",
        nav_root / "deepglint_ws/src/tools/ros_map_edit/maps",
    ):
        if maps_dir.exists():
            yamls = sorted(maps_dir.glob("*.yaml"))
            if yamls:
                return yamls[0]
    return candidates[0]


def _default_waypoints_file(nav_root: Path) -> Path:
    candidates = (
        nav_root / "data" / "waypoints.yaml",
        nav_root / "data" / "waypoints.yml",
        nav_root / "maps" / "waypoints.yaml",
        nav_root / "maps" / "waypoints.yml",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _point_file_for_map(map_file: Path) -> Path:
    return map_file.with_name(f"{map_file.stem}_point.json")


def _quaternion_from_theta(theta: float) -> dict[str, float]:
    import math

    return {
        "x": 0.0,
        "y": 0.0,
        "z": math.sin(theta / 2.0),
        "w": math.cos(theta / 2.0),
    }


def _theta_from_orientation(orientation: dict[str, Any]) -> float:
    import math

    return 2.0 * math.atan2(
        float(orientation.get("z", 0.0) or 0.0),
        float(orientation.get("w", 1.0) or 1.0),
    )


def _default_docker_container() -> str:
    return (
        os.getenv("INTERRUPT_G1_NAV_DOCKER_CONTAINER", "").strip()
        or os.getenv("G1_NAV_BRIDGE_DOCKER_CONTAINER", "").strip()
    )


def _entry_from_pose(name: str, pose: dict[str, Any], *, source_point: dict[str, Any] | None = None) -> dict[str, Any]:
    position = pose.get("position") or {}
    orientation = pose.get("orientation") or {}
    return {
        "name": name,
        "id": name,
        "pose": {
            "position": {
                "x": float(position.get("x", 0.0) or 0.0),
                "y": float(position.get("y", 0.0) or 0.0),
                "z": float(position.get("z", 0.0) or 0.0),
            },
            "orientation": {
                "x": float(orientation.get("x", 0.0) or 0.0),
                "y": float(orientation.get("y", 0.0) or 0.0),
                "z": float(orientation.get("z", 0.0) or 0.0),
                "w": float(orientation.get("w", 1.0) or 1.0),
            },
        },
        "source_point": source_point or pose,
    }


def _entry_from_flat_waypoint(name: str, value: dict[str, Any]) -> dict[str, Any]:
    yaw = float(value.get("yaw", value.get("theta", 0.0)) or 0.0)
    orientation = {
        "x": float(value.get("qx", 0.0) or 0.0),
        "y": float(value.get("qy", 0.0) or 0.0),
        "z": float(value.get("qz", 0.0) or 0.0),
        "w": float(value.get("qw", 0.0) or 0.0),
    }
    if not any(abs(component) > 1e-9 for component in orientation.values()):
        orientation = _quaternion_from_theta(yaw)
    return _entry_from_pose(
        name,
        {
            "position": {
                "x": float(value.get("x", 0.0) or 0.0),
                "y": float(value.get("y", 0.0) or 0.0),
                "z": float(value.get("z", 0.0) or 0.0),
            },
            "orientation": orientation,
        },
        source_point=value,
    )


def _parse_waypoint_payload(raw: Any, *, default_frame_id: str = "map") -> tuple[dict[str, dict[str, Any]], str, str]:
    frame_id = default_frame_id
    storage_format = "pose_dict"
    source = raw
    if isinstance(raw, dict):
        frame_id = str(raw.get("frame_id") or default_frame_id).strip() or default_frame_id
        if isinstance(raw.get("waypoints"), dict):
            storage_format = "nested_waypoints"
            source = raw.get("waypoints") or {}

    parsed: dict[str, dict[str, Any]] = {}
    if isinstance(source, dict):
        for key, value in source.items():
            if not isinstance(value, dict):
                continue
            name = str(value.get("name") or key).strip()
            if not name:
                continue
            if isinstance(value.get("pose"), dict):
                parsed[name.lower()] = _entry_from_pose(name, value["pose"], source_point=value)
                continue
            if isinstance(value.get("position"), dict) or isinstance(value.get("orientation"), dict):
                parsed[name.lower()] = _entry_from_pose(
                    name,
                    {
                        "position": value.get("position") or {},
                        "orientation": value.get("orientation") or {},
                    },
                    source_point=value,
                )
                continue
            if any(token in value for token in ("x", "y", "qx", "qy", "qz", "qw", "yaw", "theta")):
                parsed[name.lower()] = _entry_from_flat_waypoint(name, value)
    elif isinstance(source, list):
        for item in source:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("label") or "").strip()
            if not name:
                continue
            if isinstance(item.get("pose"), dict):
                parsed[name.lower()] = _entry_from_pose(name, item["pose"], source_point=item)
                continue
            if isinstance(item.get("position"), dict) or isinstance(item.get("orientation"), dict):
                parsed[name.lower()] = _entry_from_pose(
                    name,
                    {
                        "position": item.get("position") or {},
                        "orientation": item.get("orientation") or {},
                    },
                    source_point=item,
                )
                continue
            if any(token in item for token in ("x", "y", "qx", "qy", "qz", "qw", "yaw", "theta")):
                parsed[name.lower()] = _entry_from_flat_waypoint(name, item)
    return parsed, frame_id, storage_format


def _serialize_locations(
    locations: dict[str, dict[str, Any]],
    *,
    frame_id: str,
    storage_format: str,
) -> dict[str, Any]:
    if storage_format == "nested_waypoints":
        waypoints: dict[str, dict[str, Any]] = {}
        for entry in locations.values():
            name = str(entry.get("name") or "").strip()
            if not name:
                continue
            pose = entry.get("pose") or {}
            position = pose.get("position") or {}
            orientation = pose.get("orientation") or {}
            source_point = entry.get("source_point") if isinstance(entry.get("source_point"), dict) else {}
            payload = dict(source_point or {})
            payload.update(
                {
                    "x": float(position.get("x", 0.0) or 0.0),
                    "y": float(position.get("y", 0.0) or 0.0),
                    "z": float(position.get("z", 0.0) or 0.0),
                    "qx": float(orientation.get("x", 0.0) or 0.0),
                    "qy": float(orientation.get("y", 0.0) or 0.0),
                    "qz": float(orientation.get("z", 0.0) or 0.0),
                    "qw": float(orientation.get("w", 1.0) or 1.0),
                    "yaw": _theta_from_orientation(orientation),
                }
            )
            waypoints[name] = payload
        return {"frame_id": frame_id, "waypoints": waypoints}

    return {
        entry["name"]: {
            "position": entry["pose"]["position"],
            "orientation": entry["pose"]["orientation"],
        }
        for entry in locations.values()
    }


@dataclass
class BridgeStatus:
    ros_available: bool
    navigation_ready: bool
    current_goal: str | None
    last_error: str
    backend_kind: str


class NavBridgeBackend:
    backend_kind = "unknown"

    def status(self) -> BridgeStatus:
        raise NotImplementedError

    def list_locations(self) -> dict[str, dict[str, Any]]:
        raise NotImplementedError

    def remember_location(self, label: str, *, description: str = "", map_name: str = "map") -> dict[str, Any]:
        raise NotImplementedError

    def navigate_to_label(self, label: str) -> dict[str, Any]:
        raise NotImplementedError

    def cancel_navigation(self) -> dict[str, Any]:
        raise NotImplementedError

    @property
    def locations_file(self) -> Path:
        raise NotImplementedError

    @property
    def map_file(self) -> Path:
        raise NotImplementedError

    @property
    def nav_root(self) -> Path:
        raise NotImplementedError


class Ros1PointBackend(NavBridgeBackend):
    backend_kind = "ros1_move_base"

    def __init__(
        self,
        *,
        nav_root: Path,
        map_file: Path,
        action_server: str,
        frame_id: str,
    ) -> None:
        self._nav_root = nav_root
        self._map_file = map_file
        self.action_server = action_server
        self.frame_id = frame_id
        self._locations_file = _point_file_for_map(map_file)
        self._lock = threading.Lock()
        self._locations: dict[str, dict[str, Any]] = {}
        self._current_pose: dict[str, Any] | None = None
        self._current_goal: str | None = None
        self._last_error = ""
        self._ros_available = False
        self._navigation_ready = False
        self._move_base_client = None
        self._load_locations()
        self._init_ros()

    @property
    def nav_root(self) -> Path:
        return self._nav_root

    @property
    def map_file(self) -> Path:
        return self._map_file

    @property
    def locations_file(self) -> Path:
        return self._locations_file

    def _init_ros(self) -> None:
        if ROS1_IMPORT_ERROR is not None:
            self._last_error = f"ROS1 imports unavailable: {ROS1_IMPORT_ERROR}"
            logging.warning(self._last_error)
            return
        assert rospy is not None
        assert actionlib is not None
        assert PoseWithCovarianceStamped is not None
        assert MoveBaseAction is not None
        try:
            rospy.init_node("g1_3d_nav_bridge", anonymous=True, disable_signals=True)
            rospy.Subscriber("/amcl_pose", PoseWithCovarianceStamped, self._pose_callback)
            self._move_base_client = actionlib.SimpleActionClient(self.action_server, MoveBaseAction)
            self._navigation_ready = bool(self._move_base_client.wait_for_server(rospy.Duration(5.0)))
            self._ros_available = True
            if not self._navigation_ready:
                self._last_error = f"move_base action server not ready: {self.action_server}"
        except Exception as exc:  # pragma: no cover
            self._last_error = f"failed to initialize ROS1 bridge: {exc}"
            logging.exception(self._last_error)

    def _pose_callback(self, msg: Any) -> None:  # pragma: no cover
        pose = msg.pose.pose
        with self._lock:
            self._current_pose = {
                "position": {
                    "x": float(pose.position.x),
                    "y": float(pose.position.y),
                    "z": float(pose.position.z),
                },
                "orientation": {
                    "x": float(pose.orientation.x),
                    "y": float(pose.orientation.y),
                    "z": float(pose.orientation.z),
                    "w": float(pose.orientation.w),
                },
            }

    def _load_locations(self) -> None:
        if not self._locations_file.exists():
            return
        try:
            raw = json.loads(self._locations_file.read_text(encoding="utf-8"))
        except Exception as exc:
            self._last_error = f"failed to load locations file: {exc}"
            logging.exception(self._last_error)
            return
        points = raw.get("points") if isinstance(raw, dict) else None
        if not isinstance(points, list):
            self._last_error = "locations file must contain a 'points' list"
            return
        parsed: dict[str, dict[str, Any]] = {}
        for item in points:
            if not isinstance(item, dict):
                continue
            label = str(item.get("name") or item.get("label") or item.get("id") or "").strip()
            if not label:
                continue
            theta = float(item.get("theta", 0.0) or 0.0)
            parsed[label.lower()] = {
                "name": label,
                "id": str(item.get("id") or label).strip(),
                "pose": {
                    "position": {
                        "x": float(item.get("x", 0.0) or 0.0),
                        "y": float(item.get("y", 0.0) or 0.0),
                        "z": 0.0,
                    },
                    "orientation": _quaternion_from_theta(theta),
                },
                "source_theta": theta,
                "source_point": item,
            }
        with self._lock:
            self._locations = parsed

    def _save_locations(self) -> None:
        with self._lock:
            ordered = list(sorted(self._locations.values(), key=lambda entry: str(entry.get("id") or entry.get("name"))))
        points: list[dict[str, Any]] = []
        for index, entry in enumerate(ordered):
            point = dict(entry.get("source_point") or {})
            pose = entry.get("pose") or {}
            position = pose.get("position") or {}
            point["id"] = str(point.get("id") or entry.get("id") or index)
            point["name"] = str(entry.get("name") or point["id"])
            point["x"] = float(position.get("x", 0.0))
            point["y"] = float(position.get("y", 0.0))
            point["theta"] = float(entry.get("source_theta", 0.0))
            points.append(point)
        self._locations_file.parent.mkdir(parents=True, exist_ok=True)
        self._locations_file.write_text(
            json.dumps({"points": points}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def status(self) -> BridgeStatus:
        with self._lock:
            return BridgeStatus(
                ros_available=self._ros_available,
                navigation_ready=self._navigation_ready,
                current_goal=self._current_goal,
                last_error=self._last_error,
                backend_kind=self.backend_kind,
            )

    def list_locations(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return dict(self._locations)

    def remember_location(self, label: str, *, description: str = "", map_name: str = "map") -> dict[str, Any]:
        normalized = label.strip().lower()
        if not normalized:
            raise ValueError("label is required")
        with self._lock:
            pose = dict(self._current_pose or {})
            existing = dict(self._locations.get(normalized) or {})
            existing_ids = [
                int(str(item.get("id")))
                for item in self._locations.values()
                if str(item.get("id") or "").isdigit()
            ]
        if not pose:
            raise RuntimeError("current robot pose is unavailable; amcl_pose has not been received yet")
        theta = _theta_from_orientation(pose.get("orientation") or {})
        point_id = str(existing.get("id") or (max(existing_ids) + 1 if existing_ids else 0))
        entry = {
            "name": label.strip(),
            "id": point_id,
            "map_name": map_name,
            "description": description.strip(),
            "pose": pose,
            "source_theta": theta,
            "source_point": {
                "id": point_id,
                "name": label.strip(),
                "x": float((pose.get("position") or {}).get("x", 0.0)),
                "y": float((pose.get("position") or {}).get("y", 0.0)),
                "theta": theta,
            },
            "saved_at": int(time.time()),
        }
        with self._lock:
            self._locations[normalized] = entry
        self._save_locations()
        return entry

    def _build_goal(self, entry: dict[str, Any]) -> Any:  # pragma: no cover
        assert MoveBaseGoal is not None
        assert rospy is not None
        pose = entry.get("pose") or {}
        position = pose.get("position") or {}
        orientation = pose.get("orientation") or {}
        goal = MoveBaseGoal()
        goal.target_pose.header.frame_id = self.frame_id
        goal.target_pose.header.stamp = rospy.Time.now()
        goal.target_pose.pose.position.x = float(position.get("x", 0.0))
        goal.target_pose.pose.position.y = float(position.get("y", 0.0))
        goal.target_pose.pose.position.z = float(position.get("z", 0.0))
        goal.target_pose.pose.orientation.x = float(orientation.get("x", 0.0))
        goal.target_pose.pose.orientation.y = float(orientation.get("y", 0.0))
        goal.target_pose.pose.orientation.z = float(orientation.get("z", 0.0))
        goal.target_pose.pose.orientation.w = float(orientation.get("w", 1.0))
        return goal

    def navigate_to_label(self, label: str) -> dict[str, Any]:
        normalized = label.strip().lower()
        if not normalized:
            raise ValueError("label is required")
        with self._lock:
            entry = self._locations.get(normalized)
        if entry is None:
            raise KeyError(label)
        if not self._ros_available or not self._navigation_ready or self._move_base_client is None:
            raise RuntimeError(self._last_error or "move_base is not ready")
        self._move_base_client.send_goal(self._build_goal(entry))
        with self._lock:
            self._current_goal = str(entry.get("name") or label).strip() or label
        return entry

    def cancel_navigation(self) -> dict[str, Any]:
        if not self._ros_available or self._move_base_client is None:
            raise RuntimeError(self._last_error or "move_base is not ready")
        self._move_base_client.cancel_all_goals()
        with self._lock:
            previous_goal = self._current_goal
            self._current_goal = None
        return {"previous_goal": previous_goal}


if Node is not None:  # pragma: no cover
    class _Ros2WaypointNode(Node):
        def __init__(self, action_server: str) -> None:
            super().__init__("g1_3d_nav_bridge")
            assert PoseStamped is not None
            assert NavigateToPose is not None
            assert ActionClient is not None
            self._latest_pose: PoseStamped | None = None
            self._goal_handle = None
            self.create_subscription(PoseStamped, "/localization_3d", self._on_pose, 10)
            self._nav = ActionClient(self, NavigateToPose, action_server)

        def _on_pose(self, msg: PoseStamped) -> None:
            self._latest_pose = msg
else:
    class _Ros2WaypointNode:  # pragma: no cover
        pass


class Ros2WaypointBackend(NavBridgeBackend):
    backend_kind = "ros2_nav2"

    def __init__(
        self,
        *,
        nav_root: Path,
        map_file: Path,
        waypoints_file: Path,
        action_server: str,
        frame_id: str,
    ) -> None:
        self._nav_root = nav_root
        self._map_file = map_file
        self._locations_file = waypoints_file
        self.action_server = action_server
        self.frame_id = frame_id
        self._lock = threading.Lock()
        self._locations: dict[str, dict[str, Any]] = {}
        self._current_goal: str | None = None
        self._last_error = ""
        self._storage_format = "pose_dict"
        self._ros_available = False
        self._navigation_ready = False
        self._spin_thread: threading.Thread | None = None
        self._node: _Ros2WaypointNode | None = None
        self._load_locations()
        self._init_ros()

    @property
    def nav_root(self) -> Path:
        return self._nav_root

    @property
    def map_file(self) -> Path:
        return self._map_file

    @property
    def locations_file(self) -> Path:
        return self._locations_file

    def _init_ros(self) -> None:
        if ROS2_IMPORT_ERROR is not None or rclpy is None or _Ros2WaypointNode is None:
            self._last_error = f"ROS2 imports unavailable: {ROS2_IMPORT_ERROR}"
            logging.warning(self._last_error)
            return
        try:
            rclpy.init(args=None)
            self._node = _Ros2WaypointNode(self.action_server)
            self._navigation_ready = bool(self._node._nav.wait_for_server(timeout_sec=5.0))
            self._ros_available = True
            if not self._navigation_ready:
                self._last_error = f"NavigateToPose action server not ready: {self.action_server}"
            self._spin_thread = threading.Thread(target=rclpy.spin, args=(self._node,), daemon=True)
            self._spin_thread.start()
        except Exception as exc:  # pragma: no cover
            self._last_error = f"failed to initialize ROS2 bridge: {exc}"
            logging.exception(self._last_error)

    def _load_locations(self) -> None:
        if not self._locations_file.exists():
            return
        try:
            raw = yaml.safe_load(self._locations_file.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            self._last_error = f"failed to load waypoints file: {exc}"
            logging.exception(self._last_error)
            return
        parsed, resolved_frame_id, storage_format = _parse_waypoint_payload(raw, default_frame_id=self.frame_id)
        with self._lock:
            self._locations = parsed
            self.frame_id = resolved_frame_id
            self._storage_format = storage_format

    def _save_locations(self) -> None:
        with self._lock:
            serializable = _serialize_locations(
                self._locations,
                frame_id=self.frame_id,
                storage_format=self._storage_format,
            )
        self._locations_file.parent.mkdir(parents=True, exist_ok=True)
        self._locations_file.write_text(
            yaml.safe_dump(serializable, default_flow_style=False, allow_unicode=True, sort_keys=True),
            encoding="utf-8",
        )

    def status(self) -> BridgeStatus:
        with self._lock:
            return BridgeStatus(
                ros_available=self._ros_available,
                navigation_ready=self._navigation_ready,
                current_goal=self._current_goal,
                last_error=self._last_error,
                backend_kind=self.backend_kind,
            )

    def list_locations(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return dict(self._locations)

    def remember_location(self, label: str, *, description: str = "", map_name: str = "map") -> dict[str, Any]:
        del description, map_name
        normalized = label.strip().lower()
        if not normalized:
            raise ValueError("label is required")
        if self._node is None or self._node._latest_pose is None:
            raise RuntimeError("current robot pose is unavailable; localization_3d has not been received yet")
        msg = self._node._latest_pose
        pose = {
            "position": {
                "x": float(msg.pose.position.x),
                "y": float(msg.pose.position.y),
                "z": float(msg.pose.position.z),
            },
            "orientation": {
                "x": float(msg.pose.orientation.x),
                "y": float(msg.pose.orientation.y),
                "z": float(msg.pose.orientation.z),
                "w": float(msg.pose.orientation.w),
            },
        }
        entry = {
            "name": label.strip(),
            "id": label.strip(),
            "pose": pose,
            "source_point": {
                "position": pose["position"],
                "orientation": pose["orientation"],
            },
            "saved_at": int(time.time()),
        }
        with self._lock:
            self._locations[normalized] = entry
        self._save_locations()
        return entry

    def navigate_to_label(self, label: str) -> dict[str, Any]:
        normalized = label.strip().lower()
        if not normalized:
            raise ValueError("label is required")
        with self._lock:
            entry = self._locations.get(normalized)
        if entry is None:
            raise KeyError(label)
        if not self._ros_available or not self._navigation_ready or self._node is None:
            raise RuntimeError(self._last_error or "navigate_to_pose is not ready")
        assert NavigateToPose is not None
        goal = NavigateToPose.Goal()
        goal.pose.header.frame_id = self.frame_id
        goal.pose.header.stamp = self._node.get_clock().now().to_msg()
        goal.pose.pose.position.x = float(entry["pose"]["position"]["x"])
        goal.pose.pose.position.y = float(entry["pose"]["position"]["y"])
        goal.pose.pose.position.z = float(entry["pose"]["position"]["z"])
        goal.pose.pose.orientation.x = float(entry["pose"]["orientation"]["x"])
        goal.pose.pose.orientation.y = float(entry["pose"]["orientation"]["y"])
        goal.pose.pose.orientation.z = float(entry["pose"]["orientation"]["z"])
        goal.pose.pose.orientation.w = float(entry["pose"]["orientation"]["w"])
        future = self._node._nav.send_goal_async(goal)

        def _on_goal_response(done: Any) -> None:
            try:
                self._node._goal_handle = done.result()
            except Exception as exc:  # pragma: no cover
                self._last_error = f"nav2 goal submission failed: {exc}"

        future.add_done_callback(_on_goal_response)
        with self._lock:
            self._current_goal = str(entry.get("name") or label).strip() or label
        return entry

    def cancel_navigation(self) -> dict[str, Any]:
        if self._node is None or self._node._goal_handle is None:
            raise RuntimeError("no active nav2 goal to cancel")
        self._node._goal_handle.cancel_goal_async()
        with self._lock:
            previous_goal = self._current_goal
            self._current_goal = None
        return {"previous_goal": previous_goal}


class G1ThreeDNavBridge:
    def __init__(
        self,
        *,
        nav_root: Path,
        map_file: Path,
        waypoints_file: Path,
        action_server: str,
        frame_id: str,
        docker_container: str = "",
    ) -> None:
        self._backend = self._select_backend(
            nav_root=nav_root,
            map_file=map_file,
            waypoints_file=waypoints_file,
            action_server=action_server,
            frame_id=frame_id,
            docker_container=docker_container,
        )

    @staticmethod
    def _select_backend(
        *,
        nav_root: Path,
        map_file: Path,
        waypoints_file: Path,
        action_server: str,
        frame_id: str,
        docker_container: str,
    ) -> NavBridgeBackend:
        if waypoints_file.exists():
            if docker_container:
                return DockerRos2WaypointBackend(
                    nav_root=nav_root,
                    map_file=map_file,
                    waypoints_file=waypoints_file,
                    action_server=action_server,
                    frame_id=frame_id,
                    docker_container=docker_container,
                )
            return Ros2WaypointBackend(
                nav_root=nav_root,
                map_file=map_file,
                waypoints_file=waypoints_file,
                action_server=action_server,
                frame_id=frame_id,
            )
        return Ros1PointBackend(
            nav_root=nav_root,
            map_file=map_file,
            action_server=action_server,
            frame_id=frame_id,
        )

    @property
    def backend_kind(self) -> str:
        return self._backend.backend_kind

    @property
    def nav_root(self) -> Path:
        return self._backend.nav_root

    @property
    def map_file(self) -> Path:
        return self._backend.map_file

    @property
    def locations_file(self) -> Path:
        return self._backend.locations_file

    def status(self) -> BridgeStatus:
        return self._backend.status()

    def list_locations(self) -> dict[str, dict[str, Any]]:
        return self._backend.list_locations()

    def remember_location(self, label: str, *, description: str = "", map_name: str = "map") -> dict[str, Any]:
        return self._backend.remember_location(label, description=description, map_name=map_name)

    def navigate_to_label(self, label: str) -> dict[str, Any]:
        return self._backend.navigate_to_label(label)

    def cancel_navigation(self) -> dict[str, Any]:
        return self._backend.cancel_navigation()


class DockerRos2WaypointBackend(NavBridgeBackend):
    backend_kind = "docker_ros2_nav2"

    def __init__(
        self,
        *,
        nav_root: Path,
        map_file: Path,
        waypoints_file: Path,
        action_server: str,
        frame_id: str,
        docker_container: str,
    ) -> None:
        self._nav_root = nav_root
        self._map_file = map_file
        self._locations_file = waypoints_file
        self.action_server = action_server
        self.frame_id = frame_id
        self.docker_container = docker_container.strip()
        self._lock = threading.Lock()
        self._locations: dict[str, dict[str, Any]] = {}
        self._current_goal: str | None = None
        self._last_error = ""
        self._storage_format = "pose_dict"
        self._ros_available = False
        self._navigation_ready = False
        self._load_locations()
        self._probe_runtime()

    @property
    def nav_root(self) -> Path:
        return self._nav_root

    @property
    def map_file(self) -> Path:
        return self._map_file

    @property
    def locations_file(self) -> Path:
        return self._locations_file

    def _probe_runtime(self) -> None:
        if not self.docker_container:
            self._last_error = "docker container is not configured"
            return
        if shutil.which("docker") is None:
            self._last_error = "docker executable is unavailable on the host"
            return
        result = subprocess.run(
            [
                "docker",
                "inspect",
                "-f",
                "{{.State.Running}}",
                self.docker_container,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            self._last_error = result.stderr.strip() or f"failed to inspect docker container {self.docker_container}"
            return
        self._ros_available = result.stdout.strip().lower() == "true"
        self._navigation_ready = self._ros_available
        if not self._navigation_ready:
            self._last_error = f"docker container {self.docker_container} is not running"

    def _load_locations(self) -> None:
        if not self._locations_file.exists():
            return
        try:
            raw = yaml.safe_load(self._locations_file.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            self._last_error = f"failed to load waypoints file: {exc}"
            logging.exception(self._last_error)
            return
        parsed, resolved_frame_id, storage_format = _parse_waypoint_payload(raw, default_frame_id=self.frame_id)
        with self._lock:
            self._locations = parsed
            self.frame_id = resolved_frame_id
            self._storage_format = storage_format

    def _save_locations(self) -> None:
        with self._lock:
            serializable = _serialize_locations(
                self._locations,
                frame_id=self.frame_id,
                storage_format=self._storage_format,
            )
        self._locations_file.parent.mkdir(parents=True, exist_ok=True)
        self._locations_file.write_text(
            yaml.safe_dump(serializable, default_flow_style=False, allow_unicode=True, sort_keys=True),
            encoding="utf-8",
        )

    def _docker_exec_python(self, code: str, *, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        env_args: list[str] = []
        for key, value in sorted((extra_env or {}).items()):
            env_args.extend(["-e", f"{key}={value}"])
        command = [
            "docker",
            "exec",
            *env_args,
            self.docker_container,
            "bash",
            "-lc",
            (
                "source /opt/ros/humble/setup.bash && "
                "source /botbrain_ws/install/setup.bash && "
                f"python3 -c {shlex.quote(code)}"
            ),
        ]
        return subprocess.run(command, capture_output=True, text=True, check=False)

    def status(self) -> BridgeStatus:
        self._probe_runtime()
        with self._lock:
            return BridgeStatus(
                ros_available=self._ros_available,
                navigation_ready=self._navigation_ready,
                current_goal=self._current_goal,
                last_error=self._last_error,
                backend_kind=self.backend_kind,
            )

    def list_locations(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return dict(self._locations)

    def remember_location(self, label: str, *, description: str = "", map_name: str = "map") -> dict[str, Any]:
        del description, map_name
        normalized = label.strip().lower()
        if not normalized:
            raise ValueError("label is required")
        script = textwrap.dedent(
            """
            import json
            import os
            import time

            os.environ.setdefault("RMW_IMPLEMENTATION", "rmw_zenoh_cpp")
            os.environ.setdefault(
                "ZENOH_CONFIG_OVERRIDE",
                'mode="client";connect/endpoints=["tcp/127.0.0.1:7448"]',
            )

            import rclpy
            from geometry_msgs.msg import PoseStamped
            from rclpy.node import Node

            topic = os.environ.get("BRIDGE_LOCALIZATION_TOPIC", "/localization_3d")

            class PoseCapture(Node):
                def __init__(self) -> None:
                    super().__init__("interrupt_nav_pose_capture")
                    self.pose = None
                    self.create_subscription(PoseStamped, topic, self._on_pose, 10)

                def _on_pose(self, msg: PoseStamped) -> None:
                    self.pose = msg

            rclpy.init(args=None)
            node = PoseCapture()
            deadline = time.time() + 5.0
            while time.time() < deadline and node.pose is None:
                rclpy.spin_once(node, timeout_sec=0.2)
            if node.pose is None:
                raise SystemExit("localization pose unavailable")
            msg = node.pose
            print(
                json.dumps(
                    {
                        "position": {
                            "x": float(msg.pose.position.x),
                            "y": float(msg.pose.position.y),
                            "z": float(msg.pose.position.z),
                        },
                        "orientation": {
                            "x": float(msg.pose.orientation.x),
                            "y": float(msg.pose.orientation.y),
                            "z": float(msg.pose.orientation.z),
                            "w": float(msg.pose.orientation.w),
                        },
                    }
                )
            )
            node.destroy_node()
            rclpy.shutdown()
            """
        ).strip()
        result = self._docker_exec_python(
            script,
            extra_env={"BRIDGE_LOCALIZATION_TOPIC": os.getenv("INTERRUPT_G1_NAV_LOCALIZATION_TOPIC", "/localization_3d")},
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "failed to capture localization pose")
        pose = json.loads(result.stdout.strip())
        entry = _entry_from_pose(label.strip(), pose, source_point=pose)
        entry["saved_at"] = int(time.time())
        with self._lock:
            self._locations[normalized] = entry
        self._save_locations()
        return entry

    def navigate_to_label(self, label: str) -> dict[str, Any]:
        normalized = label.strip().lower()
        if not normalized:
            raise ValueError("label is required")
        with self._lock:
            entry = self._locations.get(normalized)
        if entry is None:
            raise KeyError(label)
        self._probe_runtime()
        if not self._ros_available or not self._navigation_ready:
            raise RuntimeError(self._last_error or "docker nav2 backend is not ready")
        script = textwrap.dedent(
            """
            import json
            import os

            os.environ.setdefault("RMW_IMPLEMENTATION", "rmw_zenoh_cpp")
            os.environ.setdefault(
                "ZENOH_CONFIG_OVERRIDE",
                'mode="client";connect/endpoints=["tcp/127.0.0.1:7448"]',
            )

            import rclpy
            from nav2_msgs.action import NavigateToPose
            from rclpy.action import ActionClient
            from rclpy.node import Node

            entry = json.loads(os.environ["BRIDGE_ENTRY_JSON"])
            action_server = os.environ.get("BRIDGE_ACTION_SERVER", "navigate_to_pose")
            frame_id = os.environ.get("BRIDGE_FRAME_ID", "map")

            rclpy.init(args=None)
            node = Node("interrupt_nav_goal_dispatch")
            client = ActionClient(node, NavigateToPose, action_server)
            if not client.wait_for_server(timeout_sec=5.0):
                raise SystemExit(f"NavigateToPose action server not ready: {action_server}")

            goal = NavigateToPose.Goal()
            goal.pose.header.frame_id = frame_id
            goal.pose.header.stamp = node.get_clock().now().to_msg()
            goal.pose.pose.position.x = float(entry["pose"]["position"]["x"])
            goal.pose.pose.position.y = float(entry["pose"]["position"]["y"])
            goal.pose.pose.position.z = float(entry["pose"]["position"]["z"])
            goal.pose.pose.orientation.x = float(entry["pose"]["orientation"]["x"])
            goal.pose.pose.orientation.y = float(entry["pose"]["orientation"]["y"])
            goal.pose.pose.orientation.z = float(entry["pose"]["orientation"]["z"])
            goal.pose.pose.orientation.w = float(entry["pose"]["orientation"]["w"])

            future = client.send_goal_async(goal)
            rclpy.spin_until_future_complete(node, future, timeout_sec=5.0)
            handle = future.result()
            if handle is None or not handle.accepted:
                raise SystemExit("navigation goal was rejected")

            print(json.dumps({"accepted": True}))
            node.destroy_node()
            rclpy.shutdown()
            """
        ).strip()
        result = self._docker_exec_python(
            script,
            extra_env={
                "BRIDGE_ACTION_SERVER": self.action_server,
                "BRIDGE_ENTRY_JSON": json.dumps(entry, ensure_ascii=False),
                "BRIDGE_FRAME_ID": self.frame_id,
            },
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "failed to dispatch docker nav goal")
        with self._lock:
            self._current_goal = str(entry.get("name") or label).strip() or label
        return entry

    def cancel_navigation(self) -> dict[str, Any]:
        raise RuntimeError("docker ros2 navigation cancel is not implemented by this bridge backend")


class BridgeRequestHandler(BaseHTTPRequestHandler):
    bridge: G1ThreeDNavBridge

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        logging.info("%s - %s", self.address_string(), format % args)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/healthz":
            status = self.bridge.status()
            self._write_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "provider": "g1_3d_nav",
                    "backend_kind": status.backend_kind,
                    "ros_available": status.ros_available,
                    "navigation_ready": status.navigation_ready,
                    "current_goal": status.current_goal,
                    "last_error": status.last_error,
                    "nav_root": str(self.bridge.nav_root),
                    "map_file": str(self.bridge.map_file),
                    "locations_file": str(self.bridge.locations_file),
                },
            )
            return
        if self.path == "/maps/locations/list":
            self._write_json(HTTPStatus.OK, self.bridge.list_locations())
            return
        self._write_json(HTTPStatus.NOT_FOUND, {"ok": False, "message": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        payload = self._read_json()
        try:
            if self.path == "/maps/locations/add/slam":
                label = str(payload.get("label") or "").strip()
                entry = self.bridge.remember_location(
                    label,
                    description=str(payload.get("description") or ""),
                    map_name=str(payload.get("map_name") or "map"),
                )
                self._write_json(HTTPStatus.OK, {"ok": True, "message": f"location '{entry['name']}' saved", "entry": entry})
                return
            if self.path == "/navigate/location":
                label = str(payload.get("label") or payload.get("location") or "").strip()
                entry = self.bridge.navigate_to_label(label)
                self._write_json(HTTPStatus.OK, {"ok": True, "message": f"navigating to {entry['name']}", "entry": entry})
                return
            if self.path == "/start/nav2":
                status = self.bridge.status()
                code = HTTPStatus.OK if status.navigation_ready else HTTPStatus.SERVICE_UNAVAILABLE
                self._write_json(
                    code,
                    {
                        "ok": status.navigation_ready,
                        "backend_kind": status.backend_kind,
                        "message": "navigation bridge ready" if status.navigation_ready else status.last_error,
                    },
                )
                return
            if self.path == "/stop/nav2":
                result = self.bridge.cancel_navigation()
                self._write_json(HTTPStatus.OK, {"ok": True, "message": "navigation canceled", **result})
                return
            self._write_json(HTTPStatus.NOT_FOUND, {"ok": False, "message": "not found"})
        except ValueError as exc:
            self._write_json(HTTPStatus.BAD_REQUEST, {"ok": False, "message": str(exc)})
        except KeyError as exc:
            available = sorted(str(entry.get("name") or key) for key, entry in self.bridge.list_locations().items())
            self._write_json(
                HTTPStatus.NOT_FOUND,
                {"ok": False, "message": f"location not found: {exc.args[0]}", "available": available},
            )
        except RuntimeError as exc:
            self._write_json(HTTPStatus.SERVICE_UNAVAILABLE, {"ok": False, "message": str(exc)})
        except Exception as exc:  # pragma: no cover
            logging.exception("bridge request failed")
            self._write_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "message": str(exc)})

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("request body must be valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError("request body must be a JSON object")
        return parsed

    def _write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def build_parser() -> argparse.ArgumentParser:
    nav_root = _default_nav_root()
    parser = argparse.ArgumentParser(description="HTTP bridge for interrupt voice navigation over g1_3d_nav data files.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--nav-root", type=Path, default=nav_root)
    parser.add_argument("--map-file", type=Path, default=_default_map_file(nav_root))
    parser.add_argument("--waypoints-file", type=Path, default=_default_waypoints_file(nav_root))
    parser.add_argument("--action-server", default="navigate_to_pose")
    parser.add_argument("--frame-id", default="map")
    parser.add_argument("--docker-container", default=_default_docker_container())
    parser.add_argument("--log-level", default="INFO")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    bridge = G1ThreeDNavBridge(
        nav_root=args.nav_root,
        map_file=args.map_file,
        waypoints_file=args.waypoints_file,
        action_server=args.action_server,
        frame_id=args.frame_id,
        docker_container=args.docker_container,
    )
    BridgeRequestHandler.bridge = bridge
    server = ThreadingHTTPServer((args.host, args.port), BridgeRequestHandler)
    logging.info(
        "g1_3d_nav bridge listening on %s:%s backend=%s nav_root=%s map_file=%s locations_file=%s",
        args.host,
        args.port,
        bridge.backend_kind,
        args.nav_root,
        args.map_file,
        bridge.locations_file,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("shutdown requested")
    finally:
        server.server_close()
        if rclpy is not None and rclpy.ok():  # pragma: no cover
            rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
