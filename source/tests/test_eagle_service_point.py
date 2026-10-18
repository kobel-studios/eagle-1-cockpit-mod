"""Safe Lua tests for a mission-local, stationary rearm zone."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "test_runtime"))
from lupa.lua51 import LuaRuntime


class ServicePointTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(register_eval=False, register_builtins=False,
                              unpack_returned_tuples=True)
        module = self.lua.execute((ROOT / "eagle_service_point.lua").read_text())
        self.service = module.new()

    def pos(self, x=10, y=20, z=30):
        return self.lua.table_from(dict(x=x, y=y, z=z))

    def stand(self):
        for now in (0, 1, 2, 3):
            self.service.observe(now, self.pos(), True)

    def test_stationary_mark_and_park(self):
        self.stand()
        self.assertEqual(self.service.mark(3), (True, "service point set"))
        self.assertTrue(self.service.docked(self.pos(z=31), False, 0))
        self.assertTrue(self.service.docked(self.pos(x=18, z=32), False, 0.5))

    def test_no_remote_or_airborne_or_moving_rearm(self):
        self.stand()
        self.service.mark(3)
        for p, flying, speed in ((self.pos(x=18.01), False, 0),
                                 (self.pos(z=32.01), False, 0),
                                 (self.pos(), True, 0), (self.pos(), None, 0),
                                 (self.pos(), False, 0.51),
                                 (self.pos(), False, float("nan")),
                                 (self.pos(), False, -1)):
            self.assertFalse(self.service.docked(p, flying, speed))

    def test_cannot_move_existing_point_to_plane(self):
        self.stand()
        self.service.mark(3)
        for now in (4, 5, 6, 7):
            self.service.observe(now, self.pos(x=500), True)
        self.assertFalse(self.service.mark(7)[0])
        self.assertEqual(self.service.point().x, 10)

    def test_requires_observed_on_foot_stillness(self):
        for in_vehicle in (True, False):
            self.setUp()
            for now in range(4):
                self.service.observe(now, self.pos(x=10 + now), not in_vehicle)
            self.assertFalse(self.service.mark(3)[0])

    def test_gap_and_stale_sample_do_not_authorize_marker(self):
        self.service.observe(0, self.pos(), True)
        self.service.observe(3, self.pos(), True)
        self.assertFalse(self.service.mark(3)[0])
        self.setUp()
        self.stand()
        self.assertFalse(self.service.mark(4)[0])

    def test_point_copy_cannot_move_zone(self):
        self.stand()
        self.service.mark(3)
        self.service.point().x = 500
        self.assertEqual(self.service.point().x, 10)

    def test_new_mission_starts_without_marker(self):
        self.assertIsNone(self.service.point())
        self.assertFalse(self.service.docked(self.pos(), False, 0))

    def test_navigation_offsets_point_back_to_pad(self):
        self.stand()
        self.service.mark(3)
        result = self.service.describe(self.pos(x=13, y=24, z=35), True, 20)
        self.assertEqual(result.horizontal_distance, 5)
        self.assertEqual(result.vertical_offset, -5)
        self.assertEqual((result.offset.x, result.offset.y, result.offset.z), (-3, -4, -5))
        self.assertEqual(result.reason_code, "wrong_height")
        self.assertFalse(result.within_zone)
        result.offset.x = 500
        self.assertEqual(self.service.point().x, 10)

    def test_navigation_reasons_and_docking_agree(self):
        self.assertEqual(self.service.describe(self.pos(), False, 0).reason_code, "unmarked")
        self.stand()
        self.service.mark(3)
        for p, flying, speed, reason in (
                (None, False, 0, "position_unknown"),
                (self.pos(x=float("nan")), False, 0, "position_unknown"),
                (self.pos(x=19), False, 0, "too_far"),
                (self.pos(z=33), False, 0, "wrong_height"),
                (self.pos(), True, 0, "flight_enabled"),
                (self.pos(), None, 0, "flight_enabled"),
                (self.pos(), False, None, "speed_unknown"),
                (self.pos(), False, float("inf"), "speed_unknown"),
                (self.pos(), False, -1, "speed_unknown"),
                (self.pos(), False, 0.51, "moving"),
                (self.pos(x=18, z=32), False, 0.5, "ready")):
            with self.subTest(reason=reason):
                result = self.service.describe(p, flying, speed)
                self.assertEqual(result.reason_code, reason)
                self.assertEqual(result.docked, reason == "ready")
                self.assertEqual(result.docked, self.service.docked(p, flying, speed))

    def test_slow_drift_resets_three_second_marking_window(self):
        # Tiny per-frame movements must not accumulate unlimited anchor drift.
        for step in range(17):
            self.service.observe(step * 0.25, self.pos(x=10 + step * 0.05), True)
        self.assertFalse(self.service.mark(4)[0])
        for step in range(1, 13):
            self.service.observe(4 + step * 0.25, self.pos(x=10.8), True)
        self.assertTrue(self.service.mark(7)[0])

    def test_leaving_foot_or_clock_reversal_restarts_observation(self):
        for invalid in ("vehicle", "clock"):
            with self.subTest(invalid=invalid):
                self.setUp()
                self.stand()
                self.service.observe(2 if invalid == "clock" else 4,
                                     self.pos(), invalid != "vehicle")
                self.service.observe(4, self.pos(), True)
                self.assertFalse(self.service.mark(4)[0])
                for now in (5, 6, 7):
                    self.service.observe(now, self.pos(), True)
                self.assertTrue(self.service.mark(7)[0])


if __name__ == "__main__":
    unittest.main()
