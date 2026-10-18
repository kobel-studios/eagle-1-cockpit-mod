-- HD2-Addon: mods/devin/eagle_probe
-- Read-only environment probe. Writes EagleProbe.log; touches nothing else.
local log
do
    local loader = rawget(_G, "CowboyBingusModLoader")
    if loader and loader.open_log then
        log = loader.open_log("EagleProbe.log")
    end
end
local function w(...)
    if not log then return end
    local n = select("#", ...)
    local parts = {}
    for i = 1, n do parts[i] = tostring(select(i, ...)) end
    log:write(table.concat(parts, " "), "\n")
end

local function dump(name, t, maxn)
    local tt = type(t)
    w(name, "type:", tt, "value:", t)
    if tt ~= "table" then return end
    local n = 0
    for k, v in pairs(t) do
        n = n + 1
        if n > (maxn or 200) then w(name, "... truncated") return end
        w("  ", name, ".", k, "=", type(v), v)
    end
    w(name, "entries:", n)
end

local ok, err = pcall(function()
    w("eagle_probe start")
    dump("stingray", rawget(_G, "stingray"), 300)
    local st = rawget(_G, "stingray")
    if type(st) == "table" then
        for _, name in ipairs({ "World", "Unit", "Application", "Level", "Entity",
                                "Gui", "Vector3", "Quaternion", "Matrix4x4",
                                "PhysicsWorld", "Actor", "FlowCallbacks" }) do
            dump("stingray." .. name, st[name], 120)
        end
        local W = st.World
        if type(W) == "table" then
            for _, fn in ipairs({ "spawn_unit", "destroy_unit", "units",
                                  "spawn_scene", "name" }) do
                w("World." .. fn, "=", W[fn])
            end
        end
        local U = st.Unit
        if type(U) == "table" then
            for _, fn in ipairs({ "node", "world_pose", "set_local_pose",
                                  "flow_event", "num_nodes", "node_name" }) do
                w("Unit." .. fn, "=", U[fn])
            end
        end
    end
    local pl = rawget(_G, "package")
    if type(pl) == "table" and type(pl.loaded) == "table" then
        for name in pairs(pl.loaded) do
            w("package.loaded:", name)
        end
    end
    for _, g in ipairs({ "update", "shutdown", "render", "update_paused",
                         "init", "level" }) do
        w("_G." .. g, "=", type(rawget(_G, g)), rawget(_G, g))
    end
    w("eagle_probe end")
end)
w("probe pcall ok:", ok, "err:", err)
if log then pcall(function() log:close() end) end
