"""Actual Lua 5.1 controller with in-memory INI only; never open the live INI."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "test_runtime"))
from lupa.lua51 import LuaRuntime


INI = (
    "; Saved changes are picked up in game.\r\n"
    "[camera]\r\n"
    "enabled = 1 ; leave alone\r\n"
    "distance         = 100    ; zoom\r\n"
    "fov = 103\r\n"
    "[vehicles]\r\n"
    "enabled          = 0      ; keep generic seats OFF\r\n"
    "distance = 100\r\n"
    "[first_person]\r\n"
    "enabled = 0 ; threshold mode\r\n"
    "below = 30\r\n"
    "eye_height = 120\r\n"
    "eye_forward = 0\r\n"
    "[seat_distance]\r\n"
    "57 = 333 ; not owned"
)


class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(register_eval=False, register_builtins=False,
                              unpack_returned_tuples=True)
        self.g = self.lua.globals()
        self.g.Scope = self.lua.execute((ROOT / "eagle_camera_scope.lua").read_text())
        self.g.initial = INI
        self.lua.execute("""
            text=initial; writes=0; reads=0; logs={}
            deps={
                read=function() reads=reads+1; return text end,
                write=function(expected, replacement)
                    writes=writes+1
                    if race then text=text..'\\r\\n; user edit'; race=false end
                    if throw_write then error('disk error') end
                    if deny then return false, 'permission denied' end
                    if text~=expected then return false, 'concurrent edit' end
                    text=replacement
                    if throw_after_commit then error('uncertain commit') end
                    return true
                end,
                log=function(message) logs[#logs+1]=message end,
            }
            function seat()
                return {authority=true, alive=true, entity=123, unit=456,
                    vehicle_key='123:000001C8', role=4, flying=false,
                    frames=20, now=1.5}
            end
            scope=Scope.new(deps)
        """)

    def test_initial_normal_and_onfoot_never_enables_first_person(self):
        self.assertEqual(self.g.reads, 1)
        self.assertEqual(self.g.writes, 0)
        for snapshot in (None, True, False, self.lua.table_from({})):
            self.assertTrue(self.g.scope.update(snapshot)[0])
        self.assertEqual(self.g.text, INI)
        self.assertEqual(self.g.reads, 1)

    def test_startup_forces_normal_even_if_old_global_first_person_was_on(self):
        self.lua.execute("""
            text=text:gsub('= 100', '= 25'):gsub('(enabled%s*= )0', '%11')
            original=text
            scope=Scope.new(deps)
        """)
        self.assertEqual(self.g.text, INI)
        self.assertEqual(self.g.scope.original, self.g.original)
        self.assertEqual(self.g.writes, 1)

    def test_valid_seat_works_with_flight_mode_on_or_off_and_exit_restores(self):
        for flying in (False, True):
            with self.subTest(flying=flying):
                snapshot = self.g.seat()
                snapshot.flying = flying
                self.assertTrue(self.g.scope.update(snapshot)[0])
                self.assertTrue(self.g.scope.active)
                expected = INI.replace("= 100    ; zoom", "= 25    ; zoom").replace(
                    "enabled = 0 ; threshold", "enabled = 1 ; threshold").replace(
                    "eye_height = 120", "eye_height = 115").replace(
                    "eye_forward = 0", "eye_forward = 60")
                self.assertEqual(self.g.text, expected)
                self.assertTrue(self.g.scope.update(None)[0])
                self.assertEqual(self.g.text, INI)

    def test_missing_source_fields_and_wrong_role_or_identity_fail_closed(self):
        for key in ("authority", "alive", "entity", "unit", "vehicle_key",
                    "role", "flying", "frames", "now"):
            with self.subTest(missing=key):
                self.g.scope.update(self.g.seat())
                snapshot = self.g.seat()
                snapshot[key] = None
                self.g.scope.update(snapshot)
                self.assertEqual(self.g.text, INI)
        for key, value in (("authority", 1), ("alive", False), ("role", 3),
                           ("unit", 0), ("entity", 1.5), ("vehicle_key", "other"),
                           ("flying", 1), ("frames", 0), ("now", float("nan"))):
            with self.subTest(key=key, value=value):
                snapshot = self.g.seat()
                snapshot[key] = value
                self.g.scope.update(snapshot)
                self.assertEqual(self.g.text, INI)
        self.g.scope.update(self.lua.table_from(
            {"flying": True, "tmpl": 26, "vehicle": "e=123", "frames": 21}))
        self.assertEqual(self.g.text, INI)

    def test_invalid_ticks_within_hold_do_not_rewrite_or_bounce(self):
        # A one-tick telemetry blip must not drop the camera out of first
        # person; the hold only applies while the caller supplies a clock.
        self.lua.execute("scope=Scope.new(deps)")
        self.g.scope.update(self.g.seat(), 10.0)
        self.assertTrue(self.g.scope.active)
        before = (self.g.reads, self.g.writes)
        active_ini = self.g.text
        # Blips inside the 0.6 s hold keep the active INI untouched.
        for t in (10.1, 10.2, 10.4, 10.59):
            self.assertTrue(self.g.scope.update(None, t)[0])
            self.assertTrue(self.g.scope.active)
        self.assertEqual((self.g.reads, self.g.writes), before)
        self.assertEqual(self.g.text, active_ini)
        # Past the hold the normal camera is restored exactly once.
        self.assertTrue(self.g.scope.update(None, 10.7)[0])
        self.assertEqual(self.g.text, INI)
        for _ in range(20):
            self.g.scope.update(None, 20.0)
        self.assertEqual(self.g.writes, before[1] + 1)

    def test_hold_needs_clock_and_resets_on_each_valid_snapshot(self):
        self.lua.execute("scope=Scope.new(deps)")
        # No clock argument: invalid updates still restore immediately.
        self.g.scope.update(self.g.seat())
        self.assertTrue(self.g.scope.update(None)[0])
        self.assertEqual(self.g.text, INI)
        # With a clock, each valid snapshot restarts the hold window.
        self.g.scope.update(self.g.seat(), 5.0)
        self.g.scope.update(None, 5.5)          # 0.5s in: still held
        self.assertTrue(self.g.scope.active)
        self.g.scope.update(self.g.seat(), 5.9)  # valid again: window resets
        self.g.scope.update(None, 6.3)          # 0.4s in: still held
        self.assertTrue(self.g.scope.active)
        self.g.scope.update(None, 6.6)          # 0.7s past last valid: restore
        self.assertEqual(self.g.text, INI)

    def test_hold_seconds_option_is_validated(self):
        for bad in (-1, 2.5, float("nan"), "x"):
            with self.subTest(bad=bad):
                self.g.bad = bad
                self.lua.execute("s, r = Scope.new(deps, {hold_seconds=bad})")
                self.assertIsNone(self.g.s)
                self.assertIsNotNone(self.g.r)
        self.lua.execute("s=Scope.new(deps,{hold_seconds=0})")
        self.g.s.update(self.g.seat(), 1.0)
        self.assertTrue(self.g.s.update(None, 1.01)[0])
        self.assertEqual(self.g.text, INI)

    def test_repeated_ticks_never_poll_or_write_disk(self):
        self.g.scope.update(self.g.seat())
        before = (self.g.reads, self.g.writes)
        for _ in range(500):
            self.g.scope.update(self.g.seat())
        self.assertEqual((self.g.reads, self.g.writes), before)
        self.g.scope.update(None)
        before = (self.g.reads, self.g.writes)
        for _ in range(500):
            self.g.scope.update(None)
        self.assertEqual((self.g.reads, self.g.writes), before)

    def test_unrelated_user_changes_survive_exit(self):
        self.g.scope.update(self.g.seat())
        self.g.text = self.g.text.replace("fov = 103", "fov = 117") + "\r\n; new user setting"
        self.g.scope.update(None)
        self.assertEqual(self.g.text, INI.replace("fov = 103", "fov = 117")
                         + "\r\n; new user setting")

    def test_compare_and_swap_rejects_concurrent_edit_and_blocks_activation(self):
        self.g.race = True
        ok, reason = self.g.scope.update(self.g.seat())
        self.assertFalse(ok)
        self.assertIn("concurrent edit", reason)
        self.assertTrue(self.g.scope.faulted)
        self.assertEqual(self.g.text, INI + "\r\n; user edit")
        self.g.scope.update(self.g.seat())  # Cleanup only, not reactivation.
        self.assertFalse(self.g.scope.active)
        self.assertEqual(self.g.text, INI + "\r\n; user edit")

    def test_stop_resets_owned_values_without_clobbering_manual_edit(self):
        self.g.scope.update(self.g.seat())
        self.g.text = self.g.text.replace("= 25    ; zoom", "= 250    ; zoom")
        ok, reason = self.g.scope.stop()
        self.assertFalse(ok)
        self.assertIn("manual", reason)
        self.assertEqual(self.g.text, INI.replace("= 100    ; zoom", "= 250    ; zoom"))
        before = (self.g.reads, self.g.writes)
        self.g.scope.stop()
        self.g.scope.update(self.g.seat())
        self.assertEqual((self.g.reads, self.g.writes), before)

    def test_stop_is_idempotent_and_prevents_reactivation(self):
        self.g.scope.update(self.g.seat())
        self.assertTrue(self.g.scope.stop()[0])
        self.assertEqual(self.g.text, INI)
        before = (self.g.reads, self.g.writes)
        self.assertTrue(self.g.scope.stop()[0])
        self.assertFalse(self.g.scope.update(self.g.seat())[0])
        self.assertEqual((self.g.reads, self.g.writes), before)

    def test_failed_exit_reports_possible_active_state_and_caps_retries(self):
        self.g.scope.update(self.g.seat())
        self.g.deny = True
        self.assertFalse(self.g.scope.update(None)[0])
        self.assertIsNone(self.g.scope.active)
        for _ in range(50):
            self.g.scope.update(None)
        self.assertEqual(self.g.writes, 4)  # Activate, three failed cleanup attempts.
        self.assertIn("first person may remain active", self.g.scope.status)
        self.assertIn("retry limit", self.g.scope.status)
        self.assertFalse(self.g.scope.stop()[0])
        self.assertEqual(self.g.writes, 4)

    def test_stop_can_retry_failed_cleanup_and_write_exceptions_are_contained(self):
        self.g.scope.update(self.g.seat())
        self.g.throw_write = True
        self.assertFalse(self.g.scope.stop()[0])
        self.g.throw_write = False
        self.assertTrue(self.g.scope.stop()[0])
        self.assertEqual(self.g.text, INI)

    def test_exception_after_commit_is_cleaned_up_not_treated_as_manual_edit(self):
        self.g.throw_after_commit = True
        self.assertFalse(self.g.scope.update(self.g.seat())[0])
        self.g.throw_after_commit = False
        self.assertTrue(self.g.scope.update(None)[0])
        self.assertEqual(self.g.text, INI)
        self.assertFalse(self.g.scope.active)

    def test_uncertain_commit_ownership_survives_another_failed_cleanup(self):
        for flag in ("deny", "throw_write"):
            with self.subTest(flag=flag):
                self.setUp()
                self.g.throw_after_commit = True
                self.assertFalse(self.g.scope.update(self.g.seat())[0])
                self.g.throw_after_commit = False
                self.g[flag] = True
                self.assertFalse(self.g.scope.update(None)[0])
                self.g[flag] = False
                self.assertTrue(self.g.scope.update(None)[0])
                self.assertEqual(self.g.text, INI)

    def test_missing_ambiguous_or_malformed_ini_is_not_written(self):
        for text in ("", "[camera]\ndistance=100", INI + "\r\n[camera]\ndistance=100",
                     INI.replace("fov = 103", "distance = 90"),
                     INI.replace("[camera]", "[camera]garbage"),
                     INI.replace("distance = 100", "distance = nonsense"),
                     INI.replace("distance = 100", "distance = 100junk")):
            with self.subTest(text=text):
                self.g.text = text
                self.lua.execute("scope=Scope.new(deps)")
                self.assertTrue(self.g.scope.faulted)
                self.assertEqual(self.g.writes, 0)
                self.assertEqual(self.g.text, text)

    def test_bom_lf_no_final_newline_and_comments_are_preserved(self):
        self.g.text = "\ufeff" + INI.replace("\r\n", "\n")
        self.lua.execute("scope=Scope.new(deps)")
        self.g.scope.update(self.g.seat())
        self.g.scope.stop()
        self.assertEqual(self.g.text, "\ufeff" + INI.replace("\r\n", "\n"))

    def mock_filesystem(self):
        # No real io/os operation can run: load gets a complete Lua fake filesystem.
        self.lua.execute("""
            path='MOCK/CowboyBingus/Helldivers2/Logs/AdvancedTankCamera.ini'
            files={[path]=initial}; renames=0; removed=0
            io={open=function(name, mode)
                assert(name==path or name:find('/.eagle%-camera%-scope.'))
                if mode=='rb' then
                    if not files[name] then return nil, 'not found' end
                    return {read=function() return files[name] end,
                            close=function() return true end}
                end
                assert(mode=='wb' and name~=path)
                return {write=function(_, bytes)
                            if fail_staging and name:sub(-4)=='.tmp' then
                                return nil, 'disk full'
                            end
                            files[name]=bytes
                            if race_after_stage and name:sub(-4)=='.tmp' then
                                files[path]=files[path]..'\\r\\n; racing user edit'
                            end
                            return true
                        end,
                        close=function() return true end}
            end}
            os={getenv=function(name) assert(name=='LOCALAPPDATA'); return 'MOCK' end,
                time=function() return 123 end,
                rename=function(a,b)
                    assert(b==path and files[path] and files[a])
                    if fail_rename then return nil, 'rename denied' end
                    files[b]=files[a]; files[a]=nil; renames=renames+1; return true
                end,
                remove=function(name)
                    assert(name~=path); removed=removed+1; files[name]=nil; return true
                end}
            package.config='/\\n'
        """)

    def test_load_uses_only_fixed_config_and_own_sidecars_with_atomic_replace(self):
        self.mock_filesystem()
        self.lua.execute("""
            loaded=Scope.load()
            assert(loaded and loaded.path==path)
            assert(renames==0)
            assert(loaded.update(seat()))
            assert(files[loaded.backup_path]==initial)
            assert(renames==1)
            assert(loaded.stop())
            assert(files[path]==initial and renames==2)
            assert(files[loaded.backup_path]==initial)
        """)

    def test_production_second_read_detects_concurrent_edit_and_removes_staging(self):
        self.mock_filesystem()
        self.lua.execute("""
            loaded=Scope.load()
            race_after_stage=true
            local ok, reason=loaded.update(seat())
            assert(not ok and reason:find('concurrent INI edit before replacement'))
            assert(files[path]==initial..'\\r\\n; racing user edit')
            assert(renames==0 and removed==1)
            assert(files[loaded.backup_path]==initial)
        """)

    def test_production_staging_or_replace_failure_never_deletes_live_ini(self):
        for flag in ("fail_staging", "fail_rename"):
            with self.subTest(flag=flag):
                self.setUp()
                self.mock_filesystem()
                self.g[flag] = True
                self.lua.execute("""
                    loaded=Scope.load()
                    assert(not loaded.update(seat()))
                    assert(files[path]==initial and renames==0 and removed==1)
                """)

    def test_production_missing_file_is_not_created(self):
        self.mock_filesystem()
        self.lua.execute("""
            files[path]=nil
            local loaded, reason=Scope.load()
            assert(not loaded and reason)
            assert(next(files)==nil)
        """)

    def test_production_load_exceptions_return_a_reason_not_a_game_callback_error(self):
        self.mock_filesystem()
        self.lua.execute("""
            io.open=function() error('filesystem denied') end
            local loaded, reason=Scope.load()
            assert(not loaded and reason:find('filesystem denied'))
            assert(files[path]==initial and renames==0 and removed==0)
        """)

    def test_windows_uses_documented_filesystem_replace_not_crt_rename(self):
        self.mock_filesystem()
        self.lua.execute("""
            package.config='\\\\\\n'
            package.loaded.ffi={
                cdef=function(declaration)
                    assert(declaration:find('MoveFileExA'))
                end,
                load=function(name)
                    assert(name=='kernel32')
                    return {
                        eagle_camera_scope_v1_MoveFileExA=function(a,b,flags)
                            assert(flags==9 and b==path)
                            files[b]=files[a]; files[a]=nil
                            renames=renames+1
                            return 1
                        end,
                        eagle_camera_scope_v1_GetLastError=function() return 5 end,
                    }
                end,
            }
            os.rename=function() error('must not use CRT rename on Windows') end
            loaded=Scope.load()
            assert(loaded.update(seat()))
            assert(loaded.stop())
            assert(renames==2 and files[path]==initial)
        """)

    def test_windows_without_atomic_file_api_refuses_load_without_writing(self):
        self.mock_filesystem()
        self.lua.execute("""
            package.config='\\\\\\n'
            package.loaded.ffi=nil
            package.preload.ffi=function() error('FFI unavailable') end
            local loaded, reason=Scope.load()
            assert(not loaded and reason:find('atomic Windows file replacement'))
            assert(files[path]==initial and renames==0 and removed==0)
        """)


if __name__ == "__main__":
    unittest.main()
