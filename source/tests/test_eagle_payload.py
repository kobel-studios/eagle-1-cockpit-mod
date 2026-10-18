"""Exercise the real Lua payload controller without the game or native hooks.

Run from HQ:
python -m unittest discover -s downloads/hd2-mods/tests -p test_eagle_payload.py
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "test_runtime"))
from lupa.lua51 import LuaRuntime

BOMB = dict(id="bomb500", name="500 KG",
            output="output/v1/projectile/eagle-500kg-bomb-projectile-239",
            capacity=2)
ROCKET = dict(id="rockets", name="ROCKETS",
              output="output/v1/projectile/eagle-110mm-rocket-pods-82",
              capacity=3)
POD = dict(id="gas", name="GAS", output="output/v1/projectile/gas-188",
           capacity=1)


class PayloadTests(unittest.TestCase):
    def setUp(self):
        # Own Lua source only. No installed mod bytecode is executed.
        self.lua = LuaRuntime(register_eval=False, register_builtins=False)
        self.module = self.lua.execute((ROOT / "eagle_payload.lua").read_text())
        self.calls = []
        self.callback = lambda spec: self.calls.append(spec.id) or "requested"
        self.bridge = self.lua.eval("function(fn) return function(c) return fn(c) end end")
        self.controller = self.make(dict(weapons=[BOMB, ROCKET], rearm_seconds=3))
        self.context = dict(now=0, authority=True, in_cockpit=True, alive=True,
                            focused=True, paused=False, grounded=False,
                            landed=False, stationary=False, speed=20,
                            fire=False, rearm=False, select=False)

    def lua_table(self, value):
        # This lupa build's table_from is shallow; convert nested values.
        if isinstance(value, dict):
            return self.lua.table_from(
                {key: self.lua_table(item) for key, item in value.items()})
        if isinstance(value, (list, tuple)):
            return self.lua.table_from([self.lua_table(item) for item in value])
        return value

    def make(self, options):
        return self.module.new(self.bridge(lambda spec: self.callback(spec)),
                               self.lua_table(options))

    def tick(self, now, **changes):
        self.context.update(now=now, **changes)
        return self.controller.update(self.lua.table_from(self.context))

    def fire(self, now, **changes):
        self.tick(now, fire=False, **changes)
        return self.tick(now, fire=True, **changes)

    def press_select(self, now):
        self.tick(now, select=False)
        return self.tick(now, select=True)

    def begin_rearm(self, now):
        self.tick(now, rearm=False)
        return self.tick(now, rearm=True, landed=True, stationary=True,
                         speed=0, grounded=True, flight_enabled=False)

    def test_weapons_have_independent_ammo(self):
        state = self.tick(0)
        self.assertEqual(state.selected, 1)
        self.assertEqual(state.selected_name, "500 KG")
        self.assertEqual(state.ammo, 2)
        self.assertEqual(state.capacity, 2)
        self.assertEqual(state.weapons[1].ammo, 2)
        self.assertEqual(state.weapons[1].capacity, 2)
        self.assertEqual(state.weapons[1].name, "500 KG")
        self.assertEqual(state.weapons[1].output, BOMB["output"])
        self.assertEqual(state.weapons[2].ammo, 3)
        self.assertEqual(state.weapons[2].capacity, 3)
        self.assertIsNone(state.weapons[3])

    def test_select_cycles_forward_and_wraps(self):
        self.assertEqual(self.press_select(0).selected, 2)
        self.assertEqual(self.press_select(1).selected, 1)
        state = self.press_select(2)
        self.assertEqual((state.selected, state.selected_name), (2, "ROCKETS"))
        self.assertEqual(state.ammo, 3)

    def test_select_wraps_through_all_three(self):
        self.controller = self.make(dict(weapons=[BOMB, ROCKET, POD]))
        self.assertEqual(self.press_select(0).selected, 2)
        self.assertEqual(self.press_select(1).selected, 3)
        state = self.press_select(2)
        self.assertEqual(state.selected, 1)
        self.assertEqual(state.selected_name, "500 KG")

    def test_held_select_does_not_cycle_repeatedly(self):
        self.tick(0, select=False)  # attach with the key released
        self.tick(0.1, select=True)
        for now in (0.2, 0.3, 0.4, 0.5):
            self.tick(now, select=True)
        self.assertEqual(self.controller.state().selected, 2)
        self.tick(1, select=False)
        self.assertEqual(self.press_select(2).selected, 1)  # wraps to first

    def test_attach_with_select_held_is_not_a_press(self):
        self.context.update(select=True)
        self.tick(0)
        self.tick(1)
        self.assertEqual(self.controller.state().selected, 1)

    def test_select_reports_readable_status(self):
        state = self.press_select(0)
        self.assertEqual(state.status, "selected ROCKETS")
        self.assertEqual(self.press_select(1).status, "selected 500 KG")

    def test_select_index_jumps_to_slot(self):
        state = self.tick(0, select_index=2)
        self.assertEqual((state.selected, state.selected_name), (2, "ROCKETS"))
        state = self.tick(1, select_index=1)
        self.assertEqual(state.selected_name, "500 KG")
        for bad in (0, 3, 1.5, -1, "x"):
            self.assertEqual(self.tick(2, select_index=bad).selected, 1)

    def test_select_is_allowed_during_a_rearm_run(self):
        self.fire(0)
        self.begin_rearm(1)
        state = self.tick(2, select=True, rearm=False)
        self.assertTrue(state.rearming)
        self.assertEqual(state.selected_name, "ROCKETS")
        self.tick(3)
        state = self.tick(4)
        self.assertEqual(state.status, "rearmed")
        self.assertEqual(state.selected_name, "ROCKETS")

    def test_fire_only_decrements_selected_weapon(self):
        self.press_select(0)
        state = self.fire(1)
        self.assertEqual(state.ammo, 2)
        self.assertEqual(state.weapons[1].ammo, 2)
        self.assertEqual(state.weapons[2].ammo, 2)
        self.assertEqual(self.calls, ["rockets"])
        self.assertEqual(state.status, "ROCKETS released")

    def test_same_tick_select_and_fire_drops_new_selection(self):
        self.tick(0, select=False, fire=False)
        state = self.tick(1, select=True, fire=True)
        self.assertEqual(self.calls, ["rockets"])
        self.assertEqual(state.ammo, 2)
        self.assertEqual(state.selected, 2)

    def test_empty_selected_does_not_block_other_weapon(self):
        self.assertEqual(self.fire(0).ammo, 1)
        self.assertEqual(self.fire(1).ammo, 0)
        self.assertEqual(self.fire(2).status, "out of 500 KG")
        self.press_select(3)
        self.assertEqual(self.fire(4).ammo, 2)
        self.assertEqual(self.calls, ["bomb500", "bomb500", "rockets"])

    def test_spawn_gets_selected_weapon_spec_table(self):
        seen = []
        self.callback = lambda spec: seen.append(
            (spec.id, spec.name, spec.output, spec.capacity)) or "requested"
        self.press_select(0)
        self.fire(1)
        self.assertEqual(seen, [("rockets", "ROCKETS", ROCKET["output"], 3)])

    def test_spawn_spec_cannot_corrupt_internal_state(self):
        def tamper(spec):
            spec.ammo = 0
            spec.capacity = 99
            return "requested"
        self.callback = tamper
        self.fire(0)
        self.fire(1)
        self.assertEqual(self.fire(2).status, "out of 500 KG")
        fresh = self.controller.state()
        self.assertEqual(fresh.weapons[1].capacity, 2)

    def test_hold_fire_and_cooldown_cannot_repeat(self):
        self.fire(0)
        self.tick(0.1, fire=True)
        self.assertEqual(self.fire(0.5).status, "release interval")
        self.tick(2, fire=True)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.fire(2).ammo, 0)

    def test_release_interval_is_shared_across_weapons(self):
        self.fire(0)
        self.press_select(0.5)
        state = self.fire(0.9)
        self.assertEqual(state.status, "release interval")
        self.assertEqual(state.weapons[2].ammo, 3)

    def test_attaching_while_fire_held_does_not_release(self):
        self.tick(0, fire=True)
        self.tick(1, fire=True)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.fire(2).ammo, 1)

    def test_requested_string_confirms_release(self):
        self.callback = lambda spec: "requested"
        self.assertEqual(self.fire(0).ammo, 1)

    def test_requested_status_table_confirms_release(self):
        self.callback = lambda spec: self.lua_table(dict(status="requested"))
        self.assertEqual(self.fire(0).ammo, 1)

    def test_true_result_still_confirms_release(self):
        self.callback = lambda spec: True
        self.assertEqual(self.fire(0).ammo, 1)

    def test_explicit_rejection_preserves_ammo(self):
        self.callback = lambda spec: False
        state = self.fire(0)
        self.assertEqual(state.ammo, 2)
        self.assertFalse(state.faulted)
        self.assertEqual(state.status, "release rejected")

    def test_rejected_status_table_preserves_ammo(self):
        # Entry wraps adapter rejections as {status="rejected"}.
        self.callback = lambda spec: self.lua_table(dict(status="rejected"))
        state = self.fire(0)
        self.assertEqual(state.ammo, 2)
        self.assertFalse(state.faulted)
        self.assertEqual(state.status, "release rejected")

    def test_ambiguous_spawn_disables_instead_of_retrying(self):
        for outcome in (None, "yes", 0, "uncertain"):
            with self.subTest(outcome=outcome):
                self.setUp()
                calls = [0]
                def cb(spec):
                    calls[0] += 1
                    return outcome
                self.callback = cb
                state = self.fire(0)
                self.assertEqual(state.ammo, 1)
                self.assertTrue(state.faulted)
                self.assertEqual(self.fire(2).ammo, 1)
                self.assertEqual(calls[0], 1)  # no auto-retry

    def test_non_requested_status_table_is_uncertain(self):
        for status in ("refused", "cancelled", "uncertain", "mystery"):
            with self.subTest(status=status):
                self.setUp()
                self.callback = lambda spec: self.lua_table(dict(status=status))
                state = self.fire(0)
                self.assertEqual(state.ammo, 1)
                self.assertTrue(state.faulted)

    def test_exception_after_spawn_cannot_duplicate(self):
        calls = [0]
        def failure(spec):
            calls[0] += 1
            raise RuntimeError("outcome unknown")
        self.callback = failure
        self.assertTrue(self.fire(0).faulted)
        self.fire(2)
        self.assertEqual(calls[0], 1)

    def test_reentrant_adapter_cannot_double_fire(self):
        calls = [0]
        def recursive(spec):
            calls[0] += 1
            self.controller.update(spec)
            return "requested"
        self.callback = recursive
        self.assertEqual(self.fire(0).ammo, 1)
        self.assertEqual(calls[0], 1)

    def test_invalid_state_blocks_firing(self):
        for change in (dict(authority=False), dict(in_cockpit=False),
                       dict(alive=False), dict(focused=False), dict(paused=True),
                       dict(paused=None), dict(grounded=True), dict(landed=True),
                       dict(grounded=None, landed=None)):
            with self.subTest(change=change):
                self.setUp()
                self.tick(0, fire=False, **change)
                self.tick(0, fire=True, **change)
                self.assertEqual(self.calls, [])
                self.assertEqual(self.controller.state().ammo, 2)

    def test_seat_switch_does_not_refill_or_create_a_press(self):
        self.fire(0)
        self.tick(1, in_cockpit=False, fire=False)
        self.tick(2, in_cockpit=False, fire=True)
        self.tick(3, in_cockpit=True, fire=True)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.controller.state().ammo, 1)

    def test_rearm_requires_landed_stationary_and_stopped(self):
        for changes in (dict(landed=False), dict(landed=None),
                        dict(stationary=False), dict(stationary=None),
                        dict(speed=0.6), dict(speed=float("nan")),
                        dict(flight_enabled=True)):
            with self.subTest(changes=changes):
                self.setUp()
                self.fire(0)
                ctx = dict(landed=True, stationary=True, speed=0)
                ctx.update(changes)
                state = self.tick(1, fire=False, rearm=True, **ctx)
                self.assertFalse(state.rearming)
                self.assertEqual(state.status,
                                 "landed and stationary required")
                self.assertEqual(state.weapons[1].ammo, 1)

    def test_rearm_speed_limit_applies_even_when_stationary_flag_is_true(self):
        # The core checks reported speed itself; a stale/wrong stationary
        # flag cannot launder a moving vehicle into a rearm run.
        self.fire(0)
        state = self.tick(1, rearm=True, landed=True, stationary=True,
                          speed=0.6)
        self.assertFalse(state.rearming)
        state = self.tick(2, rearm=False, speed=0.5)
        self.assertTrue(self.begin_rearm(3).rearming)

    def test_rearm_allows_missing_speed(self):
        self.fire(0)
        state = self.tick(1, rearm=True, landed=True, stationary=True,
                          speed=None)
        self.assertTrue(state.rearming)

    def test_docked_and_service_area_flags_are_ignored(self):
        self.fire(0)
        # Old service-point flags cannot start a run without landed+stationary.
        state = self.tick(1, rearm=True, docked=True, in_service_area=True,
                          landed=False, stationary=False, speed=0)
        self.assertFalse(state.rearming)
        self.assertEqual(state.weapons[1].ammo, 1)
        # A landed stationary run needs no service point at all.
        self.tick(2, rearm=False, docked=False, in_service_area=False)
        self.assertTrue(self.begin_rearm(3).rearming)

    def test_service_block_reasons_describe_the_gate(self):
        self.fire(0)
        state = self.tick(1, rearm=True, landed=False, stationary=False,
                          speed=0)
        self.assertEqual(state.service_block_reason,
                         "land before starting a rearm run")
        state = self.tick(2, rearm=False, landed=True)
        self.assertEqual(state.service_block_reason, "hold still to rearm")
        state = self.tick(3, stationary=True, speed=3)
        self.assertEqual(state.service_block_reason, "stop to rearm")
        state = self.tick(4, speed=float("nan"))
        self.assertEqual(state.service_block_reason,
                         "waiting for measured vehicle speed")

    def test_rearm_run_refills_every_weapon(self):
        self.fire(0)                    # 500 KG -> 1
        self.press_select(1)
        self.fire(2)
        self.fire(3)                    # ROCKETS -> 1
        state = self.begin_rearm(4)
        self.assertTrue(state.rearming)
        self.assertEqual(state.status, "rearm run inbound")
        for now in (5, 6):
            state = self.tick(now, rearm=False)
            self.assertTrue(state.rearming)
        state = self.tick(7)
        self.assertFalse(state.rearming)
        self.assertEqual(state.status, "rearmed")
        self.assertEqual(state.weapons[1].ammo, 2)
        self.assertEqual(state.weapons[2].ammo, 3)
        self.assertEqual(state.rearm_progress, 1)

    def test_rearm_progress_and_remaining_time(self):
        self.fire(0)
        state = self.begin_rearm(1)
        self.assertEqual(state.rearm_remaining, 3)
        self.assertEqual(state.rearm_elapsed, 0)
        state = self.tick(2, rearm=False)
        self.assertAlmostEqual(state.rearm_progress, 1 / 3)
        self.assertEqual(state.rearm_remaining, 2)
        self.tick(3)
        state = self.tick(4)
        self.assertEqual(state.status, "rearmed")

    def test_moving_or_unlanding_cancels_and_resets_timer(self):
        for changes in (dict(landed=False), dict(stationary=False),
                        dict(speed=2)):
            with self.subTest(changes=changes):
                self.setUp()
                self.fire(0)
                self.begin_rearm(1)
                self.tick(2, rearm=False)
                state = self.tick(3, **changes)
                self.assertFalse(state.rearming)
                self.assertEqual(state.status, "rearm cancelled: moved")
                self.assertEqual(state.rearm_progress, 0)
                self.assertEqual(state.weapons[1].ammo, 1)
                # A fresh press restarts the full run from zero.
                self.tick(4, landed=True, stationary=True, speed=0)
                state = self.begin_rearm(5)
                self.assertTrue(state.rearming)
                self.assertEqual(state.rearm_elapsed, 0)
                self.assertEqual(state.rearm_remaining, 3)

    def test_flight_mode_vetoes_and_cancels_rearm(self):
        self.fire(0)
        state = self.tick(1, rearm=True, landed=True, stationary=True, speed=0,
                          flight_enabled=True)
        self.assertFalse(state.rearming)
        self.assertEqual(state.service_block_reason, "switch flight mode off")
        self.tick(2, rearm=False, flight_enabled=False)
        self.begin_rearm(3)
        state = self.tick(4, rearm=False, flight_enabled=True)
        self.assertEqual(state.status, "rearm cancelled: flight mode on")
        self.assertEqual(state.weapons[1].ammo, 1)
        self.assertEqual(state.rearm_elapsed, 0)

    def test_inactivity_cancels_rearm_and_needs_fresh_press(self):
        restore = dict(paused=False, focused=True, in_cockpit=True,
                       authority=True, alive=True)
        for changes in (dict(paused=True), dict(focused=False),
                        dict(in_cockpit=False), dict(authority=False),
                        dict(alive=False)):
            with self.subTest(changes=changes):
                self.setUp()
                self.fire(0)
                self.begin_rearm(1)
                state = self.tick(2, **changes)
                self.assertFalse(state.rearming)
                self.assertEqual(state.weapons[1].ammo, 1)
                state = self.tick(3, **restore)
                self.assertFalse(state.rearming)  # Home still held, no press
                self.tick(4, rearm=False)
                self.assertTrue(self.begin_rearm(5).rearming)

    def test_long_gap_does_not_count_as_service(self):
        self.fire(0)
        self.begin_rearm(1)
        state = self.tick(10, rearm=False)
        self.assertFalse(state.rearming)
        self.assertEqual(state.status, "rearm cancelled: missing updates")
        self.assertEqual(state.weapons[1].ammo, 1)

    def test_bad_clock_cancels_rearm(self):
        for now in (float("nan"), float("inf"), -1, 0.5):
            with self.subTest(now=now):
                self.setUp()
                self.fire(0)
                self.begin_rearm(1)
                state = self.tick(now, rearm=False)
                self.assertEqual(state.status, "invalid clock")
                self.assertFalse(state.rearming)
                self.assertEqual(state.weapons[1].ammo, 1)

    def test_rearm_when_everything_full_is_already_full(self):
        state = self.begin_rearm(0)
        self.assertEqual(state.status, "already full")
        self.assertFalse(state.rearming)
        state = self.fire(1, grounded=False, landed=False, stationary=False,
                          speed=20)
        self.assertEqual(state.ammo, 1)
        self.assertTrue(self.begin_rearm(2).rearming)

    def test_held_keys_do_not_fire_or_restart_after_completion(self):
        self.fire(0)
        self.begin_rearm(1)
        for now in (2, 3, 4):
            state = self.tick(now, fire=True, rearm=True)
        self.assertEqual(state.status, "rearmed")
        self.assertFalse(state.rearming)
        state = self.tick(5, fire=True, rearm=True)
        self.assertFalse(state.rearming)
        self.assertEqual(len(self.calls), 1)  # held fire never pressed again
        state = self.fire(6, grounded=False, landed=False, stationary=False,
                          speed=20, rearm=False)
        self.assertEqual(state.ammo, 1)
        self.assertEqual(state.status, "500 KG released")

    def test_faulted_latches_and_survives_seat_changes_and_rearm(self):
        self.callback = lambda spec: None
        self.fire(0)
        self.tick(1, in_cockpit=False)
        self.tick(2, in_cockpit=True)
        self.press_select(3)  # selection stays frozen while faulted
        state = self.controller.state()
        self.assertEqual(state.selected, 1)
        self.assertTrue(state.faulted)
        self.assertEqual(state.status,
                         "release outcome unknown; weapons disabled")
        self.begin_rearm(4)
        self.assertFalse(self.controller.state().rearming)
        self.assertEqual(self.controller.state().ammo, 1)

    def test_state_survives_inactive_gaps(self):
        self.press_select(0)
        self.fire(1)
        for now in (2, 3, 4):
            self.tick(now, in_cockpit=False, paused=True)
        state = self.tick(5, in_cockpit=True, paused=False)
        self.assertEqual(state.selected, 2)
        self.assertEqual(state.selected_name, "ROCKETS")
        self.assertEqual(state.weapons[2].ammo, 2)
        self.assertEqual(state.ammo, 2)

    def test_state_snapshot_cannot_move_ammo_or_selection(self):
        self.fire(0)
        snapshot = self.controller.state()
        snapshot.ammo = 999
        snapshot.selected = 2
        snapshot.weapons[1].ammo = 999
        fresh = self.controller.state()
        self.assertEqual(fresh.ammo, 1)
        self.assertEqual(fresh.selected, 1)
        self.assertEqual(fresh.weapons[1].ammo, 1)

    def test_single_capacity_wraps_as_one_500kg_weapon(self):
        self.controller = self.make(dict(capacity=2))
        state = self.tick(0)
        self.assertEqual(state.selected, 1)
        self.assertEqual(state.selected_name, "500 KG")
        self.assertEqual(state.weapons[1].id, "bomb500")
        self.assertEqual(state.weapons[1].name, "500 KG")
        self.assertEqual(state.weapons[1].output,
                         "output/v1/projectile/eagle-500kg-bomb-projectile-239")
        self.assertIsNone(state.weapons[2])
        self.assertEqual(self.fire(0).ammo, 1)
        self.assertEqual(self.calls, ["bomb500"])
        self.assertEqual(self.press_select(2).selected, 1)  # wrap on one weapon

    def test_custom_single_weapon_fields_are_kept(self):
        self.controller = self.make(dict(capacity=4, name="NAPALM",
                                         output="output/v1/x", id="napalm"))
        state = self.tick(0)
        self.assertEqual(state.selected_name, "NAPALM")
        self.assertEqual(state.weapons[1].id, "napalm")
        self.assertEqual(state.weapons[1].output, "output/v1/x")
        self.assertEqual(state.capacity, 4)

    def test_default_options_build_one_500kg_weapon(self):
        self.controller = self.make({})
        state = self.tick(0)
        self.assertEqual(state.selected_name, "500 KG")
        self.assertEqual(state.capacity, 2)

    def test_invalid_settings_rejected(self):
        good = dict(id="x", name="X", output="o", capacity=1)
        cases = (
            dict(capacity=0), dict(capacity=1.5), dict(capacity=17),
            dict(capacity=float("nan")), dict(rearm_seconds=0),
            dict(drop_interval=-1), dict(weapons=[]), dict(weapons="nope"),
            dict(weapons=[good] * 17),
            dict(weapons=[dict(name="X", output="o", capacity=1)]),
            dict(weapons=[dict(id="x", output="o", capacity=1)]),
            dict(weapons=[dict(id="x", name="X", capacity=1)]),
            dict(weapons=[dict(id="x", name="X", output="o")]),
            dict(weapons=[dict(id="x", name="X", output="o", capacity=0)]),
            dict(weapons=[dict(id="x", name="X", output="o", capacity=1.5)]),
            dict(weapons=[dict(id="x", name="X", output="o", capacity=20)]),
        )
        for opts in cases:
            with self.subTest(opts=opts), self.assertRaises(Exception):
                self.module.new(self.bridge(self.callback),
                                self.lua_table(opts))


if __name__ == "__main__":
    unittest.main()
