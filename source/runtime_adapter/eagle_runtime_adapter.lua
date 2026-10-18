-- Experimental, NOT installed or automatically started.
-- Built against HD2Runtime 0.40.0/API 1 by SkyeShade:
-- https://github.com/SkyeShade/HD2Runtime
-- Uses its guarded development API; no native addresses, FFI, or row edits.
-- A requested action is acceptance, NOT proof of a working in-game 500kg bomb.
local Adapter = {}
local VERSION, API = "0.40.0", 1
local REVISION = "vehicle-flight-1.0.1"
local MAELSTROM = "B0C9FAF4AF8903F9"
local DEFAULT_BOMB = "output/v1/projectile/eagle-500kg-bomb-projectile-239"
local OWNER = "mods/jacks/eagle_payload"
-- The real Eagle rows launch at 500-700 m/s, which makes gravity all but
-- invisible. A dropped bomb leaves the rack at aircraft speed, not muzzle
-- velocity, so each weapon borrows only its launch `speed` member from a
-- slow ballistic donor; gravity, drag, mass, damage and impact all stay
-- native to the real Eagle row.
local SPEED_DONORS = {
    -- Dropped ordnance: 50 m/s release (EAT-411 Leveller, gravity 1.0).
    ["output/v1/projectile/eagle-500kg-bomb-projectile-239"] =
        "output/v1/projectile/eat-411-leveller",
    ["output/v1/projectile/eagle-airstrike-projectile-170"] =
        "output/v1/projectile/eat-411-leveller",
    ["output/v1/projectile/eagle-cluster-bomb-projectile-286"] =
        "output/v1/projectile/eat-411-leveller",
    ["output/v1/projectile/eagle-napalm-airstrike-projectile-141"] =
        "output/v1/projectile/eat-411-leveller",
    ["output/v1/projectile/eagle-gas-airstrike-projectile-188"] =
        "output/v1/projectile/eat-411-leveller",
    ["output/v1/projectile/eagle-smoke-strike-projectile-130"] =
        "output/v1/projectile/eat-411-leveller",
    -- Self-propelled 110mm pods: faster 150 m/s launch (P-34 Breacher)
    -- while keeping the row's own gravity factor of 2.1.
    ["output/v1/projectile/eagle-110mm-rocket-pods-projectile-82"] =
        "output/v1/projectile/p-34-breacher",
}
local STRATAGEMS = {
    "Eagle 500kg Bomb", "Eagle Airstrike", "Eagle Cluster Bomb",
    "Eagle Napalm Airstrike", "Eagle 110mm Rocket Pods",
    "Eagle Gas Airstrike", "Eagle Smoke Strike",
}

local function finite(n, limit)
    return type(n) == "number" and n == n and math.abs(n) <= limit
end

local function integer(n, low, high)
    return finite(n, high) and n >= low and n == math.floor(n)
end

local function vector(v)
    return type(v) == "table" and finite(v.x, 100000)
        and finite(v.y, 100000) and finite(v.z, 100000)
end

local function hex(text, limit)
    return #text <= limit and (text == "0" or text:sub(1, 1) ~= "0")
end

-- actor/seat are opaque diagnostic strings, NOT trusted pointers or type ids.
-- In particular seat is VFC's seat_type; do not cast either to a Lua double.
function Adapter.parse_vehicle(text)
    if type(text) ~= "string" or #text > 128 then return nil, "invalid vehicle text" end
    local entity, unit, actor, seat, role = text:match(
        "^e=(%d+) u=0x([0-9A-F]+) actor=0x([0-9A-F]+) seat=0x([0-9A-F]+) role=(%d+)$")
    if not entity or #entity > 10 or #role > 10
        or (#entity > 1 and entity:sub(1, 1) == "0")
        or (#role > 1 and role:sub(1, 1) == "0")
        or not hex(unit, 8) or not hex(actor, 16) or not hex(seat, 16) then
        return nil, "noncanonical vehicle text"
    end
    entity, unit, role = tonumber(entity), tonumber(unit, 16), tonumber(role)
    if not integer(entity, 1, 4294967295) or not integer(unit, 1, 4294967295)
        or not integer(role, 0, 4294967295) then return nil, "invalid vehicle ids" end
    return {entity = entity, unit = unit, actor_hex = actor, seat_hex = seat, role = role,
        vehicle_key = string.format("%d:%08X", entity, unit)}
end

-- All dependencies are injected in tests. Construction does not touch the game.
-- read_flight() defaults to the real, read-only status global; never changes it.
function Adapter.new(deps, options)
    assert(type(deps) == "table", "explicit Runtime dependencies required")
    options = options or {}
    local clearance = options.clearance or 4
    local max_age = options.max_status_age or 0.25
    local role = options.control_role or 4
    assert(finite(clearance, 30) and clearance >= 1, "clearance must be 1..30 metres")
    assert(finite(max_age, 1) and max_age > 0, "max_status_age must be >0 and <=1 second")
    assert(integer(role, 0, 4294967295), "invalid control role")
    local hd2, world_api, custom, actions = deps.hd2, deps.world, deps.custom, deps.actions
    local pelican = deps.pelican
    local read_flight = deps.read_flight or function() return rawget(_G, "VehicleFlight") end
    -- Held control-seat proof for the landed fallback: the game-state
    -- SoloVehicleDriver role overlay, or an injected equivalent in tests.
    -- Fails closed whenever the overlay is absent or reports any other status.
    local seat_held = deps.seat_held or function()
        local svd = rawget(_G, "SoloVehicleDriver")
        return type(svd) == "table" and svd.status == "role_overlay_held_by_game_state"
    end
    local proximity = options.seat_proximity or 10
    assert(finite(proximity, 30) and proximity > 0,
        "seat_proximity must be >0 and <=30 metres")
    local last_time, heartbeat, tracked_text, tracked_frame, proven
    local motion, measured_speed, cached_vehicle
    local faulted, busy = false, false
    local definitions, asset_job = {}, nil
    local self = {}

    local function reset_heartbeat()
        heartbeat, tracked_text, tracked_frame, proven = nil, nil, nil, false
        motion, measured_speed = nil, nil
    end

    local function compatible()
        if type(hd2) ~= "table" or hd2.version ~= VERSION or hd2.api_version ~= API then
            return nil, "unsupported HD2Runtime; need 0.40.0/API 1"
        end
        if hd2.build() ~= "matched" then return nil, "unknown or mismatched game build" end
        return true
    end

    local function authority()
        local ok, why = compatible()
        if not ok then return nil, why end
        local state = hd2.game_state()
        if type(state) ~= "table" or state.mission ~= true or state.host ~= true then
            return nil, "host in mission required"
        end
        local player = hd2.local_player()
        if not player or player:is_local_player() ~= true or player:is_alive() ~= true then
            return nil, "living local player required"
        end
        local avatar = player:avatar()
        if not avatar or avatar:is_alive() ~= true or avatar:is_downed() ~= false then
            return nil, "living non-downed local avatar required"
        end
        return true
    end

    -- Parked first-entry identity lookup. Returns only {entity, unit, role,
    -- vehicle_key}: actor/seat are unknown outside VFC's seat text and stay
    -- nil; the caller's verification pass still decides whether the record
    -- lives. Reads: local avatar position (player:avatar():position()),
    -- health-record descriptors, and unit positions -- the same read-only
    -- world surface the normal path uses.
    local function proximity_vehicle(world)
        if type(world_api.health_header) ~= "function"
            or type(world_api.descriptor) ~= "function"
            or type(world_api.unit_position) ~= "function" then
            return nil, "health-record scan unsupported by this runtime"
        end
        local player = hd2.local_player()
        local avatar = player and player:avatar()
        local here = avatar and avatar:position()
        if not vector(here) then return nil, "avatar position unavailable" end
        local slot = world.view and world.view.slot
        local header = type(slot) == "function"
            and world_api.health_header(world, world.view.slot())
        if type(header) ~= "table" or not integer(header.live, 0, 4294967295)
            or not header.descriptors then
            return nil, "health records unreadable"
        end
        local found
        for index = 0, header.live - 1 do
            local d = world_api.descriptor(world, header, index)
            if type(d) == "table" and type(d.type) == "string"
                and d.type:upper() == MAELSTROM
                and integer(d.entity, 1, 4294967295)
                and integer(d.unit, 1, 4294967295) then
                local pos = world_api.unit_position(world, d.unit)
                if vector(pos) then
                    local dx, dy, dz = pos.x - here.x, pos.y - here.y, pos.z - here.z
                    if dx * dx + dy * dy + dz * dz <= proximity * proximity then
                        if found then
                            return nil, "more than one Maelstrom near the avatar"
                        end
                        found = {entity = d.entity, unit = d.unit, role = role,
                            vehicle_key = string.format("%d:%08X", d.entity, d.unit)}
                    end
                end
            end
        end
        if not found then return nil, "no Maelstrom near the seated avatar" end
        return found
    end

    local function inspect(now, require_flying)
        if faulted then return nil, "bomb outcome unknown; adapter faulted" end
        if not finite(now, 9007199254740991) or now < 0
            or (last_time and now < last_time) then
            reset_heartbeat()
            last_time = nil
            return nil, "invalid monotonic clock"
        end
        -- A long polling gap cannot establish continuous seat occupancy.
        if last_time and now - last_time > max_age then reset_heartbeat() end
        last_time = now
        local allowed, why = authority()
        if not allowed then reset_heartbeat(); return nil, why end
        local flight = read_flight()
        -- tmpl=26 is the gunner camera VFC reports while a supported vehicle
        -- context is active. A COLD parked seat (entered on the ground, never
        -- flown) reports tmpl=-1: no camera template is attached at all. The
        -- parked path accepts exactly that sentinel; flying still requires 26.
        -- The seat-overlay + identity checks below carry the whole proof then.
        local cold_parked = not require_flying and type(flight) == "table"
            and flight.flying == false and flight.tmpl == -1
        if type(flight) ~= "table" or flight.rev ~= REVISION or type(flight.flying) ~= "boolean"
            or (require_flying and flight.flying ~= true)
            or (flight.tmpl ~= 26 and not cold_parked)
            or not integer(flight.frames, 1, 9007199254740991) then
            reset_heartbeat()
            return nil, "no supported active flight"
        end
        local vehicle, reason = Adapter.parse_vehicle(flight.vehicle)
        local landed = false
        if not vehicle then
            -- Flight mode OFF blanks VFC's vehicle text even while the driver
            -- is still seated. The last fully verified vehicle then remains
            -- observable only while the game state still holds our seat-role
            -- overlay; a lost seat or a missing verification fails closed.
            if require_flying or flight.flying ~= false or not seat_held() then
                if not seat_held() then cached_vehicle = nil end
                reset_heartbeat()
                return nil, reason or "not the configured control role"
            end
            if not cached_vehicle then
                -- First parked entry: VFC has never emitted this vehicle's
                -- identity text, so the held seat overlay cannot be tied to
                -- a known vehicle. Proximity supplies only a candidate: the
                -- unique live Maelstrom whose unit origin sits within
                -- `proximity` metres of the local avatar. Nothing here
                -- bypasses verification -- the entity/unit/type/pose checks
                -- below still prove or reject it, and a failure clears the
                -- cache. Two Maelstroms inside the radius are ambiguous and
                -- refused. Residual gap: if the held seat belongs to another
                -- vehicle parked within the radius of a Maelstrom, that
                -- Maelstrom could be bound; weapon release still requires
                -- inspect() (flying with live VFC text), so only parked
                -- rearm/HUD state could attach to the wrong tank.
                local world, world_reason = world_api.open()
                if world then
                    local found, why = proximity_vehicle(world)
                    if not found then
                        reset_heartbeat()
                        return nil, why or "no Maelstrom near the seated avatar"
                    end
                    cached_vehicle = found
                else
                    reset_heartbeat()
                    return nil, world_reason or "world unavailable"
                end
            end
            vehicle = {entity = cached_vehicle.entity, unit = cached_vehicle.unit,
                actor_hex = cached_vehicle.actor_hex, seat_hex = cached_vehicle.seat_hex,
                role = cached_vehicle.role, vehicle_key = cached_vehicle.vehicle_key}
            landed = true
        elseif vehicle.role ~= role then
            cached_vehicle = nil
            reset_heartbeat()
            return nil, "not the configured control role"
        end
        -- Blank vehicle text is not an identity change: tracked_text keeps the
        -- last parsed string. Frame-counter continuity, not table identity,
        -- proves liveness: VFC republishes its status table between polls, and
        -- a republish with a non-decreasing frame count is the same stream --
        -- resetting on `flight ~= tracked_table` rejected every republish tick
        -- and flapped the camera/HUD in game. A regression, a changed vehicle
        -- text (flying) or a first observation re-bootstrap: the next observed
        -- advance must re-prove the stream before it is trusted again.
        if not tracked_frame or flight.frames < tracked_frame
            or (not landed and flight.vehicle ~= tracked_text) then
            motion, measured_speed = nil, nil
            tracked_frame = flight.frames
            if not landed then tracked_text = flight.vehicle end
            heartbeat, proven = nil, false
        elseif flight.frames > tracked_frame then
            tracked_frame, heartbeat, proven = flight.frames, now, true
        end
        if landed then
            -- VFC stops ticking `frames` when flight mode is off, so a parked
            -- vehicle can never produce a fresh heartbeat. While landed, the
            -- per-tick SVD seat overlay plus the world re-verification below
            -- are the freshness proof instead; flying keeps the strict rule.
            heartbeat = now
        elseif not proven or now - heartbeat > max_age then
            return nil, "awaiting fresh VehicleFlight heartbeat"
        end
        local world, world_reason = world_api.open()
        if not world then reset_heartbeat(); return nil, world_reason or "world unavailable" end
        if world_api.entity_exists(world, vehicle.entity) ~= true then
            if landed then cached_vehicle = nil end
            reset_heartbeat(); return nil, "stale vehicle entity"
        end
        if world_api.entity_unit(world, vehicle.entity) ~= vehicle.unit then
            if landed then cached_vehicle = nil end
            reset_heartbeat(); return nil, "vehicle unit mismatch"
        end
        local kind = world_api.entity_type(world, vehicle.entity)
        -- Release 0.40.0 returns a 16-digit HEX STRING, not a descriptor table.
        if type(kind) ~= "string" or kind:upper() ~= MAELSTROM then
            if landed then cached_vehicle = nil end
            reset_heartbeat(); return nil, "vehicle is not the Maelstrom"
        end
        local pose = world_api.unit_pose(world, vehicle.unit)
        if type(pose) ~= "table" or not vector(pose.position) then
            reset_heartbeat(); return nil, "vehicle pose unavailable"
        end
        -- Launch along the hull's forward axis: in the cockpit view the nose
        -- is where the crosshair points. The runtime exposes no camera ray, so
        -- a turret free-look off the nose is not captured (VFC's `aim` field
        -- may carry the look pitch; unproven, under capture in diagnostics).
        local forward = pose.forward
        if not vector(forward) then
            reset_heartbeat(); return nil, "vehicle forward vector unavailable"
        end
        -- World +Z is up. This tunable root offset is NOT a measured
        -- cockpit/wing/hull clearance.
        local position = {x = pose.position.x, y = pose.position.y, z = pose.position.z - clearance}
        if not vector(position) then return nil, "release point out of range" end
        local root = pose.position
        if motion and now > motion.now then
            local dt = now - motion.now
            measured_speed = math.sqrt((root.x-motion.x)^2+(root.y-motion.y)^2
                +(root.z-motion.z)^2) / dt
        end
        if not motion or now > motion.now then
            motion = {x=root.x, y=root.y, z=root.z, now=now}
        end
        vehicle.root_position = {x=root.x, y=root.y, z=root.z}
        vehicle.measured_speed = measured_speed
        vehicle.position, vehicle.direction = position,
            {x = forward.x, y = forward.y, z = forward.z}
        vehicle.frames, vehicle.now, vehicle.flying = flight.frames, now, flight.flying
        vehicle.authority, vehicle.alive = true, true
        -- Deliberately no grounded/in_service_area/in_cockpit fields:
        -- native vehicle identity + VFC status do not prove any of those.
        -- Remember the last fully verified vehicle for the landed fallback.
        cached_vehicle = vehicle
        return vehicle
    end

    -- Poll from a game-update callback with a monotonic seconds clock.
    -- First observation, changed vehicle/status table and gaps require a new frame.
    function self.inspect(now)
        local ok, value, why = pcall(inspect, now, true)
        if not ok then reset_heartbeat(); return nil, "inspection failed: " .. tostring(value) end
        return value, why
    end

    -- Same proofs as inspect(), but permits flight mode OFF for virtual service.
    -- When flight OFF blanks VFC's vehicle text, the last verified vehicle stays
    -- observable while the seat-role overlay is held and frames keep advancing.
    -- A seat first taken while parked (VFC never saw the vehicle) is resolved
    -- by proximity: the unique Maelstrom within `seat_proximity` metres of the
    -- local avatar, still fully re-verified before it is observable.
    function self.inspect_vehicle(now)
        local ok, value, why = pcall(inspect, now, false)
        if not ok then reset_heartbeat(); return nil, "inspection failed: " .. tostring(value) end
        return value, why
    end

    -- Decorative transport Pelican for the landed service presentation only.
    -- Every failure here is a plain refusal: it never sets faulted, never
    -- touches busy, and is never part of the weapon release path.
    -- ctx: {now=..., vehicle_key=..., hover=optional seconds}. Returns the
    -- handle's status string and the handle; nil/false + reason otherwise.
    function self.call_pelican(ctx)
        if type(ctx) ~= "table" then return false, nil, "invalid pelican context" end
        if not finite(ctx.now, 86400) or ctx.now < 0 then
            return false, nil, "invalid pelican clock"
        end
        local allowed, why = authority()
        if not allowed then return false, nil, why end
        local vehicle
        vehicle, why = self.inspect_vehicle(ctx.now)
        if not vehicle then return false, nil, why end
        if ctx.vehicle_key ~= vehicle.vehicle_key then
            return false, nil, "pelican request belongs to another vehicle"
        end
        if type(pelican) ~= "table" or type(pelican.spawn) ~= "function" then
            return false, nil, "pelican API unavailable"
        end
        local root = vehicle.root_position
        local ok, handle = pcall(pelican.spawn, {
            position = {x = root.x, y = root.y, z = root.z},
            hover = ctx.hover or 60, owner = OWNER})
        if not ok then return nil, nil, "pelican request failed: " .. tostring(handle) end
        if type(handle) ~= "table" then return nil, nil, "missing pelican handle" end
        return handle.status, handle
    end

    -- Assets only: never queue a bomb as a way to warm up its packages.
    function self.prewarm()
        local ok, job, why = pcall(function()
            local allowed, reason = authority()
            if not allowed then return nil, reason end
            if faulted then return nil, "adapter faulted" end
            if asset_job then return asset_job end
            local targets = {}
            for _, name in ipairs(STRATAGEMS) do
                targets[#targets + 1] = hd2.stratagem(name)
            end
            local handle, err = hd2.require_assets({id = "eagle-weapon-assets",
                targets = targets})
            asset_job = handle
            return handle, err
        end)
        if not ok then return nil, "asset prewarm failed: " .. tostring(job) end
        return job, why
    end

    local function caller_ready(ctx)
        return type(ctx) == "table" and ctx.in_cockpit == true and ctx.flight_enabled == true
            and ctx.focused == true and ctx.paused == false
    end

    local function spawn(ctx, weapon)
        if not caller_ready(ctx) then
            return false, "logical control seat, flight mode, focus and unpaused state required"
        end
        local vehicle, why = self.inspect(ctx.now)
        if not vehicle then return false, why end
        if ctx.vehicle_key ~= vehicle.vehicle_key then return false, "payload belongs to another vehicle" end
        if type(weapon) ~= "table" or type(weapon.id) ~= "string" or #weapon.id > 40
            or type(weapon.output) ~= "string" or #weapon.output > 200 then
            return false, "invalid weapon spec"
        end
        local def = definitions[weapon.id]
        if not def then
            local code
            local spec = {id = "jacks/eagle_" .. weapon.id, base = weapon.output}
            local donor = SPEED_DONORS[weapon.output]
            if donor then
                spec.changes = {{member = "speed", from = donor}}
            end
            def, code, why = custom.define(spec)
            if not def then return false, tostring(code) .. ": " .. tostring(why) end
            definitions[weapon.id] = def
        end
        -- Define may take time or invoke other callbacks. Revalidate all guards
        -- and resolve the current vehicle pose immediately before requesting.
        if not caller_ready(ctx) then return false, "caller context changed before release" end
        vehicle, why = self.inspect(ctx.now)
        if not vehicle or ctx.vehicle_key ~= vehicle.vehicle_key then
            return false, why or "vehicle changed before release"
        end
        return vehicle, def
    end

    -- Pass a closure over this to the payload controller.
    -- true=requested; false=definitely no projectile; nil=uncertain, no retry.
    function self.spawn_weapon(ctx, weapon)
        if faulted then return nil, "release outcome unknown; adapter faulted" end
        if busy then return false, "release already in progress" end
        busy = true
        local ok, vehicle, extra = pcall(spawn, ctx, weapon)
        if not ok or vehicle == false then
            busy = false
            return false, ok and extra or ("release preparation failed: " .. tostring(vehicle))
        end
        local acted, accepted, reason = pcall(function()
            local action = actions.spawn_custom_projectile(extra, {
                position = vehicle.position, direction = vehicle.direction, owner = OWNER})
            if type(action) ~= "table" then return nil, "missing action handle" end
            if action.status == "requested" then return true, "requested" end
            if action.status == "waiting_for_assets" then
                -- Cancellation is synchronous in this pinned API; its watcher
                -- checks the changed status before it can invoke fire_custom.
                action:cancel()
                if action.status == "cancelled" then return false, "asset wait cancelled; retry with a new press" end
                return nil, "asset wait cancellation not confirmed"
            end
            if action.status == "refused" or action.status == "cancelled" then
                return false, tostring(action.code or action.status) .. ": " .. tostring(action.reason)
            end
            return nil, "unknown action status: " .. tostring(action.status)
        end)
        busy = false
        if not acted or accepted == nil then
            faulted = true
            return nil, acted and reason or ("action outcome unknown: " .. tostring(accepted))
        end
        return accepted, reason
    end

    -- Backwards-compatible single-bomb entry point.
    function self.spawn_bomb(ctx)
        return self.spawn_weapon(ctx, {id = "500kg", output = DEFAULT_BOMB})
    end

    function self.is_faulted() return faulted end
    return self
end

-- Explicit opt-in loader only. Importing this module alone does not require or
-- execute HD2Runtime. Do NOT call in offline tests: use new(mock_dependencies).
function Adapter.load(options)
    local hd2 = require("hd2runtime/api/hd2")
    if hd2.version ~= VERSION or hd2.api_version ~= API then
        return nil, "unsupported HD2Runtime; need 0.40.0/API 1"
    end
    return Adapter.new({
        hd2 = hd2,
        custom = require("hd2runtime/runtime/custom_projectiles"),
        actions = require("hd2runtime/api/actions"),
        world = require("hd2runtime/runtime/event_world"),
        pelican = require("hd2runtime/api/pelican"),
    }, options)
end

return Adapter
