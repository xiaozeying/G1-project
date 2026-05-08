#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.g1_dialogue_state import DialogueConfig, WakewordDialogueController
from src.g1_om1_adapter import G1Om1AdapterConfig
from src.navigation_intents import (
    extract_navigation_destination,
    extract_remember_location_name,
    looks_like_relative_motion_command,
    looks_like_saved_locations_query,
)
from src.om1_wakeword_gate import _normalize_followup_text, _normalize_wake_text


class WakewordNormalizationTests(unittest.TestCase):
    def test_normalize_wake_aliases(self) -> None:
        self.assertEqual(_normalize_wake_text("笨笨你好"), "你好笨笨")
        self.assertEqual(_normalize_wake_text("本本"), "笨笨")
        self.assertEqual(_normalize_wake_text("对本"), "笨笨")
        self.assertEqual(_normalize_wake_text("贝贝同学"), "笨笨同学")
        self.assertEqual(_normalize_wake_text("本同学"), "笨笨同学")
        self.assertEqual(_normalize_wake_text("根本同学"), "笨笨同学")

    def test_normalize_followup_led_aliases(self) -> None:
        self.assertEqual(_normalize_followup_text("把L灯变红"), "把LED灯变红")
        self.assertEqual(_normalize_followup_text("benben同学"), "笨笨同学")


class DialogueStateTests(unittest.TestCase):
    def _controller(self) -> WakewordDialogueController:
        return WakewordDialogueController(
            DialogueConfig(
                wakewords=["笨笨同学", "笨笨"],
                interrupt_suffixes=["先别说了", "等一下"],
                session_timeout_s=5.0,
            )
        )

    def test_dialogue_flow(self) -> None:
        controller = self._controller()

        event = controller.process_text("笨笨同学", now=0.0)
        self.assertEqual(event.kind, "wake_ack")

        event = controller.process_text("把灯变成蓝色", now=1.0)
        self.assertEqual(event.kind, "forward_followup")
        self.assertEqual(event.text, "把灯变成蓝色")

        event = controller.process_text("笨笨同学，先别说了", now=2.0)
        self.assertEqual(event.kind, "interrupt")
        self.assertEqual(event.wakeword, "笨笨同学")

        event = controller.process_text("帮我挥手", now=3.0)
        self.assertEqual(event.kind, "forward_followup")

    def test_timeout_expires_session(self) -> None:
        controller = self._controller()
        controller.process_text("笨笨同学", now=0.0)
        timeout_event = controller.expire_if_needed(now=6.0)
        self.assertIsNotNone(timeout_event)
        assert timeout_event is not None
        self.assertEqual(timeout_event.kind, "session_timeout")


class AdapterDefaultsTests(unittest.TestCase):
    def test_interface_default_is_eth1(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            config = G1Om1AdapterConfig.from_env()
        self.assertEqual(config.unitree_interface, "eth1")

    def test_navigation_script_default_exists_in_config(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            config = G1Om1AdapterConfig.from_env()
        self.assertTrue(config.navigation_script.endswith("g1_nav_command.py"))


class NavigationIntentTests(unittest.TestCase):
    def test_extract_navigation_destination(self) -> None:
        self.assertEqual(extract_navigation_destination("带我去电梯"), "电梯")
        self.assertEqual(extract_navigation_destination("請帶我去 會議室 呀"), "會議室")
        self.assertEqual(extract_navigation_destination("navigate to table"), "table")
        self.assertEqual(extract_navigation_destination("go to charging station please"), "charging station")

    def test_extract_remember_location_name(self) -> None:
        self.assertEqual(extract_remember_location_name("记住这里是前台"), "前台")
        self.assertEqual(extract_remember_location_name("save this location as meeting room"), "meeting room")

    def test_relative_motion_not_treated_as_navigation(self) -> None:
        self.assertTrue(looks_like_relative_motion_command("往前走几步"))
        self.assertTrue(looks_like_relative_motion_command("turn around"))
        self.assertIsNone(extract_navigation_destination("往前走几步"))

    def test_saved_locations_query_detection(self) -> None:
        self.assertTrue(looks_like_saved_locations_query("有哪些位置可以去"))
        self.assertTrue(looks_like_saved_locations_query("where can you go"))


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
