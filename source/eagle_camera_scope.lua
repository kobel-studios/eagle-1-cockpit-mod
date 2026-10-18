-- Scope AdvancedTankCamera's SUPPORTED, hot-reloaded INI to the logical pilot.
-- Only pass the current adapter.inspect_vehicle(now) result; never a VFC table,
-- cached snapshot or boolean. The adapter proves Maelstrom identity/freshness;
-- these structural checks cannot independently prove engine state.
-- Call update(nil) on every invalid context/exit/session change, and stop() on
-- shutdown. Methods use dots, not colons. Check their (ok, reason) returns.
-- INI reload is asynchronous: this does NOT promise instant camera changes or
-- true cockpit eye geometry. Existing eye_height=120/eye_forward=0 may clip.
local Scope = {}
local keys = {
    -- AVP only engages first person at distance <= 30; 60 gave a close
    -- third-person view where the user saw their own body in the seat.
    {section="camera", key="distance", normal="100", active="25", low=25, high=5000},
    {section="first_person", key="enabled", normal="0", active="1", low=0, high=1},
    -- Cockpit eye: ~1.15 m up, ~0.6 m ahead of the seat pivot - inside the
    -- canopy. 220 cm forward put the eye past the nose: the "weird angle".
    {section="first_person", key="eye_height", normal="120", active="115", low=-100, high=300},
    {section="first_person", key="eye_forward", normal="0", active="60", low=-300, high=300},
    -- Never enable the generic vehicle camera: it also captured on-foot tmpl57.
    {section="vehicles", key="enabled", normal="0", active="0", low=0, high=1},
    {section="vehicles", key="distance", normal="100", active="100", low=25, high=5000},
}

local function integer(n, low, high)
    return type(n)=="number" and n==n and n>=low and n<=high and n==math.floor(n)
end

local function valid(snapshot)
    return type(snapshot)=="table"
        and snapshot.authority==true and snapshot.alive==true
        and snapshot.role==4 and type(snapshot.flying)=="boolean"
        and integer(snapshot.entity, 1, 4294967295)
        and integer(snapshot.unit, 1, 4294967295)
        and snapshot.vehicle_key==string.format("%d:%08X", snapshot.entity, snapshot.unit)
        and integer(snapshot.frames, 1, 9007199254740991)
        and type(snapshot.now)=="number" and snapshot.now>=0
        and snapshot.now<math.huge
end

-- Keep the original byte stream, including CRLF, spacing, comments and EOF.
-- Refuse ambiguous/missing owned sections or keys rather than guessing.
local function parse(text)
    if type(text)~="string" or #text==0 or #text>1024*1024 or text:find("%z") then
        return nil, "missing or invalid camera INI"
    end
    local lines, found, sections, section = {}, {}, {}, nil
    local start = 1
    while start<=#text do
        local ending = text:find("\n", start, true)
        local line = text:sub(start, ending or #text)
        lines[#lines+1] = line
        local body = line:gsub("[\r\n]+$", "")
        if start==1 then body=body:gsub("^\239\187\191", "") end
        local name, section_tail = body:match("^%s*%[([^%]]+)%](.*)$")
        if name then
            if not (section_tail:match("^%s*$") or section_tail:match("^%s*[;#]")) then
                return nil, "malformed INI section suffix"
            end
            section=name:match("^%s*(.-)%s*$"):lower()
            if section=="camera" or section=="first_person" or section=="vehicles" then
                if sections[section] then return nil, "duplicate owned INI section" end
                sections[section]=true
            end
        elseif body:match("^%s*%[") then
            return nil, "malformed INI section"
        else
            local key=body:match("^%s*([%w_]+)%s*=")
            for i, spec in ipairs(keys) do
                if section==spec.section and key and key:lower()==spec.key then
                    if found[i] then return nil, "duplicate owned INI key" end
                    local prefix, digits, tail = line:match("^(%s*[%w_]+%s*=%s*)(%d+)(.*)$")
                    local suffix=tail and tail:gsub("[\r\n]+$", "") or ""
                    if not digits or not (suffix:match("^%s*$") or suffix:match("^%s*[;#]"))
                        or not integer(tonumber(digits), spec.low, spec.high) then
                        return nil, "invalid owned INI value: "..spec.section.."."..spec.key
                    end
                    found[i]={line=#lines, prefix=prefix, suffix=tail, value=digits}
                end
            end
        end
        start=ending and ending+1 or #text+1
    end
    for i, spec in ipairs(keys) do
        if not found[i] then return nil, "missing INI key: "..spec.section.."."..spec.key end
    end
    return {lines=lines, found=found}
end

-- deps.read() -> bytes, reason
-- deps.write(expected_bytes, replacement_bytes) -> true OR false, reason.
-- write MUST NOT commit when expected bytes no longer match. A thrown error
-- leaves the outcome uncertain; the controller blocks activation and reports it.
-- Construction performs one normal-camera reset. No per-frame filesystem IO.
function Scope.new(deps, options)
    options=options or {}
    if type(deps)~="table" or type(deps.read)~="function" or type(deps.write)~="function" then
        return nil, "camera scope needs read and compare-and-replace write"
    end
    local cap=options.cleanup_attempts or 3
    if not integer(cap, 1, 5) then return nil, "cleanup_attempts must be 1..5" end
    -- A short invalid stretch keeps the camera where it is: VFC republishes
    -- its status table and the seat overlay blips, and one bad tick must not
    -- rewrite the INI and visibly bounce between first and third person.
    -- Only meaningful when update() gets a monotonic `now`; without one the
    -- old immediate behaviour is kept.
    local hold=options.hold_seconds or 0.6
    if type(hold)~="number" or hold~=hold or hold<0 or hold>2 then
        return nil, "hold_seconds must be 0..2"
    end
    local self={active=nil, status="starting", faulted=false, stopped=false}
    local last, pending, relinquished, failures, settled = nil, nil, {}, 0, false
    local last_valid

    local function report(ok, reason)
        if self.status~=reason and type(deps.log)=="function" then pcall(deps.log, reason) end
        self.status=reason
        return ok, reason
    end

    local function failed(reason)
        self.faulted, self.active, settled = true, nil, false
        failures=failures+1
        return report(false, "camera INI write/reset failed; first person may remain active: "
            ..tostring(reason)..(failures>=cap and " (retry limit reached)" or ""))
    end

    local function apply(active)
        local ok, text, why=pcall(deps.read)
        if not ok then return failed(text) end
        local parsed, problem=parse(text)
        if not parsed then return failed(why or problem) end
        if not self.original then self.original=text end
        local conflict=false
        if last then
            for i, record in ipairs(parsed.found) do
                if relinquished[i] or (record.value~=last[i]
                    and not (pending and pending[i] and pending[i][record.value])) then
                    relinquished[i], conflict=true, true
                end
            end
        end
        -- A manual edit of an owned setting stops automatic activation.
        -- Restore the other owned settings, never overwrite the manual edit.
        if conflict then self.faulted=true; active=false end
        local values={}
        for i, record in ipairs(parsed.found) do
            local value=record.value
            if not relinquished[i] then value=active and keys[i].active or keys[i].normal end
            values[i]=value
            parsed.lines[record.line]=record.prefix..value..record.suffix
        end
        local replacement=table.concat(parsed.lines)
        if replacement~=text then
            local called, written, reason=pcall(deps.write, text, replacement)
            -- A callback that threw after committing may have installed these
            -- values. Cleanup may restore them, not mistake them for user edits.
            if not called then
                pending=pending or {}
                for i, value in ipairs(values) do
                    pending[i]=pending[i] or {}
                    pending[i][value]=true
                end
            end
            if not called or written~=true then return failed(called and reason or written) end
        end
        last, pending, failures, settled=values, nil, 0, true
        self.active=active
        if conflict then
            -- A manually enabled first_person value is not ours to undo.
            if tonumber(values[2])~=0 then self.active=nil end
            return report(false, "camera scope disabled: manual owned-key edit preserved; "
                .."only unchanged owned settings reset")
        end
        return report(true, active and "Eagle first-person INI requested (reload pending)"
            or "normal camera INI requested (reload pending)")
    end

    function self.update(snapshot, now)
        if self.stopped then return false, "camera scope stopped: "..self.status end
        local active=not self.faulted and valid(snapshot) or false
        if type(now)=="number" and now==now then
            if active then
                last_valid=now
            elseif self.active and last_valid
                and now>=last_valid and now-last_valid<hold then
                active=true
            end
        end
        if settled and (self.faulted or self.active==active) then
            return not self.faulted, self.status
        end
        if failures>=cap then return false, self.status end
        return apply(active)
    end

    function self.stop()
        -- Explicit repeated stop calls can retry failed cleanup up to the cap.
        if self.stopped and settled then return not self.faulted, self.status end
        self.stopped=true
        if failures>=cap then return false, self.status end
        return apply(false)
    end

    apply(false)
    return self
end

-- Windows CRT rename cannot replace an existing file. Use documented Win32
-- FILESYSTEM calls through LuaJIT, never engine addresses/offsets or closures.
-- If FFI is unavailable, refuse writes rather than delete the live INI first.
local function atomic_replacer()
    if package.config:sub(1,1)~="\\" then return os.rename end
    local ok, ffi=pcall(require, "ffi")
    if not ok then return nil, "LuaJIT FFI unavailable for atomic Windows file replacement" end
    local loaded, kernel=pcall(function()
        ffi.cdef[[
            int __stdcall eagle_camera_scope_v1_MoveFileExA(
                const char *existing, const char *destination,
                unsigned long flags) __asm__("MoveFileExA");
            unsigned long __stdcall eagle_camera_scope_v1_GetLastError(void)
                __asm__("GetLastError");
        ]]
        return ffi.load("kernel32")
    end)
    if not loaded then return nil, "Windows file replacement unavailable: "..tostring(kernel) end
    return function(source, destination)
        -- MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH. Both paths are
        -- in the same directory/volume; never fall back to remove+rename.
        if kernel.eagle_camera_scope_v1_MoveFileExA(source, destination, 9)~=0 then return true end
        return nil, "MoveFileExA error "..tonumber(kernel.eagle_camera_scope_v1_GetLastError())
    end
end

local function load(options)
    options=options or {}
    local base=os.getenv("LOCALAPPDATA")
    if type(base)~="string" or base=="" then return nil, "LOCALAPPDATA unavailable" end
    local path=base.."/CowboyBingus/Helldivers2/Logs/AdvancedTankCamera.ini"
    local function read()
        local file, why=io.open(path, "rb")
        if not file then return nil, why end
        local text, problem=file:read("*a")
        file:close()
        return text, problem
    end
    local text, why=read()
    local parsed, problem=parse(text)
    if not parsed then return nil, why or problem end
    local replace, reason=atomic_replacer()
    if not replace then return nil, reason end
    local nonce=tostring({}):gsub("[^%w]", "").."."..tostring(os.time())
    local prefix=base.."/CowboyBingus/Helldivers2/Logs/.eagle-camera-scope."..nonce
    local backup, temp=prefix..".original.bak", prefix..".tmp"
    local backed_up=false
    local function create(filename, bytes)
        -- Own unique prefix, never reuse or overwrite another instance's file.
        local existing=io.open(filename, "rb")
        if existing then existing:close(); return false, "scope sidecar already exists" end
        local file, error_message=io.open(filename, "wb")
        if not file then return false, error_message end
        local wrote, write_error=file:write(bytes)
        local closed, close_error=file:close()
        if not wrote or not closed then
            os.remove(filename)
            return false, write_error or close_error
        end
        return true
    end
    local function write(expected, replacement)
        if read()~=expected then return false, "concurrent INI edit before staging" end
        if not backed_up then
            local saved, error_message=create(backup, expected)
            if not saved then return false, "original backup failed: "..tostring(error_message) end
            backed_up=true
        end
        local staged, error_message=create(temp, replacement)
        if not staged then return false, "staging failed: "..tostring(error_message) end
        -- Best-effort compare-and-replace: an external writer can still race
        -- between this second read and the atomic rename. No filesystem CAS
        -- primitive is available here. Never claim this gap is eliminated.
        if read()~=expected then
            os.remove(temp)
            return false, "concurrent INI edit before replacement"
        end
        local committed, commit_error=replace(temp, path)
        if not committed then os.remove(temp); return false, commit_error end
        return true
    end
    local self, error_message=Scope.new({read=read, write=write, log=options.log}, options)
    if self then self.path, self.backup_path=path, backup end
    return self, error_message
end

function Scope.load(options)
    -- A loader sandbox or failed filesystem API must not break the payload.
    local ok, value, reason=pcall(load, options)
    if not ok then return nil, "camera scope load failed: "..tostring(value) end
    return value, reason
end

return Scope
