-- HD2-Addon: mods/jacks/eagle_camera_diagnostics
-- Read existing mod status tables only. No native memory or gameplay writes.
if rawget(_G, "EagleCameraDiagnostics") then return end
local loader = rawget(_G, "CowboyBingusModLoader")
if type(loader) ~= "table" or type(loader.open_log) ~= "function" then return end
local ok, log = pcall(loader.open_log, "EagleCameraDiagnostics.log")
if not ok or not log then return end

local status = {revision = "camera-experiment-0.3", samples = 0, stopped = false}
local old_update, old_shutdown = rawget(_G, "update"), rawget(_G, "shutdown")
local frames, last_line = 0, nil
local update_wrapper, shutdown_wrapper
local unpack_results = unpack
local function pack(...) return {n = select("#", ...), ...} end

local function write(line)
    log:write(line .. "\n")
    log:flush()
end

local function fields(name)
    local t = rawget(_G, name)
    if type(t) ~= "table" then return name .. "=unavailable" end
    local parts = {}
    for _, key in ipairs({"rev", "revision", "phase", "status", "why", "flying",
                          "vehicle", "tmpl", "zoom", "errors", "conflicts",
                          "enabled", "active", "frames", "aim", "pitch", "roll",
                          "dist", "speed", "alt", "mode", "sets", "impacts"}) do
        local value = rawget(t, key)
        if type(value) == "string" or type(value) == "number"
            or type(value) == "boolean" then
            parts[#parts + 1] = key .. "=" .. tostring(value):gsub("[\r\n]", " "):sub(1, 160)
        end
    end
    return name .. "{" .. table.concat(parts, ",") .. "}"
end

local function sample()
    local line = fields("VehicleFlight") .. " " .. fields("AdvancedTankCamera")
        .. " " .. fields("SoloVehicleDriver")
    if line ~= last_line then
        write(line)
        last_line = line
        status.samples = status.samples + 1
    end
end

local function close()
    if status.stopped then return end
    status.stopped = true
    pcall(function() log:close() end)
end

local wrote = pcall(write, "Eagle camera experiment 0.3; read-only telemetry. "
    .. "Template 26 supports AVP first person. Bombs/rearm are NOT connected. "
    .. "Adds VFC frames/aim/pitch/roll/dist/speed/alt capture at 0.1 s cadence.")
if not wrote or type(old_update) ~= "function" then close(); return end

update_wrapper = function(...)
    -- Original game/mod errors propagate; original return values are preserved.
    local results = pack(old_update(...))
    if not status.stopped then
        frames = frames + 1
        if frames == 1 or frames % 6 == 0 then
            if not pcall(sample) then close() end
        end
    end
    return unpack_results(results, 1, results.n)
end

shutdown_wrapper = function(...)
    pcall(sample)
    close()
    if rawget(_G, "update") == update_wrapper then _G.update = old_update end
    if rawget(_G, "shutdown") == shutdown_wrapper then _G.shutdown = old_shutdown end
    if type(old_shutdown) == "function" then return old_shutdown(...) end
end

_G.EagleCameraDiagnostics = status
_G.update, _G.shutdown = update_wrapper, shutdown_wrapper
