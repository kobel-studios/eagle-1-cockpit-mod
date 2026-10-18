-- Eagle payload controller. This is not a standalone game addon.
-- The game adapter must provide verified vehicle/landing state and a spawn
-- function taking a weapon spec table. Keep one controller per vehicle for
-- its entire life, including seat changes.
local Payload = {}

local function finite(n)
    return type(n) == "number" and n == n and n > -math.huge and n < math.huge
end

-- cfg.weapons is an ordered list of {id, name, output, capacity} specs. A
-- bare cfg.capacity still means a single 500 KG rack for older callers.
local function weapon_specs(options)
    local list = options.weapons
    if list == nil then
        list = {{
            id = options.id or "bomb500",
            name = options.name or "500 KG",
            output = options.output
                or "output/v1/projectile/eagle-500kg-bomb-projectile-239",
            capacity = options.capacity or 2,
        }}
    end
    assert(type(list) == "table", "invalid weapons list")
    local specs = {}
    for index, spec in ipairs(list) do
        assert(type(spec) == "table", "invalid weapon spec")
        assert(type(spec.id) == "string" and #spec.id >= 1 and #spec.id <= 40,
            "invalid weapon id")
        assert(type(spec.name) == "string" and #spec.name >= 1
            and #spec.name <= 40, "invalid weapon name")
        assert(type(spec.output) == "string" and #spec.output >= 1
            and #spec.output <= 200, "invalid weapon output")
        local capacity = spec.capacity
        assert(finite(capacity) and capacity >= 1 and capacity <= 16
            and capacity == math.floor(capacity), "invalid weapon capacity")
        specs[index] = {id = spec.id, name = spec.name, output = spec.output,
            capacity = capacity}
    end
    assert(#specs >= 1 and #specs <= 16, "invalid weapons list")
    return specs
end

function Payload.new(spawn_weapon, options)
    assert(type(spawn_weapon) == "function",
        "a verified weapon adapter is required")
    options = options or {}
    local specs = weapon_specs(options)
    local duration = options.rearm_seconds or 150
    local interval = options.drop_interval or 1
    assert(finite(duration) and duration > 0, "invalid rearm duration")
    assert(finite(interval) and interval > 0, "invalid drop interval")

    local ammo = {}
    for index, spec in ipairs(specs) do ammo[index] = spec.capacity end
    local selected = 1
    local input_seen = false
    local fire_held, rearm_held, select_held = false, false, false
    local previous_time, next_drop = nil, 0
    local service_time = nil
    local uncertain = false
    local busy = false
    local last_status = "ready"
    local service_block_reason = nil
    local self = {}

    local function snapshot()
        -- Completion stays visible until another action changes status. All
        -- fields are informational copies; editing them cannot move ammo.
        local progress_time = service_time
            or (last_status == "rearmed" and duration) or 0
        local current = specs[selected]
        local list = {}
        for index, spec in ipairs(specs) do
            list[index] = {id = spec.id, name = spec.name, output = spec.output,
                ammo = ammo[index], capacity = spec.capacity}
        end
        return {
            weapons = list, selected = selected, selected_name = current.name,
            ammo = ammo[selected], capacity = current.capacity,
            status = last_status,
            rearming = service_time ~= nil,
            firing_locked = service_time ~= nil,
            rearm_remaining = service_time
                and math.max(0, duration - service_time) or 0,
            rearm_elapsed = progress_time, rearm_duration = duration,
            rearm_progress = math.min(1, progress_time / duration),
            service_block_reason = service_block_reason,
            faulted = uncertain,
        }
    end

    function self.state()
        return snapshot()
    end

    function self.update(ctx)
        -- Reserve ammunition before invoking the adapter; a reentrant update
        -- must never create another projectile.
        if busy then return snapshot() end
        assert(type(ctx) == "table", "vehicle context required")
        local fire = ctx.fire == true
        local rearm = ctx.rearm == true
        local select_key = ctx.select == true
        -- On attachment, sample held keys without treating them as new presses.
        local fire_press = input_seen and fire and not fire_held
        local rearm_press = input_seen and rearm and not rearm_held
        local select_press = input_seen and select_key and not select_held
        input_seen = true
        fire_held, rearm_held, select_held = fire, rearm, select_key
        service_block_reason = nil

        if not finite(ctx.now) or ctx.now < 0
            or (previous_time and ctx.now < previous_time) then
            service_time, previous_time = nil, nil
            last_status = "invalid clock"
            service_block_reason = "invalid clock; press Home again after recovery"
            return snapshot()
        end
        local elapsed = previous_time and (ctx.now - previous_time) or 0
        previous_time = ctx.now

        if uncertain then
            service_time = nil
            last_status = "release outcome unknown; weapons disabled"
            service_block_reason = last_status
            return snapshot()
        end
        -- ctx.remote comes only from the entry's out-of-vehicle service path.
        -- It keeps the rearm clock and Home key alive while the player is
        -- away from the seat; weapons and selection stay dead.
        local remote = ctx.remote == true
        if not remote and (ctx.authority ~= true or ctx.in_cockpit ~= true
            or ctx.alive ~= true or ctx.focused ~= true or ctx.paused ~= false) then
            service_time = nil
            last_status = "inactive"
            service_block_reason = "inactive; press Home again after returning"
            return snapshot()
        end

        if not remote then
            if select_press then
                selected = selected % #specs + 1
                last_status = "selected " .. specs[selected].name
            end
            -- A direct weapon key jumps straight to a slot; out of range is ignored.
            local wanted = ctx.select_index
            if wanted ~= nil and type(wanted) == "number"
                and wanted == math.floor(wanted) and wanted >= 1
                and wanted <= #specs and wanted ~= selected then
                selected = wanted
                last_status = "selected " .. specs[selected].name
            end
        end

        -- A rearm run needs a verified landed, stationary vehicle. The old
        -- docked/in_service_area flags are still accepted but now ignored.
        -- Explicit flight mode vetoes a run even if a stale landed flag
        -- says otherwise; speed is checked whenever the adapter reports it.
        local speed = ctx.speed
        if ctx.flight_enabled == true then
            service_block_reason = "switch flight mode off"
        elseif ctx.landed ~= true then
            service_block_reason = "land before starting a rearm run"
        elseif ctx.stationary ~= true then
            service_block_reason = "hold still to rearm"
        elseif speed ~= nil and not finite(speed) then
            service_block_reason = "waiting for measured vehicle speed"
        elseif finite(speed) and speed > 0.5 then
            service_block_reason = "stop to rearm"
        end
        local can_service = service_block_reason == nil
        if service_time ~= nil then
            -- Ground movement no longer cancels a run: the Pelican keeps
            -- serving. Only leaving the ground (flight on / not landed) or a
            -- telemetry gap aborts it; starting still requires parked.
            if ctx.flight_enabled == true or ctx.landed ~= true then
                service_time = nil
                if ctx.flight_enabled == true then
                    last_status = "rearm cancelled: flight mode on"
                else
                    last_status = "rearm cancelled: left ground"
                end
                return snapshot()
            end
            -- A long gap is not evidence the plane remained parked.
            if elapsed > 1 then
                service_time = nil
                last_status = "rearm cancelled: missing updates"
                service_block_reason = "missing updates; press Home to restart"
                return snapshot()
            end
            service_time = service_time + elapsed
            if service_time >= duration then
                for index, spec in ipairs(specs) do
                    ammo[index] = spec.capacity
                end
                service_time = nil
                last_status = "rearmed"
            elseif fire_press then
                last_status = "weapons safe during rearm"
            else
                last_status = "rearm run inbound"
            end
            return snapshot()
        end

        if rearm_press then
            if not can_service then
                last_status = "landed and stationary required"
            else
                local full = true
                for index, spec in ipairs(specs) do
                    if ammo[index] < spec.capacity then
                        full = false
                        break
                    end
                end
                if full then
                    last_status = "already full"
                else
                    service_time = 0
                    last_status = "rearm run inbound"
                end
            end
            return snapshot()
        end

        if not fire_press then return snapshot() end
        local current = specs[selected]
        if ammo[selected] == 0 then
            last_status = "out of " .. current.name
            return snapshot()
        end
        -- One shared interval gates every weapon so cycling cannot release
        -- the whole loadout faster than a single rack ever could.
        if ctx.now < next_drop then
            last_status = "release interval"
            return snapshot()
        end
        -- "grounded" and "landed" come from different adapter generations.
        -- Any positive ground report vetoes release; at least one explicit
        -- airborne report is required to permit it.
        local on_ground = ctx.grounded == true or ctx.landed == true
        local airborne = not on_ground
            and (ctx.grounded == false or ctx.landed == false)
        if not airborne then
            last_status = "take off before releasing " .. current.name
            return snapshot()
        end

        ammo[selected] = ammo[selected] - 1
        busy = true
        local ok, accepted = pcall(spawn_weapon, {
            id = current.id, name = current.name,
            output = current.output, capacity = current.capacity})
        busy = false
        -- Adapters answer a table with .status or a legacy bare value.
        local status = ok and type(accepted) == "table" and accepted.status
            or accepted
        if ok and (status == "requested" or accepted == true) then
            next_drop = ctx.now + interval
            last_status = current.name .. " released"
        elseif ok and (status == "rejected" or accepted == false) then
            -- Adapter must reject only when NO projectile was created.
            ammo[selected] = ammo[selected] + 1
            last_status = "release rejected"
        else
            -- An exception or uncertain result might occur after spawning.
            -- Do not refund and retry, which could duplicate projectiles.
            uncertain = true
            last_status = "release outcome unknown; weapons disabled"
        end
        return snapshot()
    end

    return self
end

return Payload
