-- Mission service marker. Uses a chosen position, not a physical docking API.
-- Mark while on foot and stationary for three observed seconds. To service,
-- stop within eight metres horizontally/two vertically and switch flight off.
local Service = {}

local function finite(n)
    return type(n) == "number" and n == n and n > -math.huge and n < math.huge
end
local function position(p)
    return type(p) == "table" and finite(p.x) and finite(p.y) and finite(p.z)
end
local function copy(p) return {x = p.x, y = p.y, z = p.z} end
local function distance2(a, b)
    return (a.x - b.x)^2 + (a.y - b.y)^2 + (a.z - b.z)^2
end

function Service.new()
    local marker, anchor, last_time, stationary = nil, nil, nil, 0
    local self = {}

    function self.observe(now, p, on_foot)
        if not finite(now) or not position(p) or on_foot ~= true then
            anchor, last_time, stationary = nil, nil, 0
            return
        end
        local dt = last_time and now - last_time or 0
        if dt < 0 or dt > 1 or not anchor or distance2(p, anchor) > 0.25^2 then
            anchor, stationary = copy(p), 0
        else
            stationary = stationary + dt
        end
        last_time = now
    end

    function self.mark(now)
        if marker then return false, "service point already set for this mission" end
        if not finite(now) or not last_time or now - last_time < 0
            or now - last_time > 0.5 or stationary < 3 then
            return false, "stand still on foot for three seconds"
        end
        marker = copy(anchor)
        return true, "service point set"
    end

    function self.point()
        return marker and copy(marker) or nil
    end

    -- Display-only navigation, using the same checks as docking. Offsets point
    -- FROM the plane TO the marker in world coordinates, not compass headings.
    -- Nothing here proves physical ground contact or a real destroyer dock.
    function self.describe(p, flying, speed)
        local result = {
            marked = marker ~= nil, docked = false, within_zone = false,
            horizontal_radius = 8, vertical_tolerance = 2, speed_limit = 0.5,
        }
        local function blocked(code, reason)
            result.reason_code, result.reason = code, reason
            return result
        end
        if not marker then
            return blocked("unmarked", "mark a service point on foot with Insert")
        end
        if not position(p) then
            return blocked("position_unknown", "vehicle position unavailable")
        end
        local dx, dy, dz = marker.x - p.x, marker.y - p.y, marker.z - p.z
        local horizontal = math.sqrt(dx^2 + dy^2)
        if not finite(horizontal) or not finite(dz) then
            return blocked("position_unknown", "vehicle position unavailable")
        end
        result.offset = {x = dx, y = dy, z = dz}
        result.horizontal_distance, result.vertical_offset = horizontal, dz
        result.within_zone = horizontal <= 8 and math.abs(dz) <= 2
        if horizontal > 8 then
            return blocked("too_far", "return to the service point")
        end
        if math.abs(dz) > 2 then
            return blocked("wrong_height", "match the service point height")
        end
        if flying ~= false then
            return blocked("flight_enabled", "switch flight mode off")
        end
        if not finite(speed) or speed < 0 then
            return blocked("speed_unknown", "waiting for measured vehicle speed")
        end
        if speed > 0.5 then
            return blocked("moving", "stop at the service point")
        end
        result.docked = true
        return blocked("ready", "parked at service point; Home to rearm")
    end

    function self.docked(p, flying, speed)
        return self.describe(p, flying, speed).docked
    end

    return self
end

return Service
