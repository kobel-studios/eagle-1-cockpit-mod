# VFC cockpit bridge: offline findings

This is an inspector, not an installed mod. No Lua bytecode, native FFI code,
game process, or Arsenal operation was executed. No dependencies were downloaded.
Guardian scanned the original wrapper: no local findings, **UNKNOWN** because
VirusTotal is not configured. That is not clearance to execute the wrapper.

## Reproduce from HQ

```text
python -m unittest discover -s downloads/hd2-mods/vfc_inspect -p "test*.py"
python downloads/hd2-mods/vfc_inspect/inspect_lj.py downloads/hd2-mods/extracted/vfc/12970356483147164383.lua/toc.bin
```

`listing.txt` is the complete static instruction/constant listing. Its line numbers
below refer to that generated file. Prototype IDs are assigned in dump order.
Instruction PCs begin at 1. Original bytecode has stripped source debug lines,
so these are bytecode locations, not invented Lua source line numbers.

Input: `extracted/vfc/12970356483147164383.lua/toc.bin`, 148309 bytes,
SHA256 `abc28461aecb613afa24cb5662feef1cf97c9cd2ea82e332cb4567fb0ba93fb2`.
The eight-byte envelope precedes a literal escaped LuaJIT v2 dump, 37028 bytes,
103 prototypes. Every prototype boundary and the final terminator parsed exactly.
The wrapper's final `loadstring` and call were never executed.

## Actual exported interface

**`_G.VehicleFlight` is a status table, NOT the controller or config.**

- Root prototype 102 PC 393 receives the controller. PCs 394–399 select its
  `.state` and `rawset(_G, "VehicleFlight", state)` (listing 6804–6810).
- Prototype 60 creates the status table (4848–4913). Fields include `rev`,
  `flying`, `precision`, `frames`, `flights`, `speed`, `alt`, `pitch`, `roll`,
  `zoom`, `vehicle`, `tmpl`, `aim`, `dist`, `api`, `axis`, `mode`, `phase`,
  `status`, `why`, `errors`, `sets`, `flips`, and `impacts`.
- Internal controller has `state`, `R`, `S`, `gate()`, `tick()`, `stop()`
  (4974–4985); it is held in local closures, not assigned to the global.
- The config is a separate shallow copy of defaults (prototype 69, 5247–5258).
  Writing `VehicleFlight.zoom` therefore does NOT set the config zoom.
  The tick copies config zoom to state, not the other way around (4759–4777).
- Revision string is `vehicle-flight-1.0.1` (6226).

**No public cockpit setter, camera transform, seat-switch function, or update
subscription method was found.** Do not invent `VehicleFlight.config`,
`VehicleFlight.set_camera`, or `VehicleFlight.tick` as usable APIs.

## Existing settings and camera behavior

Local defaults (6286, instantiated at 6575):

- `zoom=13`, `zoom_rate=0.8`, `zoom_only_flying=true`
- `cam_lift=0.12`, `cam_pitch=85`, `camera_fix=true`, `pivot_center=true`
- `key_zoom_in=109`, `key_zoom_out=107` (Windows numpad minus/plus)
- `key_toggle=73` (I), `key_freelook=0` (unbound default).

Only these five Mod Options Menu options are declared (6296–6310):

| Key | Default | Bounds |
| --- | --- | --- |
| `vfc.enabled` | true | toggle |
| `vfc.turn` | 200 | 50–400, step 10 |
| `vfc.roll` | 100 | 25–300, step 5 |
| `vfc.cam_height` | 12 | 0–40, step 1 |
| `vfc.flip_damage` | true | toggle |

Prototype 66 registers these using `ModOptionsMenu.register_option(key, spec)`
under `pcall` (5109–5170). Prototype 67 polls `ModOptionsMenu.get(key)` and
applies validated values (5172–5225). No menu setter API is proven by this.
Prototype 99 applies options approximately every 0.2 seconds (6090–6098).

Camera height callback prototype 64 validates a non-NaN number, clamps to 0–40,
divides by 100, and sets private `cam_lift` (5067–5094).
Its help text explicitly describes a raised third-person line of sight.
It is not cockpit position.

Camera editor prototype 46 (2529–2856) saves originals and edits native camera
template memory via private helpers:

- PCs 158–180 multiply each saved camera boom component by private `zoom`
  (2723–2745). Zoom is a scale, not proven distance in meters or FOV.
- While flying, `camera_fix` permits pitch limits ±`cam_pitch`, yaw ±180,
  and a native identity byte change (2752–2804).
- `pivot_center` zeros three pivot components (2805–2825).
- Vertical adjustment combines the original pivot/up, `cam_lift`, saved boom,
  and zoom (2826–2849).
- Keyboard zoom uses exponential scaling, clamped **0.5–50**
  (4759–4777). Zero boom/first-person is not reachable through that clamp.
- Prototype 48 restores camera edits (2898–3042). Shutdown calls controller
  stop, restores the prior update if still its own, and clears the global
  (6170–6213). This is evidence of intended cleanup, not runtime verification.

## Update hook and seat evidence

Root captures existing global `update` and `shutdown` (6862–6863). It requires
`update` to be a function, otherwise stops with `STOPPED: no update callback`.
It installs wrapper prototypes 100/101 (6876–6881).
Prototype 100 calls the old update under `pcall`, then passes the results to
prototype 99 (6154–6168). Prototype 99 runs the private controller tick,
records errors, stops on failure, and rejects after five errors (6054–6152).
This is global callback wrapping, not an independently exposed VFC hook.
Blindly replacing `update` risks breaking VFC and other mods.

The option help explicitly says driver seat OR **Solo Vehicle Driver pilot seat**
(6297). There is native seat/role handling, but this does not establish Eagle
seat creation, pilot/gunner switching, weapon controls, or network authority.

## Feasibility verdict

Read-only VFC telemetry is a plausible bridge once the game/BSL version is
validated. Existing menu camera-height adjustment is the only identified
high-level camera control; keyboard zoom remains third-person template scaling.

**A safe first-person cockpit bridge is blocked on a supported camera API or
an upstream VFC change.** Needed: an explicit versioned camera-mode/seat-transform
setter, lifecycle cleanup, and an update registration contract. Alternatively,
obtain readable source/author support to add those APIs inside VFC rather than
extract private closure state or copy native offsets into a second addon.

Do not claim that setting height to zero creates a cockpit. Even zero boom
would not prove an interior model, correct seat transform, visibility/clipping,
weapons aiming, or camera collision behavior.

The listing contains original native constants only as evidence; none were
copied into executable bridge code. No working cockpit, pilot/gunner switching,
bomb spawning, or rearm integration is delivered here.

## Verification limitations

Focused tests cover literal-only decoding, malformed/truncated input, flag
rejection, opcode display, no Python `exec`, and the hash-pinned real fixture.
These tests do not prove game compatibility or validate native memory layouts.

The automatic verifier initially had stale results, then caught a test-module
import that depended on the test runner's search path. Tests now load the
sibling inspector by its explicit local path. Final watcher results must be
checked separately from the focused test result.
Focused suite: four tests passed. The corrected test module passed the watcher
syntax check; it intentionally did not import/run the tests.
