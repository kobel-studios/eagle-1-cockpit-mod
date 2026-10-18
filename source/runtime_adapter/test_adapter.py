"""Offline Lua 5.1 tests. Execute only our adapter and injected mock functions.

Never load HD2Runtime Lua, any SDK builder, native memory API, or game process.
Run from HQ: python -m unittest discover -s downloads/hd2-mods/runtime_adapter -v
"""
from pathlib import Path
import sys
import unittest


MOCKS = r"""
require = function(name) error("real dependency loading forbidden: " .. name) end
calls = {spawn=0, define=0, assets=0, cancel=0, native=0, open=0, pelican=0}
flight = {
    rev="vehicle-flight-1.0.1", flying=true, frames=10, tmpl=26,
    vehicle="e=123 u=0x1AB actor=0xB0C9FAF4AF8903F9 seat=0xABC role=4"
}
world = {view={slot=function() return {} end}}
avatar_pos = {x=12, y=21, z=29}
scan_descriptors = {{type="B0C9FAF4AF8903F9", entity=123, unit=0x1AB}}
scan_units = {[0x1AB]={x=10, y=20, z=30}}
health_records = true
SoloVehicleDriver = {status="role_overlay_held_by_game_state"}
player = {
    is_local_player=function() return true end,
    is_alive=function() return true end,
    avatar=function()
        return {is_alive=function() return true end,
            is_downed=function() return false end,
            position=function() return avatar_pos end}
    end
}
deps = {
    read_flight=function() return flight end,
    hd2={
        version="0.40.0", api_version=1,
        build=function() return "matched" end,
        game_state=function() return {mission=true, host=true} end,
        local_player=function() return player end,
        stratagem=function(name)
            local known={["Eagle 500kg Bomb"]=true,["Eagle Airstrike"]=true,
                ["Eagle Cluster Bomb"]=true,["Eagle Napalm Airstrike"]=true,
                ["Eagle 110mm Rocket Pods"]=true,["Eagle Gas Airstrike"]=true,
                ["Eagle Smoke Strike"]=true}
            assert(known[name], "unknown stratagem: "..tostring(name))
            return {name=name}
        end,
        require_assets=function(spec)
            calls.assets=calls.assets+1
            assert(spec.id=="eagle-weapon-assets")
            assert(#spec.targets==7)
            for _,target in ipairs(spec.targets) do
                assert(type(target)=="table" and type(target.name)=="string")
            end
            return {status="waiting"}
        end,
    },
    world={
        open=function() calls.open=calls.open+1; return world end,
        entity_exists=function(w,id) assert(w==world and id==123); return true end,
        entity_unit=function(w,id) assert(w==world and id==123); return 0x1AB end,
        entity_type=function(w,id) assert(w==world and id==123); return "B0C9FAF4AF8903F9" end,
        unit_pose=function(w,unit)
            assert(w==world and unit==0x1AB)
            return {position={x=10,y=20,z=30},forward={x=0,y=1,z=0},
                up={x=0,y=0,z=-1}}
        end,
        health_header=function(w,slot)
            assert(w==world)
            if not health_records then return nil end
            return {live=#scan_descriptors, descriptors=1, records=1}
        end,
        descriptor=function(w,h,i)
            assert(w==world)
            calls.scan=(calls.scan or 0)+1
            return scan_descriptors[i+1]
        end,
        unit_position=function(w,u)
            assert(w==world)
            return scan_units[u]
        end,
    },
    custom={
        define=function(spec)
            calls.define=calls.define+1
            last_spec=spec
            assert(type(spec.id)=="string" and spec.id:sub(1,12)=="jacks/eagle_")
            assert(type(spec.base)=="string" and #spec.base>0)
            if spec.changes~=nil then
                -- Only the launch `speed` member may be borrowed: gravity,
                -- drag, mass, damage and impact must stay native to the base.
                assert(type(spec.changes)=="table" and #spec.changes==1)
                local change=spec.changes[1]
                assert(change.member=="speed"
                    and type(change.from)=="string" and #change.from>0)
            end
            local n=0; for _ in pairs(spec) do n=n+1 end
            assert(n==2 or (n==3 and spec.changes~=nil),
                "only an optional speed-member change may be added")
            return {id=spec.id}
        end,
    },
    actions={},
    pelican={
        spawn=function(opts)
            calls.pelican=calls.pelican+1
            assert(type(opts.position)=="table"
                and opts.position.x==10 and opts.position.y==20
                and opts.position.z==30, "anchor must be the vehicle root")
            assert(opts.owner=="mods/jacks/eagle_payload")
            pelican_opts=opts; captured_opts=opts
            local handle={status="requested"}
            function handle:alive() return self.status~="refused" end
            return handle
        end,
    },
}
status="requested"
pending={}
deps.actions.spawn_custom_projectile=function(def,opts)
    calls.spawn=calls.spawn+1
    assert(type(def)=="table" and type(def.id)=="string"
        and def.id:sub(1,12)=="jacks/eagle_")
    assert(opts.owner=="mods/jacks/eagle_payload")
    assert(opts.position.x==10 and opts.position.y==20 and opts.position.z==26)
    local d=opts.direction
    assert(type(d.x)=="number" and type(d.y)=="number" and type(d.z)=="number"
        and math.abs(d.x*d.x+d.y*d.y+d.z*d.z-1)<0.01,
        "direction must be a unit vector")
    last_direction=d
    last_options=opts
    local action={status=status}
    function action:cancel()
        calls.cancel=calls.cancel+1
        if self.status=="waiting_for_assets" then self.status="cancelled" end
        return self
    end
    if status=="requested" then calls.native=calls.native+1 end
    if status=="waiting_for_assets" then pending[#pending+1]=action end
    return action
end
function drain_mock_scheduler()
    for _,action in ipairs(pending) do
        if action.status=="waiting_for_assets" then
            calls.native=calls.native+1
            action.status="requested"
        end
    end
end
adapter=Adapter.new(deps)
ctx={now=1,vehicle_key="123:000001AB",in_cockpit=true,
    flight_enabled=true,grounded=false,focused=true,paused=false}
function ready()
    assert(adapter.inspect(1)==nil)
    flight.frames=flight.frames+1
    ctx.now=1.01
    local observation,why=adapter.inspect(ctx.now)
    assert(observation,why)
    return observation
end
function park()
    ready()
    flight.flying=false
    flight.vehicle="-"
    flight.frames=flight.frames+1
    ctx.now=ctx.now+0.01
    local observation,why=adapter.inspect_vehicle(ctx.now)
    assert(observation,why)
    assert(observation.flying==false)
    return observation
end
function rejected()
    local value,why=adapter.spawn_bomb(ctx)
    assert(value==false, tostring(value)..": "..tostring(why))
    assert(calls.spawn==0 and calls.native==0)
    return why
end
function unknown()
    local value,why=adapter.spawn_bomb(ctx)
    assert(value==nil, tostring(value)..": "..tostring(why))
    assert(adapter.is_faulted())
    local count=calls.spawn
    assert(adapter.spawn_bomb(ctx)==nil)
    assert(calls.spawn==count, "uncertain action must not retry")
end
"""


class AdapterTests(unittest.TestCase):
    def setUp(self):
        # Existing local Lua wheel only; no dependency install or network access.
        root = Path(__file__).resolve().parent
        sys.path.insert(0, str(root.parent / "test_runtime"))
        from lupa.lua51 import LuaRuntime
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.globals().Adapter = self.lua.execute(
            (root / "eagle_runtime_adapter.lua").read_text(encoding="utf-8")
        )
        self.lua.execute(MOCKS)

    def check(self, code):
        self.lua.execute(code)

    def test_construction_is_inert(self):
        self.check("assert(calls.open==0 and calls.assets==0 and calls.define==0 and calls.spawn==0)")

    def test_requested_is_only_success_and_clone_has_no_changes(self):
        self.check("""
            ready()
            assert(adapter.spawn_bomb(ctx)==true)
            assert(adapter.spawn_bomb(ctx)==true)
            assert(calls.spawn==2 and calls.define==1 and calls.native==2)
            assert(not adapter.is_faulted())
        """)

    def test_parse_exact_format_preserves_opaque_64bit_hex(self):
        self.check("""
            local v=assert(Adapter.parse_vehicle(flight.vehicle))
            assert(v.entity==123 and v.unit==0x1AB and v.role==4)
            assert(v.actor_hex=="B0C9FAF4AF8903F9")
            assert(v.seat_hex=="ABC" and v.vehicle_key=="123:000001AB")
        """)

    def test_parse_invalid_forms(self):
        self.check("""
            for _,s in ipairs({
                "", "-", " e=123 u=0x1AB actor=0x1 seat=0x2 role=4",
                "e=123 u=0x1ab actor=0x1 seat=0x2 role=4",
                "e=0123 u=0x1AB actor=0x1 seat=0x2 role=4",
                "e=123 u=0x01AB actor=0x1 seat=0x2 role=4",
                "e=0 u=0x1AB actor=0x1 seat=0x2 role=4",
                "e=4294967296 u=0x1AB actor=0x1 seat=0x2 role=4",
                "e=123 u=0x100000000 actor=0x1 seat=0x2 role=4",
                "e=123 u=0x1AB actor=0x12345678901234567 seat=0x2 role=4",
                "e=123 u=0x1AB actor=0x1 seat=0x2 role=-1",
                "e=123 u=0x1AB actor=0x1 seat=0x2 role=04",
                "e=123 u=0x1AB actor=0x1 seat=0x2 role=4 trailing"
            }) do assert(Adapter.parse_vehicle(s)==nil,s) end
            assert(Adapter.parse_vehicle({})==nil)
        """)

    def test_runtime_version_and_api_pins(self):
        self.check("""
            ready(); deps.hd2.version="0.40.1"; rejected()
            deps.hd2.version="0.40.0"; deps.hd2.api_version=2; rejected()
            assert(calls.define==0)
        """)

    def test_unknown_build_is_closed_before_world_or_actions(self):
        self.check("""
            deps.hd2.build=function() return "mismatched" end
            rejected()
            assert(calls.open==0 and calls.define==0)
            assert(adapter.prewarm()==nil and calls.assets==0)
            deps.hd2.build=function() return "not_ready" end
            rejected()
        """)

    def test_host_and_mission_required(self):
        self.check("""
            ready()
            deps.hd2.game_state=function() return {host=false,mission=true} end
            rejected()
            deps.hd2.game_state=function() return {host=true,mission=false} end
            rejected()
        """)

    def test_alive_local_player_and_not_downed_required(self):
        for replacement in (
            "deps.hd2.local_player=function() return nil end",
            "player.is_local_player=function() return false end",
            "player.is_alive=function() return false end",
            "player.avatar=function() return nil end",
            """player.avatar=function() return {
                is_alive=function() return true end,is_downed=function() return true end} end""",
        ):
            with self.subTest(replacement=replacement):
                self.setUp()
                self.check("ready(); " + replacement + "; rejected()")

    def test_no_flight_wrong_revision_template_or_role(self):
        for replacement in (
            "flight=nil", "flight.flying=false", "flight.flying=1",
            'flight.rev="vehicle-flight-1.0.2"', "flight.tmpl=25",
            'flight.vehicle=flight.vehicle:gsub("role=4","role=2")',
            'flight.vehicle="-"', "flight.frames=0/0",
        ):
            with self.subTest(replacement=replacement):
                self.setUp()
                self.check("ready(); " + replacement + "; rejected()")

    def test_native_entity_and_unit_revalidation(self):
        for replacement in (
            "deps.world.open=function() return nil,'unavailable' end",
            "deps.world.entity_exists=function() return false end",
            "deps.world.entity_exists=function() return nil end",
            "deps.world.entity_unit=function() return 0x1AC end",
            'deps.world.entity_type=function() return "0000000000000001" end',
            'deps.world.entity_type=function() return {type="B0C9FAF4AF8903F9"} end',
        ):
            with self.subTest(replacement=replacement):
                self.setUp()
                self.check("ready(); " + replacement + "; rejected()")

    def test_lowercase_native_type_string_accepted(self):
        self.check("""
            ready()
            deps.world.entity_type=function() return "b0c9faf4af8903f9" end
            assert(adapter.spawn_bomb(ctx)==true)
        """)

    def test_unreadable_or_nonfinite_pose(self):
        for pose in ("nil", "{}", "{position={x=0,y=0,z=0/0}}",
                     "{position={x=0,y=math.huge,z=0}}",
                     "{position={x=0,y=0,z=-99999}}"):
            with self.subTest(pose=pose):
                self.setUp()
                self.check(f"ready(); deps.world.unit_pose=function() return {pose} end; rejected()")

    def test_release_direction_is_hull_forward_not_world_down(self):
        self.check("""
            local s=ready()
            assert(s.position.z==26 and s.direction.x==0
                and s.direction.y==1 and s.direction.z==0)
            assert(s.grounded==nil and s.in_service_area==nil and s.in_cockpit==nil)
            flight.alt=999; flight.speed=0
            assert(adapter.spawn_bomb(ctx)==true)
            assert(last_direction.x==0 and last_direction.y==1)
            deps.world.unit_pose=function()
                return {position={x=10,y=20,z=30},forward={x=0.6,y=0.8,z=0}}
            end
            assert(adapter.spawn_bomb(ctx)==true)
            assert(last_direction.x==0.6 and last_direction.y==0.8)
            deps.world.unit_pose=function()
                return {position={x=10,y=20,z=30}}
            end
            local n=calls.spawn
            local value,why=adapter.spawn_bomb(ctx)
            assert(value==false and calls.spawn==n,
                "missing forward vector must refuse cleanly: "..tostring(why))
        """)

    def test_clearance_is_tunable_and_validated(self):
        self.check("""
            for _,v in ipairs({0,-1,31,math.huge,0/0}) do
                assert(not pcall(Adapter.new,deps,{clearance=v}))
            end
            adapter=Adapter.new(deps,{clearance=8})
            local s=ready()
            assert(s.position.z==22)
        """)

    def test_heartbeat_bootstrap_stall_reset_and_recovery(self):
        self.check("""
            rejected() -- first observation cannot authorize a bomb
            assert(adapter.inspect(1.01)==nil) -- same frame still not enough
            flight.frames=11
            assert(adapter.inspect(1.02))
            assert(adapter.inspect(1.2))
            ctx.now=1.28; rejected() -- recent polling but heartbeat expired
            flight.frames=12
            assert(adapter.inspect(1.29))
            flight.frames=1
            assert(adapter.inspect(1.30)==nil)
            flight.frames=2
            assert(adapter.inspect(1.31))
        """)

    def test_long_gap_requires_a_new_observation_pair(self):
        self.check("""
            ready()
            flight.frames=100; ctx.now=2; rejected()
            flight.frames=101
            assert(adapter.inspect(2.01))
        """)

    def test_clock_backwards_nan_and_negative(self):
        self.check("""
            ready(); ctx.now=0.9; rejected()
            ctx.now=0/0; rejected()
            ctx.now=-1; rejected()
        """)

    def test_republished_status_table_is_continuity_not_rebootstrap(self):
        # VFC republishes its status global; treating the new table as a new
        # stream rejected every republish tick and visibly flapped the camera.
        self.check("""
            ready()
            local new={}
            for k,v in pairs(flight) do new[k]=v end
            flight=new                       -- same data, fresh table
            assert(adapter.inspect(1.02))    -- continuity while fresh
            flight.vehicle=flight.vehicle:gsub("seat=0xABC","seat=0xDEF")
            ctx.now=1.03; rejected()         -- identity change re-bootstraps
        """)

    def test_republished_table_with_advancing_frames_accepted_every_tick(self):
        # The observed in-game flap: each VFC publish was a fresh table, so
        # inspect alternately rejected on every publish while flying.
        self.check("""
            ready()
            for i=1,5 do
                local copy={}
                for k,v in pairs(flight) do copy[k]=v end
                copy.frames=copy.frames+1
                flight=copy
                ctx.now=1.01+i*0.01
                local s,why=adapter.inspect(ctx.now)
                assert(s, "republish tick "..i.." rejected: "..tostring(why))
            end
            assert(adapter.spawn_bomb(ctx)==true)
        """)

    def test_unproven_stream_still_rejects_until_first_advance(self):
        self.check("""
            local new={}
            for k,v in pairs(flight) do new[k]=v end
            new.frames=1   -- counter restart: a fresh stream must re-prove
            flight=new
            assert(adapter.inspect(1)==nil)
            flight.frames=2
            assert(adapter.inspect(1.01))
            -- A republished frozen table must not keep flight approval alive:
            -- past the freshness window with no advance, each poll rejects.
            for i=1,3 do
                local copy={}
                for k,v in pairs(flight) do copy[k]=v end
                flight=copy
                ctx.now=1.01+i*0.3
                assert(adapter.inspect(ctx.now)==nil) -- stale heartbeat
            end
            -- ...and it re-proves only when the counter moves again.
            ctx.now=ctx.now+0.01
            assert(adapter.inspect(ctx.now)==nil) -- first observation re-bootstraps
            flight.frames=3
            ctx.now=ctx.now+0.01
            assert(adapter.inspect(ctx.now))
        """)

    def test_caller_context_and_vehicle_lifetime_gate(self):
        for replacement in (
            "ctx.in_cockpit=false", "ctx.flight_enabled=nil", "ctx.flight_enabled=false",
            "ctx.focused=false", "ctx.paused=nil", "ctx.paused=true",
            "ctx.vehicle_key=nil", 'ctx.vehicle_key="999:000001AB"',
        ):
            with self.subTest(replacement=replacement):
                self.setUp()
                self.check("ready(); " + replacement + "; rejected()")

    def test_parked_snapshot_measures_real_root_speed_but_cannot_spawn(self):
        self.check("""
            flight.flying=false
            assert(adapter.inspect_vehicle(1)==nil)
            flight.frames=11
            local s=assert(adapter.inspect_vehicle(1.01))
            assert(s.flying==false and s.measured_speed==nil and s.root_position.z==30)
            flight.frames=12
            s=assert(adapter.inspect_vehicle(1.11))
            assert(s.measured_speed==0)
            deps.world.unit_pose=function()
                return {position={x=10.1,y=20,z=30},forward={x=0,y=1,z=0}}
            end
            flight.frames=13
            s=assert(adapter.inspect_vehicle(1.21))
            assert(math.abs(s.measured_speed-1)<0.0001)
            ctx.now=1.21
            rejected()
            assert(adapter.inspect(ctx.now)==nil)
        """)

    def test_flight_mode_policy_does_not_require_a_physical_ground_sensor(self):
        self.check("ready(); ctx.grounded=nil; assert(adapter.spawn_bomb(ctx)==true)")

    def test_definition_refusal_never_spawns(self):
        self.check("""
            ready()
            deps.custom.define=function() return nil,"HYBRID_INCOMPATIBLE","blocked" end
            local why=rejected()
            assert(why:find("HYBRID_INCOMPATIBLE",1,true))
        """)

    def test_exit_while_defining_never_spawns(self):
        self.check("""
            ready()
            local original=deps.custom.define
            deps.custom.define=function(spec) flight.flying=false; return original(spec) end
            rejected()
        """)

    def test_caller_context_rechecked_after_definition(self):
        self.check("""
            ready()
            local original=deps.custom.define
            deps.custom.define=function(spec) ctx.focused=false; return original(spec) end
            rejected()
        """)

    def test_inspection_or_definition_error_is_safe_rejection(self):
        self.check("""
            ready()
            deps.custom.define=function() error("allocation unavailable") end
            rejected()
            deps.world.entity_type=function() error("unreadable") end
            rejected()
            assert(not adapter.is_faulted())
        """)

    def test_waiting_action_cancelled_before_return_and_never_delayed(self):
        self.check("""
            ready(); status="waiting_for_assets"
            local value=adapter.spawn_bomb(ctx)
            assert(value==false and calls.cancel==1 and not adapter.is_faulted())
            assert(pending[1].status=="cancelled")
            flight.flying=false
            drain_mock_scheduler()
            assert(calls.native==0)
        """)

    def test_action_refusal_and_cancel_are_safe_false(self):
        self.check("""
            ready(); status="refused"
            assert(adapter.spawn_bomb(ctx)==false)
            status="cancelled"
            assert(adapter.spawn_bomb(ctx)==false)
            assert(not adapter.is_faulted() and calls.native==0)
        """)

    def test_nil_unknown_action_or_exception_latches_uncertainty(self):
        for replacement in (
            'status="pending"', 'status="mystery"',
            "deps.actions.spawn_custom_projectile=function() calls.spawn=calls.spawn+1; return nil end",
            'deps.actions.spawn_custom_projectile=function() calls.spawn=calls.spawn+1; error("possibly spawned") end',
        ):
            with self.subTest(replacement=replacement):
                self.setUp()
                self.check("ready(); " + replacement + "; unknown()")

    def test_failed_or_missing_cancel_is_uncertain(self):
        for cancel in (
            "nil", "function(self) return self end",
            'function(self) error("cancel unavailable") end',
            'function(self) self.status="requested" end',
        ):
            with self.subTest(cancel=cancel):
                self.setUp()
                self.check("""
                    ready()
                    deps.actions.spawn_custom_projectile=function()
                        calls.spawn=calls.spawn+1
                        return {status="waiting_for_assets",cancel=""" + cancel + """}
                    end
                    unknown()
                """)

    def test_reentrant_action_cannot_spawn_twice(self):
        self.check("""
            ready()
            local original=deps.actions.spawn_custom_projectile
            deps.actions.spawn_custom_projectile=function(def,opts)
                assert(adapter.spawn_bomb(ctx)==false)
                return original(def,opts)
            end
            assert(adapter.spawn_bomb(ctx)==true and calls.spawn==1)
        """)

    def test_spawn_weapon_uses_per_weapon_definition(self):
        self.check("""
            ready()
            local rocket={id="rockets",name="ROCKETS",
                output="output/v1/projectile/eagle-110mm-rocket-pods-projectile-82"}
            deps.custom.define=function(spec)
                calls.define=calls.define+1
                assert(spec.id=="jacks/eagle_rockets")
                assert(spec.base==rocket.output)
                -- Rockets keep their own 2.1 gravity and borrow only a
                -- faster 150 m/s launch speed from the P-34 Breacher.
                assert(type(spec.changes)=="table" and #spec.changes==1)
                assert(spec.changes[1].member=="speed"
                    and spec.changes[1].from=="output/v1/projectile/p-34-breacher")
                local n=0; for _ in pairs(spec) do n=n+1 end
                assert(n==3, "only the speed donor change is allowed")
                return {id=spec.id}
            end
            deps.actions.spawn_custom_projectile=function(def,opts)
                calls.spawn=calls.spawn+1
                assert(def.id=="jacks/eagle_rockets")
                assert(opts.owner=="mods/jacks/eagle_payload")
                return {status="requested"}
            end
            assert(adapter.spawn_weapon(ctx,rocket)==true)
            assert(calls.define==1 and calls.spawn==1)
        """)

    def test_speed_donor_map_covers_every_eagle_output(self):
        self.check("""
            ready()
            -- Every real Eagle output gets a slow ballistic launch donor so
            -- dropped ordnance arcs under gravity like a rack release; the
            -- self-propelled pods get the faster donor instead.
            local dropped={
                ["output/v1/projectile/eagle-500kg-bomb-projectile-239"]=true,
                ["output/v1/projectile/eagle-airstrike-projectile-170"]=true,
                ["output/v1/projectile/eagle-cluster-bomb-projectile-286"]=true,
                ["output/v1/projectile/eagle-napalm-airstrike-projectile-141"]=true,
                ["output/v1/projectile/eagle-gas-airstrike-projectile-188"]=true,
                ["output/v1/projectile/eagle-smoke-strike-projectile-130"]=true,
            }
            for output in pairs(dropped) do
                calls.define=0; last_spec=nil
                assert(adapter.spawn_weapon(ctx,{id="w"..tostring(output):sub(-3),
                    name="W",output=output})==true)
                assert(last_spec.changes~=nil and #last_spec.changes==1)
                assert(last_spec.changes[1].member=="speed"
                    and last_spec.changes[1].from=="output/v1/projectile/eat-411-leveller",
                    output)
            end
            calls.define=0; last_spec=nil
            assert(adapter.spawn_weapon(ctx,{id="rockets2",name="R",
                output="output/v1/projectile/eagle-110mm-rocket-pods-projectile-82"})==true)
            assert(last_spec.changes[1].from=="output/v1/projectile/p-34-breacher")
            -- An unknown output stays a plain clone: no fabricated ballistics.
            calls.define=0; last_spec=nil
            assert(adapter.spawn_weapon(ctx,{id="mystery",name="M",
                output="output/v1/projectile/not-an-eagle"})==true)
            assert(last_spec.changes==nil)
        """)

    def test_spawn_weapon_rejects_bad_spec_before_define(self):
        self.check("""
            ready()
            assert(adapter.spawn_weapon(ctx,{id="x"})==false)
            assert(adapter.spawn_weapon(ctx,nil)==false)
            assert(adapter.spawn_weapon(ctx,"rocket")==false)
            assert(calls.define==0 and calls.spawn==0 and not adapter.is_faulted())
        """)

    def test_call_pelican_anchors_over_root_when_landed(self):
        self.check("""
            ready()
            flight.flying=false; flight.frames=flight.frames+1
            local state,handle=adapter.call_pelican(
                {now=1.02,vehicle_key="123:000001AB",hover=75})
            assert(state=="requested" and type(handle)=="table")
            assert(calls.pelican==1 and pelican_opts.hover==75)
            assert(handle:alive() and handle.status=="requested")
            assert(calls.spawn==0 and calls.define==0 and not adapter.is_faulted())
        """)

    def test_call_pelican_refuses_wrong_vehicle_and_bad_ctx(self):
        self.check("""
            ready()
            flight.flying=false; flight.frames=flight.frames+1
            local state,handle=adapter.call_pelican(
                {now=1.02,vehicle_key="999:0000DEAD",hover=75})
            assert(state==false and type(handle)~="table")
            state,handle=adapter.call_pelican({now=-1,vehicle_key="123:000001AB"})
            assert(state==false and type(handle)~="table")
            state,handle=adapter.call_pelican(nil)
            assert(state==false and type(handle)~="table")
            assert(calls.pelican==0 and not adapter.is_faulted())
        """)

    def test_call_pelican_unavailable_without_api(self):
        self.check("""
            local deps2={}
            for k,v in pairs(deps) do deps2[k]=v end
            deps2.pelican=nil
            local adapter2=Adapter.new(deps2)
            assert(adapter2.inspect_vehicle(1)==nil)
            flight.frames=flight.frames+1
            local observation,why=adapter2.inspect_vehicle(1.01)
            assert(observation,why)
            local state,handle=adapter2.call_pelican(
                {now=1.02,vehicle_key="123:000001AB",hover=75})
            assert(state==false and type(handle)~="table" and calls.pelican==0)
            assert(not adapter2.is_faulted())
        """)

    def test_call_pelican_refusal_keeps_handle_status(self):
        self.check("""
            deps.pelican.spawn=function(opts)
                calls.pelican=calls.pelican+1
                local handle={status="refused",code="HOST_ONLY",reason="not host"}
                function handle:alive() return self.status~="refused" end
                return handle
            end
            ready()
            flight.flying=false; flight.frames=flight.frames+1
            local state,handle=adapter.call_pelican(
                {now=1.02,vehicle_key="123:000001AB",hover=75})
            assert(state=="refused" and type(handle)=="table"
                and handle.status=="refused" and not handle:alive())
            assert(calls.pelican==1 and not adapter.is_faulted())
        """)

    def test_parked_first_entry_discovers_maelstrom_by_proximity(self):
        self.check("""
            -- Never flown: no cached vehicle, VFC text blank, seat held.
            flight.flying=false
            flight.vehicle="-"
            local s=assert(adapter.inspect_vehicle(1))
            assert(s.vehicle_key=="123:000001AB" and s.flying==false)
            assert(s.role==4 and s.actor_hex==nil and s.seat_hex==nil)
            assert(calls.scan and calls.scan>=1)
            -- Cached after verification: a second tick must not rescan.
            local n=calls.scan
            s=assert(adapter.inspect_vehicle(1.01))
            assert(s.vehicle_key=="123:000001AB")
            assert(calls.scan==n)
            -- Parked still cannot release ordnance.
            ctx.now=1.01
            rejected()
        """)

    def test_proximity_not_used_when_vehicle_text_valid(self):
        self.check("""
            flight.flying=false -- landed but VFC still names the vehicle
            assert(adapter.inspect_vehicle(1)==nil) -- heartbeat bootstrap
            flight.frames=flight.frames+1
            local n=calls.scan or 0
            assert(adapter.inspect_vehicle(1.01))
            assert((calls.scan or 0)==n, "proximity scan ran despite live identity")
        """)

    def test_proximity_never_applies_to_flying_or_unheld_seat(self):
        self.check("""
            flight.flying=false; flight.vehicle="-"
            SoloVehicleDriver.status="idle"
            assert(adapter.inspect_vehicle(1)==nil)
            assert((calls.scan or 0)==0)
            SoloVehicleDriver.status="role_overlay_held_by_game_state"
            local s=assert(adapter.inspect_vehicle(1.01))
            SoloVehicleDriver=nil
            assert(adapter.inspect_vehicle(1.02)==nil)
        """)

    def test_proximity_ambiguous_far_or_poseless_refused(self):
        for body in (
            # Two Maelstroms inside the radius: ambiguous, refuse.
            'scan_descriptors={{type="B0C9FAF4AF8903F9",entity=123,unit=0x1AB},'
            '{type="B0C9FAF4AF8903F9",entity=124,unit=0x1AC}}; '
            'scan_units={[0x1AB]={x=10,y=20,z=30},[0x1AC]={x=12,y=20,z=30}}',
            # Avatar too far from the only Maelstrom.
            'avatar_pos={x=100,y=100,z=100}',
            # Candidate has no unit pose.
            'scan_units={}',
        ):
            with self.subTest(body=body):
                self.setUp()
                self.check("flight.flying=false; flight.vehicle='-'; "
                    + body + "; assert(adapter.inspect_vehicle(1)==nil); "
                    "assert(not adapter.is_faulted())")

    def test_proximity_candidate_still_fully_verified(self):
        self.check("""
            flight.flying=false; flight.vehicle="-"
            deps.world.entity_exists=function() return false end
            assert(adapter.inspect_vehicle(1)==nil)
            assert(not adapter.is_faulted())
            deps.world.entity_exists=nil -- functions restored via fresh setUp in loop tests only
        """)
        # Stale candidate cleared from cache: next tick rescans and fails again.
        self.setUp()
        self.check("""
            flight.flying=false; flight.vehicle="-"
            local count=0
            local original=deps.world.entity_type
            deps.world.entity_type=function(w,id) count=count+1; return "0000000000000001" end
            assert(adapter.inspect_vehicle(1)==nil)
            assert(adapter.inspect_vehicle(1.01)==nil)
            assert(count>=2, "bad candidate stayed cached across ticks")
            assert(not adapter.is_faulted())
        """)

    def test_proximity_api_gaps_fail_closed(self):
        for body in (
            'deps.world.health_header=nil',
            'deps.world.descriptor=nil',
            'deps.world.unit_position=nil',
            'health_records=false',
            'avatar_pos=nil',
            'scan_descriptors={{type="B0C9FAF4AF8903F9",entity=0,unit=0x1AB}}',
            'scan_descriptors={{type="B0C9FAF4AF8903F9"}}',
            'scan_descriptors={{type="deadbeefdeadbeef",entity=123,unit=0x1AB}}',
        ):
            with self.subTest(body=body):
                self.setUp()
                self.check("flight.flying=false; flight.vehicle='-'; "
                    + body + "; assert(adapter.inspect_vehicle(1)==nil); "
                    "assert(not adapter.is_faulted())")

    def test_proximity_throwing_scan_is_a_safe_rejection(self):
        self.check("""
            flight.flying=false; flight.vehicle="-"
            deps.world.descriptor=function() error("read fault") end
            local s,why=adapter.inspect_vehicle(1)
            assert(s==nil and type(why)=="string")
            assert(not adapter.is_faulted())
        """)

    def test_parked_entry_then_takeoff_uses_normal_path(self):
        self.check("""
            flight.flying=false; flight.vehicle="-"
            assert(adapter.inspect_vehicle(1))
            flight.flying=true
            flight.vehicle="e=123 u=0x1AB actor=0xB0C9FAF4AF8903F9 seat=0xABC role=4"
            flight.frames=flight.frames+1
            assert(adapter.inspect(1.01)==nil) -- identity change re-bootstraps
            flight.frames=flight.frames+1
            local s=assert(adapter.inspect(1.02))
            assert(s.flying==true)
            ctx.now=1.02
            assert(adapter.spawn_bomb(ctx)==true)
        """)

    def test_seat_proximity_option_validated(self):
        self.check("""
            for _,v in ipairs({0,-1,31,math.huge,0/0,"10"}) do
                assert(not pcall(Adapter.new,deps,{seat_proximity=v}))
            end
            local a=assert(Adapter.new(deps,{seat_proximity=2}))
            flight.flying=false; flight.vehicle="-"
            assert(a.inspect_vehicle(1)==nil) -- 2.45m gap exceeds the 2m radius
        """)

    def test_cold_parked_seat_without_camera_template_resolves(self):
        self.check("""
            -- Truly cold start: parked seat entered before any flight, so VFC
            -- never attached the gunner camera and reports tmpl=-1.
            flight.flying=false; flight.vehicle="-"; flight.tmpl=-1
            local s=assert(adapter.inspect_vehicle(1))
            assert(s.vehicle_key=="123:000001AB" and s.flying==false)
            assert(calls.scan and calls.scan>=1)
            ctx.now=1.01
            rejected() -- still cannot release ordnance while parked
        """)

    def test_cold_template_never_relaxed_for_flight_or_drop(self):
        self.check("""
            flight.flying=true; flight.tmpl=-1  -- flying needs template 26
            assert(adapter.inspect(1)==nil)
            assert(adapter.inspect_vehicle(1.01)==nil)
            assert((calls.scan or 0)==0)
            ctx.now=1.02
            rejected()
        """)

    def test_cold_template_still_needs_the_held_seat(self):
        self.check("""
            flight.flying=false; flight.vehicle="-"; flight.tmpl=-1
            SoloVehicleDriver.status="idle"
            assert(adapter.inspect_vehicle(1)==nil)
            assert((calls.scan or 0)==0)
        """)

    def test_only_negative_one_template_is_relaxed(self):
        for tmpl in (0, 57, "-1"):
            with self.subTest(tmpl=tmpl):
                self.setUp()
                arg = repr(tmpl) if isinstance(tmpl, str) else str(tmpl)
                if isinstance(tmpl, str): arg = '"-1"'
                self.check(f"flight.flying=false; flight.vehicle='-'; flight.tmpl={arg}; "
                           "assert(adapter.inspect_vehicle(1)==nil)")

    def test_prewarm_only_requests_semantic_assets_and_reuses_handle(self):
        self.check("""
            local job=assert(adapter.prewarm())
            assert(adapter.prewarm()==job)
            assert(calls.assets==1 and calls.spawn==0 and calls.define==0)
        """)

    def test_prewarm_failure_cannot_spawn(self):
        self.check("""
            deps.hd2.require_assets=function() error("package unavailable") end
            assert(adapter.prewarm()==nil)
            assert(calls.spawn==0 and not adapter.is_faulted())
        """)

    def test_no_globals_written_or_loads_on_module_import(self):
        root = Path(__file__).resolve().parent
        self.lua.execute("require=function() error('require forbidden') end; sentinel={}; VehicleFlight=sentinel")
        self.lua.execute((root / "eagle_runtime_adapter.lua").read_text(encoding="utf-8"))
        self.check("assert(VehicleFlight==sentinel)")


if __name__ == "__main__":
    unittest.main()
