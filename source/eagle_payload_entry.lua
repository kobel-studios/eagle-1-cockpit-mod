-- HD2-Addon: mods/jacks/eagle_payload
-- Experimental Eagle payload; HD2Runtime 0.40.0 by SkyeShade.
-- https://github.com/SkyeShade/HD2Runtime -- retain upstream attribution.
-- Logical control seat / flight-mode policy, NOT physical cockpit or ground proof.
-- Unchanged vanilla type 239: nominal 500 m/s, not a slow gravity-drop bomb.
local OWNER = "mods/jacks/eagle_payload"
local SINGLETON = "JacksEaglePayloadEntryV1"
local WEAPONS = {
    {id="bomb500", name="500 KG", capacity=2,
        output="output/v1/projectile/eagle-500kg-bomb-projectile-239"},
    {id="airstrike", name="AIRSTRIKE", capacity=3,
        output="output/v1/projectile/eagle-airstrike-projectile-170"},
    {id="cluster", name="CLUSTER", capacity=4,
        output="output/v1/projectile/eagle-cluster-bomb-projectile-286"},
    {id="napalm", name="NAPALM", capacity=3,
        output="output/v1/projectile/eagle-napalm-airstrike-projectile-141"},
    {id="rockets", name="ROCKETS", capacity=8,
        output="output/v1/projectile/eagle-110mm-rocket-pods-projectile-82"},
    {id="gas", name="GAS", capacity=2,
        output="output/v1/projectile/eagle-gas-airstrike-projectile-188"},
    {id="smoke", name="SMOKE", capacity=4,
        output="output/v1/projectile/eagle-smoke-strike-projectile-130"},
}
local existing = rawget(_G, SINGLETON)
if existing then return existing end -- never reset ammo/faults by reloading this chunk
local entry = {controllers={}, count=0, now=0, status="starting", disabled=false,
    hud_visible=false, in_mission=false}
rawset(_G, SINGLETON, entry)

local function finite(v)
    return type(v)=="number" and v==v and math.abs(v)<math.huge
end
local function fallback(message) pcall(print, "[Eagle payload] "..tostring(message)) end
-- Use the public entry so it captures every Runtime module while the game's
-- startup package is still available. Requiring api/hd2 alone skips that step.
local ok, hd2 = pcall(require, "mods/skyeshade/hd2runtime")
if not ok or type(hd2)~="table" or hd2.version~="0.40.0" or hd2.api_version~=1 then
    entry.disabled=true
    entry.status="disabled: HD2Runtime 0.40.0/API 1 required"
    fallback(entry.status)
    return entry
end

local function start()
    local Payload = require("mods/jacks/eagle_payload_core")
    local Adapter = require("mods/jacks/eagle_runtime_adapter")
    local Scope = require("mods/jacks/eagle_camera_scope")
    local mod = hd2.mod(OWNER)
    local held = {fire=false, rearm=false, select=false}
    local function log(message)
        local logged = pcall(mod.log, mod, message)
        if not logged then fallback(message) end
    end
    local function status(message)
        if entry.status~=message then entry.status=message; log(message) end
    end
    local camera_reason
    entry.camera,camera_reason=Scope.load({log=log})
    if not entry.camera then log("cockpit camera unavailable: "..tostring(camera_reason)) end
    local previous_shutdown=rawget(_G,"shutdown")
    local shutdown_wrapper
    shutdown_wrapper=function(...)
        entry.disabled=true
        if entry.camera then
            local restored,reason=entry.camera.stop()
            if not restored then log(reason) end
        end
        if rawget(_G,"shutdown")==shutdown_wrapper then _G.shutdown=previous_shutdown end
        if type(previous_shutdown)=="function" then return previous_shutdown(...) end
    end
    _G.shutdown=shutdown_wrapper
    local function inactive(except)
        if not except and entry.camera then entry.camera.update(nil, entry.now) end
        for key,controller in pairs(entry.controllers) do
            if key~=except then controller.update({
                now=entry.now, fire=held.fire, rearm=held.rearm,
                authority=false, in_cockpit=false, alive=false, focused=false, paused=true,
            }) end
        end
    end
    local function mission(epoch)
        if entry.epoch==epoch then return end
        if entry.camera then entry.camera.update(nil, entry.now) end
        -- Only a positively observed new Runtime mission epoch resets ownership.
        -- Temporary read failures, focus loss and exits never clear this state.
        entry.epoch=epoch
        entry.controllers, entry.count = {}, 0
        entry.pelican,entry.pelican_stage,entry.was_rearming=nil,nil,false
        entry.pelican_key,entry.pelican_anchor=nil,nil
        entry.adapter=assert(Adapter.load())
        entry.prewarm_attempts, entry.next_prewarm, entry.prewarmed = 0, entry.now, false
        status("mission ready: B fire, X or 1-7 select weapon, Home rearm run")
    end
    local function bind(id, key, label, press, release)
        local handle=mod:bind("jacks_eagle."..id,{
            key=key, native={label=label,category="Eagle Payload (Experimental)"},
            on_press=press, on_release=release,
        })
        assert(handle and handle.state~="refused", "key binding unavailable: "..id)
    end
    bind("drop","B","Fire Eagle Weapon",function() held.fire=true end,
        function() held.fire=false end)
    bind("select","X","Select Next Eagle Weapon",function() held.select=true end,
        function() held.select=false end)
    bind("rearm","HOME","Call Eagle Rearm Run",function() held.rearm=true end,
        function() held.rearm=false end)
    local wanted_weapon
    for index,weapon in ipairs(WEAPONS) do
        bind("w"..index,tostring(index),"Eagle Weapon: "..weapon.name,
            function() wanted_weapon=index end,function() end)
    end

    local function menu_clear()
        -- game_menu alone is NOT a universal menu detector: it is captured
        -- during cursor holds. Also require the live cursor to be hidden.
        if not hd2.ui or type(hd2.ui.cursor)~="function" then return false end
        local cursor=hd2.ui.cursor()
        if type(cursor)~="table" or cursor.game_menu~=false or cursor.held~=false
            or cursor.show_cursor~=false or cursor.mouse_focus==false then return false end
        if type(hd2.ui.settings_open)=="function" and hd2.ui.settings_open() then return false end
        return true
    end
    -- Rearm visual: when a run starts, summon the empty service Pelican to
    -- hover over the parked Eagle for the whole run. Decorative only: a
    -- refusal or failure never blocks the rearm and never faults weapons.
    -- root may be nil (out-of-seat service), which skips the summon.
    local function service_pelican(result, root, vehicle_key)
        if result.rearming and not entry.was_rearming then
            local ok_a,alive=pcall(function()
                return entry.pelican and entry.pelican:alive() end)
            -- The Pelican hovers at a FIXED anchor. Only reuse a live handle
            -- for the same vehicle parked within a few metres of its anchor;
            -- a rearm elsewhere needs a fresh summon over the new position.
            local anchor=entry.pelican_anchor
            local same_spot=ok_a and alive and anchor and root
                and vehicle_key==entry.pelican_key
                and (root.x-anchor.x)^2+(root.y-anchor.y)^2
                    +(root.z-anchor.z)^2<=625
            if not same_spot then
                entry.pelican,entry.pelican_stage,entry.pelican_anchor=nil,nil,nil
                local call=entry.adapter.call_pelican
                if type(call)=="function" and root then
                    local ok_call,state,handle,reason=pcall(call,{
                        now=entry.now,vehicle_key=vehicle_key,hover=15})
                    if ok_call and type(handle)=="table" then
                        entry.pelican,entry.pelican_stage=handle,
                            tostring(state or "requested")
                        entry.pelican_key=vehicle_key
                        entry.pelican_anchor={x=root.x,y=root.y,z=root.z}
                        log("rearm Pelican requested: "..entry.pelican_stage)
                    else
                        entry.pelican_stage="unavailable"
                        log("rearm Pelican unavailable: "..tostring(reason or state))
                    end
                end
            end
        end
        if not result.rearming and entry.was_rearming
            and result.status=="rearmed" then
            log("rearm run complete; Pelican departing on schedule")
        end
        entry.was_rearming=result.rearming==true
        if entry.pelican and entry.pelican.status then
            entry.pelican_stage=tostring(entry.pelican.status)
        end
    end
    local function report(result)
        local message=string.format("%s %d/%d: %s",result.selected_name or "weapon",
            result.ammo,result.capacity,result.status)
        -- Don't spam logs with a changing timer every frame; HUD has countdown.
        status(message)
    end
    local function tick(dt)
        entry.hud_visible=false
        local valid_dt=finite(dt) and dt>0 and dt<=0.25
        if finite(dt) and dt>0 then entry.now=entry.now+dt end
        local state=hd2.game_state()
        local epoch,tracked=hd2.events.mission_id()
        local live=type(state)=="table" and state.mission==true and state.host==true
            and tracked==true and finite(epoch) and epoch>=1
        entry.in_mission=live
        if not live then
            inactive()
            status("inactive: mission host/state unavailable")
            return
        end
        mission(epoch)
        local active=valid_dt and hd2.input.focused()==true and menu_clear()
        if not active then inactive(); status("inactive: pause, frame gap, focus or menu"); return end
        if not entry.prewarmed and entry.prewarm_attempts<3 and entry.now>=entry.next_prewarm then
            entry.prewarm_attempts=entry.prewarm_attempts+1
            entry.next_prewarm=entry.now+10
            entry.prewarmed=entry.adapter.prewarm()~=nil
        end
        local snapshot,why=entry.adapter.inspect_vehicle(entry.now)
        if not snapshot then
            -- Out of the verified seat: the parked craft keeps its rearm
            -- running on the last verified controller, and Home can still
            -- start one. An empty parked craft cannot be driven, so landed
            -- and stationary are reported parked-true. Weapons stay dead.
            local ctl=entry.current_key and entry.controllers[entry.current_key]
            if not ctl then
                inactive(); status(why or "no verified control seat"); return
            end
            if entry.camera then entry.camera.update(nil, entry.now) end
            local result=ctl.update({now=entry.now,
                vehicle_key=entry.last_vehicle_key,remote=true,fire=false,
                select=false,rearm=held.rearm,authority=false,alive=true,
                in_cockpit=false,focused=true,paused=false,landed=true,
                stationary=true,speed=0,flight_enabled=false})
            entry.payload=result
            entry.hud_visible=result.rearming==true
            service_pelican(result, entry.last_root, entry.last_vehicle_key)
            report(result)
            return
        end
        if entry.camera then entry.camera.update(snapshot, entry.now) end
        local key=tostring(epoch)..":"..snapshot.vehicle_key
        local controller=entry.controllers[key]
        if not controller then
            if entry.count>=128 then inactive(); status("vehicle limit reached; new payload refused"); return end
            controller=Payload.new(function(weapon)
                local ctx=entry.spawn_ctx
                if type(ctx)~="table" then return {status="rejected"} end
                local ok,r=pcall(entry.adapter.spawn_weapon,ctx,weapon)
                if not ok then return {status="uncertain"} end
                if r==true then return {status="requested"} end
                if r==false then return {status="rejected"} end
                return {status="uncertain"}
            end,{weapons=WEAPONS,rearm_seconds=60,drop_interval=1})
            entry.controllers[key]=controller
            entry.count=entry.count+1
        end
        inactive(key)
        local speed=snapshot.measured_speed
        local select_index=wanted_weapon
        wanted_weapon=nil -- consume the press; a held key must not reselect
        entry.spawn_ctx={now=entry.now,vehicle_key=snapshot.vehicle_key,
            in_cockpit=true,flight_enabled=snapshot.flying,focused=true,paused=false}
        -- "Landed" is flight mode OFF; there is no physical contact sensor.
        -- "Cockpit" means this verified logical control seat, not eye geometry.
        local result=controller.update({
            now=entry.now,vehicle_key=snapshot.vehicle_key,fire=held.fire,
            rearm=held.rearm,select=held.select,select_index=select_index,
            authority=snapshot.authority,alive=snapshot.alive,in_cockpit=true,
            flight_enabled=snapshot.flying,focused=true,paused=false,
            landed=snapshot.flying==false,speed=speed,
            stationary=finite(speed) and speed>=0 and speed<=0.5 or false,
        })
        entry.current_key,entry.payload=key,result
        entry.hud_visible=true
        entry.last_vehicle_key=snapshot.vehicle_key
        entry.last_root=snapshot.root_position or entry.last_root
        service_pelican(result, snapshot.root_position, snapshot.vehicle_key)
        report(result)
    end
    entry.frame=mod:on_frame(function(dt)
        if entry.disabled then return end
        local worked,why=pcall(tick,dt)
        if not worked then
            entry.hud_visible=false
            inactive()
            status("inactive: frame error: "..tostring(why))
        end
    end,{id="eagle-payload-frame",scope="session"})
    assert(entry.frame and entry.frame.state~="refused","frame subscription unavailable")
    -- Overlay is display-only. Failure must not disable mandatory status logs.
    local hud_ok,hud_error=pcall(function()
        local overlay=hd2.ui.overlay({id="eagle-payload",owner=OWNER})
        overlay:draw(function(d)
            if not entry.in_mission then return end
            local scale=d.scale or 1
            if entry.hud_visible then
                -- Cockpit sight; canvas is the 1920x1080 reference plane.
                local cx,cy=960*scale,540*scale
                d:rect(cx-14*scale,cy-1*scale,28*scale,2*scale,{94,184,232,200},4)
                d:rect(cx-1*scale,cy-14*scale,2*scale,28*scale,{94,184,232,200},4)
            end
            -- No fake canopy frame: the user asked to remove the edge bars.
            local text,detail,loadout
            if entry.hud_visible and entry.payload then
                local payload=entry.payload
                text=string.format("EAGLE | %s  %d / %d",
                    payload.selected_name or "WEAPON",payload.ammo,payload.capacity)
                detail="X: WEAPON    B: FIRE    HOME: REARM"
                if payload.rearming then
                    local pelican=entry.pelican_stage
                    if pelican=="hovering" or pelican=="held" then
                        pelican="SERVICE PELICAN ON STATION"
                    elseif pelican=="departing" or pelican=="released" then
                        pelican="service Pelican departing"
                    elseif pelican=="pending" or pelican=="requested"
                        or pelican=="arriving" then
                        pelican="SERVICE PELICAN INBOUND"
                    elseif pelican=="unavailable" or pelican=="refused" then
                        pelican="no Pelican visual - timer only"
                    elseif pelican then
                        pelican="service Pelican "..pelican
                    else
                        pelican="service Pelican inbound"
                    end
                    detail=string.format("REARM RUN: %.0f seconds - %s - GUNS SAFED",
                        payload.rearm_remaining,pelican)
                elseif payload.faulted then
                    detail="Release unconfirmed - weapons disabled for this mission"
                elseif payload.ammo==0 then
                    detail="EMPTY - land, stop and press Home for a rearm run"
                elseif payload.status=="release rejected" then
                    detail="Weapon unavailable - check the mod log"
                elseif payload.status=="landed and stationary required" then
                    detail="Land and hold still, then press Home"
                end
                local strip={}
                for index,w in ipairs(payload.weapons or {}) do
                    local count
                    if payload.rearming then
                        count=w.ammo.."->"..w.capacity
                    else
                        count="x"..w.ammo
                    end
                    strip[#strip+1]=index==payload.selected
                        and ("["..w.name.." "..count.."]") or (w.name.." "..count)
                end
                if #strip>0 then loadout=table.concat(strip,"  ") end
            else
                return
            end
            local height=loadout and 94 or 66
            d:rect(20*scale,96*scale,540*scale,height*scale,{18,25,32,210})
            d:rect(20*scale,96*scale,3*scale,height*scale,"#5EB8E8",1)
            d:text(text,32*scale,106*scale,{size=18*scale,colour="#BFE7FFFF",z=2})
            d:text(detail,32*scale,132*scale,{size=14*scale,colour="#FFFFFF",z=2})
            if loadout then
                d:text(loadout,32*scale,156*scale,{size=12*scale,colour="#BFE7FF",z=2})
            end
            if entry.hud_visible and entry.payload and entry.payload.rearming then
                d:rect(32*scale,178*scale,512*scale,4*scale,{70,80,90,255},2)
                d:rect(32*scale,178*scale,512*scale*entry.payload.rearm_progress,4*scale,"#5EB8E8",3)
            end
        end)
        entry.overlay=overlay
    end)
    if not hud_ok then log("HUD unavailable; status logging remains active: "..tostring(hud_error)) end
    status("experimental enabled; 7 unverified Eagle weapons; rearm runs while landed")
end

local started,why=pcall(function() return hd2.events.run_as(OWNER,start) end)
if not started then
    if entry.camera then pcall(entry.camera.stop) end
    entry.disabled=true
    entry.status="disabled: startup failed: "..tostring(why)
    fallback(entry.status)
end
return entry
