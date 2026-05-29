#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from bridge.g1_3d_nav_bridge import _parse_waypoint_payload, _serialize_locations


class WaypointFormatTests(unittest.TestCase):
    def test_nested_waypoints_yaml_is_supported(self) -> None:
        payload = {
            "frame_id": "map",
            "waypoints": {
                "entrance": {
                    "x": -0.0361,
                    "y": 0.0302,
                    "z": -0.0109,
                    "qx": -0.00954,
                    "qy": -0.00232,
                    "qz": -0.051629,
                    "qw": 0.998618,
                    "yaw": -0.1033,
                    "samples": 30,
                }
            },
        }

        locations, frame_id, storage_format = _parse_waypoint_payload(payload)

        self.assertEqual(frame_id, "map")
        self.assertEqual(storage_format, "nested_waypoints")
        self.assertIn("entrance", locations)
        self.assertAlmostEqual(locations["entrance"]["pose"]["position"]["x"], -0.0361)
        self.assertAlmostEqual(locations["entrance"]["pose"]["orientation"]["w"], 0.998618)

    def test_nested_waypoints_round_trip_preserves_schema(self) -> None:
        payload = {
            "frame_id": "map",
            "waypoints": {
                "middle": {
                    "x": 1.5,
                    "y": 0.3,
                    "z": 0.0,
                    "qx": 0.0,
                    "qy": 0.0,
                    "qz": 0.1,
                    "qw": 0.99,
                    "yaw": 0.2,
                    "samples": 12,
                }
            },
        }

        locations, frame_id, storage_format = _parse_waypoint_payload(payload)
        saved = _serialize_locations(locations, frame_id=frame_id, storage_format=storage_format)

        self.assertEqual(saved["frame_id"], "map")
        self.assertIn("middle", saved["waypoints"])
        self.assertEqual(saved["waypoints"]["middle"]["samples"], 12)
        self.assertAlmostEqual(saved["waypoints"]["middle"]["x"], 1.5)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
