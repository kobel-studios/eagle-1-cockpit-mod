"""Offline BSL entry integration tests: our core/service/adapter + mocked Runtime."""
from pathlib import Path
import sys
import unittest


class EagleEntryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(self.root / "test_runtime"))
        sys.path.insert(0, str(self.root / "runtime_adapter"))
        from lupa.lua51 import LuaRuntime
        from test_adapter import MOCKS
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        for name, filename in (
            ("Adapter", "runtime_adapter/eagle_runtime_adapter.lua"),
            ("Payload", "eagle_payload.lua"),
            ("Service", "eagle_service_point.lua"),
            ("Scope", "eagle_camera_scope.lua"),
        ):
            self.lua.globals()[name] = self.lua.execute((self.root / filename).read_text())
        self.lua.execute(MOCKS)
        self.lua.execute(r"""
            VehicleFlight=flight
            original_vehicle=flight.vehicle
            epoch=1; tracked=true; focused=true; menu=false; cursor_available=true
            mission_state={mission=true,host=true}
            logs={}; bindings={}; frames={}; overlays=0
            camera_ini="[camera]\ndistance=100\n[vehicles]\nenabled=0\ndistance=100\n[first_person]\nenabled=0\neye_height=120\neye_forward=0\n"
            camera_original=camera_ini; camera_writes=0
            Scope.load=function(options)
                return Scope.new({
                    read=function() return camera_ini end,
                    write=function(expected,replacement)
                        assert(camera_ini==expected)
                        camera_ini=replacement; camera_writes=camera_writes+1
                        return true
                    end,
                    log=options.log
                })
            end
            player.position=function() return {x=10,y=20,z=30} end
            deps.hd2.game_state=function() return mission_state end
            deps.hd2.input={focused=function() return focused end}
            deps.hd2.events={
                mission_id=function() return epoch,tracked end,
                run_as=function(owner,fn)
                    assert(owner=="mods/jacks/eagle_payload"); scoped=true
                    local result=fn(); scoped=false; return result
                end
            }
            mod={
                bind=function(self,id,spec)
                    assert(scoped and spec.native.label and spec.native.category)
                    bindings[id]=spec
                    return {state="active"}
                end,
                on_frame=function(self,callback,opts)
                    assert(scoped and opts.scope=="session")
                    frames[#frames+1]=callback
                    return {state="active"}
                end,
                log=function(self,text) logs[#logs+1]=text end,
            }
            deps.hd2.mod=function(owner) assert(scoped); return mod end
            deps.hd2.ui={
                cursor=function()
                    if not cursor_available then return nil end
                    return {game_menu=menu,show_cursor=menu,held=false,mouse_focus=true}
                end,
                settings_open=function() return false end,
                overlay=function()
                    overlays=overlays+1
                    return {draw=function(self,fn) draw=fn end}
                end
            }
            -- The seat driver says whether the local player still holds the
            -- control-seat role while flight mode is off. Idle = truly on foot.
            SoloVehicleDriver=SoloVehicleDriver
                or {status="role_overlay_held_by_game_state"}
            -- The service Pelican is decorative: record calls, stay "pending".
            if deps.pelican==nil then
                deps.pelican={spawn=function(opts)
                    calls.pelican=(calls.pelican or 0)+1
                    return {status="pending",
                        alive=function() return pelican_gone~=true end,
                        describe=function() return {status="pending"} end}
                end}
            end
            -- Whichever shared mock is active, always expose the spawn opts.
            local _pelican_spawn=deps.pelican.spawn
            deps.pelican.spawn=function(opts)
                pelican_opts=opts
                return _pelican_spawn(opts)
            end
            require=function(name)
                local modules={
                    ["mods/skyeshade/hd2runtime"]=deps.hd2,
                    ["hd2runtime/api/hd2"]=deps.hd2,
                    ["hd2runtime/api/actions"]=deps.actions,
                    ["hd2runtime/api/pelican"]=deps.pelican,
                    ["hd2runtime/runtime/event_world"]=deps.world,
                    ["hd2runtime/runtime/custom_projectiles"]=deps.custom,
                    ["mods/jacks/eagle_runtime_adapter"]=Adapter,
                    ["mods/jacks/eagle_payload_core"]=Payload,
                    ["mods/jacks/eagle_service_point"]=Service,
                    ["mods/jacks/eagle_camera_scope"]=Scope,
                }
                return assert(modules[name], "forbidden real require: "..name)
            end
            function step(dt,n)
                for i=1,(n or 1) do
                    flight.frames=flight.frames+1
                    for _,fn in ipairs(frames) do fn(dt or 0.1) end
                end
            end
            function press(id) bindings["jacks_eagle."..id].on_press() end
            function release(id) bindings["jacks_eagle."..id].on_release() end
            function tap(id) press(id); step(); release(id); step() end
            function seated(flying)
                SoloVehicleDriver.status="role_overlay_held_by_game_state"
                if flying then
                    flight.vehicle=original_vehicle
                else
                    -- Landed but still in the seat: VFC stops naming the
                    -- vehicle; the seat driver still reports the held role.
                    flight.vehicle="-"
                end
                flight.flying=flying
                step(0.1,4)
            end
            function onfoot()
                SoloVehicleDriver.status="no_target:idle"
                flight.vehicle="-"; flight.flying=false
                step(0.1,4)
            end
        """)

    def load(self):
        self.lua.globals().entry = self.lua.execute(
            (self.root / "eagle_payload_entry.lua").read_text()
        )

    def check(self, source):
        self.lua.execute(source)

    def test_two_bombs_one_per_press_held_does_not_repeat(self):
        self.load()
        self.check("""
            seated(true)
            press("drop"); step(0.1,20)
            assert(calls.spawn==1 and entry.payload.ammo==1)
            release("drop"); step()
            tap("drop")
            assert(calls.spawn==2 and entry.payload.ammo==0)
            step(0.1,12); tap("drop")
            assert(calls.spawn==2)
            assert(bindings["jacks_eagle.drop"].key=="B")
            assert(bindings["jacks_eagle.rearm"].key=="HOME")
            assert(bindings["jacks_eagle.select"].key=="X")
        """)

    def test_initial_held_key_is_ignored(self):
        self.load()
        self.check("""
            press("drop"); seated(true); step(0.1,20)
            assert(calls.spawn==0)
            release("drop"); step(); tap("drop")
            assert(calls.spawn==1)
        """)

    def test_camera_only_activates_in_verified_cockpit_and_restores_on_exit(self):
        self.load()
        self.check("""
            assert(camera_ini==camera_original)
            onfoot()
            assert(camera_ini==camera_original)
            seated(true)
            assert(entry.camera.active and camera_ini:find("distance=25",1,true))
            seated(false)
            assert(entry.camera.active)
            onfoot()
            step(0.1, 8)  -- ride out the camera hold before restore is expected
            assert(not entry.camera.active and camera_ini==camera_original)
            flight.vehicle=original_vehicle:gsub("role=4","role=1")
            flight.flying=true; step(0.1,5)
            assert(camera_ini==camera_original)
        """)

    def test_shutdown_restores_camera_and_preserves_previous_callback(self):
        self.check('shutdown=function(a,b) old_shutdown_called=true;return a,nil,b end')
        self.load()
        self.check("""
            seated(true); assert(entry.camera.active)
            local a,b,c=shutdown(3,4)
            assert(old_shutdown_called and a==3 and b==nil and c==4)
            assert(entry.disabled and camera_ini==camera_original)
        """)

    def test_hud_hidden_outside_mission_and_shows_readable_ammo(self):
        self.load()
        self.check("""
            drawn={}
            painter={scale=1,rect=function() end,
                text=function(self,text) drawn[#drawn+1]=text end}
            mission_state.mission=false; step(); draw(painter)
            assert(#drawn==0)
            mission_state.mission=true; seated(true); draw(painter)
            assert(drawn[1]=="EAGLE | 500 KG  2 / 2")
            assert(drawn[2]=="X: WEAPON    B: FIRE    HOME: REARM")
            drawn={}; onfoot(); draw(painter)
            assert(#drawn==0)
        """)

    def test_landed_rearm_run_refills_every_weapon(self):
        self.load()
        self.check("""
            seated(true); tap("drop"); step(0.1,12); tap("drop")
            assert(entry.payload.ammo==0)
            seated(false); tap("rearm")
            assert(entry.payload.rearming)
            step(0.1,300)
            assert(entry.payload.ammo==0)
            step(0.1,400)
            assert(entry.payload.ammo==2 and not entry.payload.rearming)
            for _,w in ipairs(entry.payload.weapons) do
                assert(w.ammo==w.capacity)
            end
            assert(calls.spawn==2)
        """)

    def test_takeoff_cancels_rearm_run(self):
        self.load()
        self.check("""
            seated(true); tap("drop")
            assert(entry.payload.ammo==1)
            seated(false); tap("rearm")
            assert(entry.payload.rearming)
            seated(true)
            assert(not entry.payload.rearming and entry.payload.ammo==1)
        """)

    def test_fire_safed_and_ground_motion_no_longer_cancels(self):
        self.load()
        self.check("""
            seated(true); tap("drop")       -- spend one bomb so rearm applies
            assert(entry.payload.ammo==1)
            seated(false); tap("rearm")
            assert(entry.payload.rearming and entry.payload.firing_locked)
            press("drop"); step()           -- fire during service: safed
            assert(calls.spawn==1)
            assert(entry.payload.status=="weapons safe during rearm")
            assert(entry.payload.rearming)
            release("drop"); step()
            -- Drive around: the Pelican keeps serving instead of cancelling.
            player.position=function() return {x=80,y=20,z=30} end
            step(0.1,5)
            player.position=function() return {x=10,y=20,z=30} end
            assert(entry.payload.rearming, entry.payload.status)
            step(0.1,700)
            assert(entry.payload.status=="rearmed"
                and entry.payload.ammo==entry.payload.capacity)
            seated(true); tap("drop")
            assert(calls.spawn==2)          -- firing works again after
        """)

    def test_rearm_continues_and_starts_while_out_of_vehicle(self):
        self.load()
        self.check("""
            seated(true); tap("drop")       -- spend one bomb so rearm applies
            seated(false); tap("rearm")
            assert(entry.payload.rearming)
            onfoot()                        -- leave mid-run: it keeps going
            assert(entry.payload.rearming, entry.payload.status)
            step(0.1,700)
            assert(entry.payload.status=="rearmed"
                and entry.payload.ammo==entry.payload.capacity)
            -- Spend one more, get out, and a Home press on foot re-arms too.
            seated(true); tap("drop")
            assert(entry.payload.ammo==1)
            seated(false); onfoot()
            tap("drop")                     -- still cannot fire on foot
            assert(calls.spawn==2)
            tap("rearm")
            assert(entry.payload.rearming)
            step(0.1,10)
            seated(false)
            assert(entry.payload.rearming)
        """)

    def test_flight_off_cannot_drop_and_onfoot_cannot_spawn(self):
        self.load()
        self.check("""
            seated(false); tap("drop"); step(0.1,20)
            assert(calls.spawn==0)
            onfoot(); tap("drop")
            assert(calls.spawn==0 and calls.define==0)
        """)

    def test_exit_seat_changes_read_failure_do_not_refill(self):
        self.load()
        self.check("""
            seated(true); tap("drop"); assert(entry.payload.ammo==1)
            onfoot()
            mission_state=nil; step(0.1,5)
            mission_state={mission=true,host=true}
            seated(true); assert(entry.payload.ammo==1 and entry.count==1)
            flight.vehicle=flight.vehicle:gsub("seat=0xABC","seat=0xDEF")
            step(0.1,4)
            assert(entry.payload.ammo==1 and entry.count==1)
        """)

    def test_real_mission_epoch_change_resets_counters(self):
        self.load()
        self.check("""
            seated(true); tap("drop")
            assert(entry.payload.ammo==1)
            epoch=3; step(0.1,4)
            assert(entry.payload.ammo==2 and entry.count==1)
        """)

    def test_wrong_runtime_never_registers_or_spawns(self):
        self.check('deps.hd2.version="0.41.0"')
        self.load()
        self.check("assert(entry.disabled and #frames==0 and next(bindings)==nil and calls.spawn==0)")

    def test_menu_focus_zero_dt_and_frame_gap_block_press(self):
        self.load()
        self.check("""
            seated(true)
            menu=true; tap("drop"); menu=false; step(0.1,4)
            focused=false; tap("drop"); focused=true; step(0.1,4)
            press("drop"); step(0); release("drop"); step()
            press("drop"); step(2); release("drop"); step(0.1,4)
            cursor_available=false; tap("drop"); cursor_available=true; step(0.1,4)
            assert(calls.spawn==0)
            tap("drop"); assert(calls.spawn==1)
        """)

    def test_gap_cancels_rearm_without_refill(self):
        self.load()
        self.check("""
            seated(true); tap("drop")
            seated(false); tap("rearm")
            assert(entry.payload.rearming)
            step(2); step(0.1,4)
            assert(not entry.payload.rearming and entry.payload.ammo==1)
        """)

    def test_queued_assets_cancel_no_delayed_bomb(self):
        self.load()
        self.check("""
            seated(true); status="waiting_for_assets"; tap("drop")
            assert(calls.cancel==1 and entry.payload.ammo==2)
            onfoot(); drain_mock_scheduler()
            assert(calls.native==0)
        """)

    def test_uncertainty_survives_exit_and_chunk_reload(self):
        self.load()
        self.check("""
            seated(true); status="mystery"; tap("drop")
            assert(entry.payload.faulted)
            onfoot(); seated(true); tap("drop")
            assert(calls.spawn==1 and entry.adapter.is_faulted())
        """)
        self.load()
        self.check("assert(#frames==1 and entry.adapter.is_faulted() and calls.spawn==1)")

    def test_maximum_controller_limit_refuses_new_vehicle(self):
        self.load()
        self.check("""
            seated(true)
            local inspect=entry.adapter.inspect_vehicle
            entry.adapter.inspect_vehicle=function(now)
                local value=inspect(now)
                if value then value.vehicle_key="999:00000222" end
                return value
            end
            entry.count=128
            tap("drop")
            assert(calls.spawn==0 and entry.count==128)
        """)

    def test_hud_failure_leaves_logs_and_payload_functional(self):
        self.check('deps.hd2.ui.overlay=function() error("HUD unavailable") end')
        self.load()
        self.check("seated(true); tap('drop'); assert(calls.spawn==1 and #logs>0 and not entry.disabled)")

    def test_select_cycles_seven_weapons_and_held_does_not_repeat(self):
        self.load()
        self.check("""
            seated(true)
            assert(entry.payload.selected==1 and entry.payload.selected_name=="500 KG")
            tap("select")
            assert(entry.payload.selected==2 and entry.payload.selected_name=="AIRSTRIKE")
            press("select"); step(0.1,10); release("select"); step()
            assert(entry.payload.selected==3)
            for i=1,5 do tap("select") end
            assert(entry.payload.selected==1)
        """)

    def test_number_keys_jump_to_each_weapon(self):
        self.load()
        self.check("""
            for i=1,7 do
                assert(bindings["jacks_eagle.w"..i].key==tostring(i))
            end
            seated(true)
            tap("w4")
            assert(entry.payload.selected==4 and entry.payload.selected_name=="NAPALM")
            tap("w1")
            assert(entry.payload.selected==1 and entry.payload.selected_name=="500 KG")
            tap("w1")
            assert(entry.payload.selected==1)
        """)

    def test_fire_uses_the_selected_weapon(self):
        self.load()
        self.check("""
            seated(true)
            tap("select"); tap("select"); tap("select")
            assert(entry.payload.selected_name=="NAPALM")
            local defined
            deps.custom.define=function(spec)
                calls.define=calls.define+1; defined=spec.id
                return {id=spec.id}
            end
            deps.actions.spawn_custom_projectile=function(def,opts)
                calls.spawn=calls.spawn+1
                assert(def.id=="jacks/eagle_napalm")
                return {status="requested"}
            end
            tap("drop")
            assert(calls.define==1 and calls.spawn==1 and defined=="jacks/eagle_napalm")
            assert(entry.payload.ammo==2)
        """)

    def test_landed_seated_keeps_hud_and_camera(self):
        self.load()
        self.check("""
            seated(true)
            seated(false)
            assert(entry.hud_visible and entry.camera.active)
            drawn={}
            painter={scale=1,rect=function() end,
                text=function(self,text) drawn[#drawn+1]=text end}
            draw(painter)
            assert(drawn[1]=="EAGLE | 500 KG  2 / 2")
            onfoot()
            assert(not entry.hud_visible)
        """)

    def test_rearm_summons_service_pelican_and_shows_stage(self):
        self.load()
        self.check("""
            seated(true); tap("drop")
            seated(false); tap("rearm")
            assert(entry.payload.rearming)
            assert(calls.pelican==1)
            assert(pelican_opts.hover==15)
            assert(type(pelican_opts.position)=="table")
            entry.pelican.status="hovering"; step()
            drawn={}
            painter={scale=1,rect=function() end,
                text=function(self,text) drawn[#drawn+1]=text end}
            draw(painter)
            assert(drawn[2]:find("REARM RUN",1,true))
            assert(drawn[2]:find("PELICAN ON STATION",1,true))
        """)

    def test_pelican_refusal_still_rearms_without_fault(self):
        self.load()
        self.check("""
            deps.pelican.spawn=function()
                calls.pelican=(calls.pelican or 0)+1
                return {status="refused",code="X",
                    alive=function() return false end}
            end
            seated(true); tap("drop")
            seated(false); tap("rearm")
            assert(entry.payload.rearming and calls.pelican==1)
            step(0.1,650)
            assert(entry.payload.ammo==2 and not entry.payload.rearming)
            assert(not entry.adapter.is_faulted())
        """)

    def test_pelican_not_respawned_while_one_is_alive(self):
        self.load()
        self.check("""
            seated(true); tap("drop")
            seated(false); tap("rearm"); step(0.1,650)
            assert(calls.pelican==1 and entry.payload.ammo==2)
            tap("drop"); seated(true); tap("drop") -- spend another bomb
            seated(false); tap("rearm")
            assert(calls.pelican==1) -- old service bird still on station
        """)


if __name__ == "__main__":
    unittest.main()
