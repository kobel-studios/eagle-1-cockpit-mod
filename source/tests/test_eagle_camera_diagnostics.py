"""Run only our read-only Lua addon with mock loader/game callbacks."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "test_runtime"))
from lupa.lua51 import LuaRuntime


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(register_eval=False, register_builtins=False,
                              unpack_returned_tuples=True)
        self.lua.execute("""
            lines = {}; updates = 0; shutdowns = 0; closed = false
            handle = {
                write=function(self, s) lines[#lines+1]=s end,
                flush=function() end,
                close=function() closed=true end
            }
            CowboyBingusModLoader={open_log=function(name)
                assert(name == 'EagleCameraDiagnostics.log'); return handle end}
            update=function(a,b) updates=updates+1; return a,nil,b end
            shutdown=function(a) shutdowns=shutdowns+1; return a end
            VehicleFlight={flying=true, tmpl=26, vehicle=123}
            AdvancedTankCamera={status='ready'}
            SoloVehicleDriver={status='ready'}
        """)
        self.source = (ROOT / "eagle_camera_diagnostics.lua").read_text()

    def test_passes_arguments_and_nil_returns_and_reads_telemetry(self):
        self.lua.execute(self.source)
        g = self.lua.globals()
        self.assertEqual(g.update(4, 5), (4, None, 5))
        self.assertEqual(g.updates, 1)
        self.assertIn("tmpl=26", g.lines[2])
        self.assertEqual(g.VehicleFlight.tmpl, 26)
        self.assertEqual(g.VehicleFlight.vehicle, 123)

    def test_duplicate_load_does_not_double_wrap(self):
        self.lua.execute(self.source)
        self.lua.execute(self.source)
        self.lua.globals().update(1, 2)
        self.assertEqual(self.lua.globals().updates, 1)
        self.assertEqual(len(self.lua.globals().lines), 2)

    def test_shutdown_closes_log_and_preserves_return(self):
        self.lua.execute(self.source)
        g = self.lua.globals()
        self.assertEqual(g.shutdown("ok"), "ok")
        self.assertTrue(g.closed)
        self.assertTrue(g.EagleCameraDiagnostics.stopped)
        self.assertEqual(g.shutdowns, 1)
        g.update(1, 2)
        self.assertEqual(g.updates, 1)

    def test_original_game_error_propagates(self):
        self.lua.execute("update=function() error('game callback failure') end")
        self.lua.execute(self.source)
        with self.assertRaisesRegex(Exception, "game callback failure"):
            self.lua.globals().update()

    def test_log_failure_does_not_break_game_update(self):
        self.lua.execute(self.source)
        self.lua.execute("handle.write=function() error('disk unavailable') end")
        g = self.lua.globals()
        self.assertEqual(g.update(1, 2), (1, None, 2))
        self.assertTrue(g.closed)
        self.assertEqual(g.update(3, 4), (3, None, 4))

    def test_missing_loader_or_update_is_inert(self):
        for setup in ("CowboyBingusModLoader=nil", "update=nil"):
            with self.subTest(setup=setup):
                self.setUp()
                self.lua.execute(setup)
                self.lua.execute(self.source)
                self.assertIsNone(self.lua.globals().EagleCameraDiagnostics)

    def test_shutdown_does_not_overwrite_later_wrappers(self):
        self.lua.execute(self.source)
        self.lua.execute("""
            diagnostic_shutdown=shutdown
            later=function() return 99 end
            update=later; shutdown=later
            diagnostic_shutdown()
            assert(update==later and shutdown==later)
        """)


if __name__ == "__main__":
    unittest.main()
