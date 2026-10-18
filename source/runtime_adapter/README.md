# Eagle weapon Runtime adapter — offline candidate

**Not installed, packaged, or tested in Helldivers 2.** This is a reusable
adapter, not a complete cockpit mod. The adapter itself neither binds a key nor starts a timer.
It does not change the primary payload controller, camera, registry, vanilla
projectile rows, or game files.

**Credit:** This adapter relies on **HD2Runtime by SkyeShade**:
<https://github.com/SkyeShade/HD2Runtime>. Retain that attribution and follow
the upstream license when distributing a mod using the Runtime. No upstream
Lua source or native-address tables are included in this adapter.

## Files and safe tests

- `eagle_runtime_adapter.lua`: Lua 5.1 module, loaded without side effects.
- `test_adapter.py`: 35 offline test cases, including failure/cancellation paths.
- `inspect_release.py`: prints source from the pinned archive as **text only**.
  It verifies the archive SHA-256 first. It does not execute its contents.

From `C:\Users\jacks\HQ`:

```text
python -m unittest discover -s downloads/hd2-mods/runtime_adapter -v
python -m unittest discover -s downloads/hd2-mods/tests -p test_eagle_payload_entry.py -v
python downloads/hd2-mods/runtime_adapter/inspect_release.py hd2runtime/runtime/custom_projectiles --start 115 --end 190
```

Tests use the already installed `downloads/hd2-mods/test_runtime/lupa.lua51`.
They execute only our module and mocks. They do **not** load HD2Runtime or the
SDK builder. Mock passes do not prove a projectile spawns, looks right, or does
the correct damage in game.

## Exact caller interface

All instance functions use **dot calls**, not colon calls:

```lua
local adapter = Adapter.new({
    hd2 = hd2,       -- require("hd2runtime/api/hd2")
    custom = custom,-- require("hd2runtime/runtime/custom_projectiles")
    actions = actions, -- require("hd2runtime/api/actions")
    world = world,  -- require("hd2runtime/runtime/event_world")
    -- read_flight = function() return _G.VehicleFlight end -- default
}, {
    clearance = 4,          -- world metres below vehicle ROOT, allowed 1..30
    max_status_age = 0.25,  -- seconds, >0 and <=1
    control_role = 4,       -- conservative role gate; verify actual driver role
    seat_proximity = 10,    -- metres, >0 and <=30: parked first-entry scan radius
})
```

`Adapter.load(options)` explicitly requires these real modules and then calls
`new`. Do not call it from offline tests. It refuses other Runtime versions.
Requiring the adapter alone does not require the Runtime.

1. `adapter.inspect(now)` returns a flying `snapshot` or `nil, reason`.
   `adapter.inspect_vehicle(now)` has the same proofs but also accepts
   `flying=false` for parked/virtual-service observations.
   - `now` must be a monotonic seconds clock from the caller's update loop.
   - Poll every update, including while idle. First observation, changed status
     table, changed vehicle/seat text, decreasing frame counter, or a polling gap
     longer than the age limit requires another observation with an increased
     VFC frame count. A frozen counter expires too.
   - Snapshot includes `vehicle_key`, `entity`, `unit`, `actor_hex`, `seat_hex`,
     `role`, `position`, `root_position`, `measured_speed`, `direction`,
     `frames`, `now`, `authority=true`, `alive=true`, and `flying`.
     Speed is distance between successive actual root positions divided by
     observed time, not VFC's displayed speed. It is nil until two valid
     position samples are available and resets on identity/gap/heartbeat resets.
   - Parked first entry: when flight mode is off, VFC blanks the vehicle text.
     While the SoloVehicleDriver seat overlay reports held, the last verified
     vehicle is reused; when none exists yet, a health-record scan finds the
     unique Maelstrom within `seat_proximity` metres of the local avatar and
     the unchanged entity/unit/type/pose checks verify it. Two Maelstroms in
     range, a missing avatar pose, or any verification failure is refused.
     A cold parked entry (no camera ever attached) reports `tmpl=-1`; only
     that exact sentinel relaxes the template check, only for the parked
     path, and only while the seat overlay is held. `inspect()` (flying)
     still requires template 26 with live vehicle identity.
     Proximity cannot see which seat is held: a seat held in another vehicle
     within the radius of a Maelstrom can bind that Maelstrom. Weapon release
     still requires `inspect()` (flying + live VFC identity), so only parked
     rearm/HUD state could ever attach to the wrong tank.
   - It deliberately does **not** supply `in_cockpit`, `grounded`,
     `in_service_area`, or landing speed. Those need separate proof.
2. `adapter.prewarm()` returns the asset-job handle or `nil, reason`.
   - Uses `hd2.require_assets({id="eagle-weapon-assets", targets={...}})` for
     the seven supported stratagems: Eagle 500kg Bomb, Airstrike, Cluster
     Bomb, Napalm Airstrike, 110mm Rocket Pods, Gas Airstrike, Smoke Strike.
   - Requires a matched build, mission host, and a living non-downed local
     player. It does not require flight, so it can be called before takeoff.
   - Requests **assets only**, never a queued projectile. Reuses its first
     returned job. A failed job or mission change needs caller-managed
     lifecycle review, not repeated speculative loading.
3. `adapter.spawn_weapon(ctx, weapon)` is the primary release entry point;
   the payload entry wraps it for `Payload.new(...)`.
   - Required caller fields: `now`, matching `vehicle_key`,
     `in_cockpit=true`, `flight_enabled=true`, `focused=true`, `paused=false`.
   - `weapon` must be a table with string `id` (max 40 chars) and string
     `output` (max 200 chars); anything else is refused before defining.
   - `in_cockpit` means the logical control seat verified by fresh VFC template
     26/configured role plus native vehicle identity. It does not claim a
     physical eye/cockpit camera position. `flight_enabled` is a mode policy;
     no unknown physical ground-contact measurement is required or fabricated.
   - Rechecks current VFC status, build, native entity, unit, type, pose, host,
     mission and player life. Rechecks again after defining the projectile.
   - Defines `{id="jacks/eagle_"..weapon.id, base=weapon.output}`, cached per
     weapon id. There are **no changes or donor components**.
   - `adapter.spawn_bomb(ctx)` remains as a single-bomb shim:
     `spawn_weapon(ctx, {id="500kg", output=<vanilla 500kg output>})`.
   - Requests `actions.spawn_custom_projectile(definition,
     {position=...,direction={x=0,y=0,z=-1},owner="mods/jacks/eagle_payload"})`.
   - Returns `true, reason` **only** for action status `requested`.
   - Returns `false, reason` only before action execution or after a known
     refusal/cancellation. For `waiting_for_assets`, it immediately calls
     `action:cancel()` and confirms status `cancelled` before returning false.
     The pinned Runtime watcher tests this status before firing later.
   - Returns `nil, reason` on an unknown action result, thrown action error,
     or unconfirmed cancellation. It then permanently faults this adapter.
     The payload controller must also latch off retries. **Do not recreate
     controllers/adapters to erase an uncertain outcome.**
4. `adapter.is_faulted()` returns that uncertainty latch.
5. `Adapter.parse_vehicle(text)` returns parsed IDs or `nil, reason`.
   It accepts only the exact canonical VFC format. Entity and unit are bounded
   32-bit numbers. `actor_hex` and `seat_hex` remain opaque strings; they are not
   converted to Lua doubles or used as native pointers.

The adapter is not an ammunition counter. Keep one payload controller per
vehicle lifetime, including exits and seat changes. `vehicle_key` is
`decimalEntity:8DigitHexUnit` and includes the handles' generation bits, but is
**not a globally unique mission ID**. Namespace controller keys by a separately
tracked mission epoch. Do not refill ammunition just because the player exits,
re-enters, changes seats, or reloads a script.

## Exact release evidence (static inspection, no Runtime execution)

Artifact: `../HD2Runtime-0.40.0-runtime.zip`.
SHA-256:
`3357d8b2b832dad23dd96af90e21d4fcdea60367a097a172d7e749ddbc1ff0ab`.
Guardian result supplied with this task: **UNKNOWN, no findings**. UNKNOWN
does not prove safety. No new download was needed. The SDK archive/builder was
not executed.

Sources below are plaintext Lua resources in
`runtime/9ba626afa44a3aa3.patch_0`. `inspect_release.py` gives numbered lines.
These are source-resource line numbers, **not native offsets**:

| Resource | Lines | Finding |
| --- | --- | --- |
| `hd2runtime/api/hd2` | 98–102 | `version` compatibility string, `api_version` export. Adapter pins 0.40.0 and numeric 1. |
| `hd2runtime/api/events` | 125–144 | `game_state()` has `mission` and `host`; `build()` returns `matched`, `mismatched`, or `not_ready`; `local_player()` returns a handle. |
| `hd2runtime/runtime/handles` | 113–139, 69–72 | Local-player methods, avatar resolution, alive and downed checks. Alive alone includes downed, so adapter also rejects downed. |
| `hd2runtime/runtime/custom_projectiles` | 46–85 | Direct semantic output IDs resolve; name lookup skips `unverifiedDonor`. A known asset dependency is required. |
| same | 115–154, 163–190, 298–314 | **No-change definitions are allowed.** They clone the live base and require validation/readback before returning. |
| `hd2runtime/core/projectile_rows` | 81–91, 124–138, 157–217 | Exact clone, empty changes accepted, identical row validates. **No categorical unit-driven-base rejection** is present in this path. |
| `hd2runtime/domains/attack_outputs` | 2 (generated one-line catalog) | Exact output `output/v1/projectile/eagle-500kg-bomb-projectile-239`: `currentDefault=239`, `unverifiedDonor=true`, dependency `projectile_donor/Eagle 500kg Bomb (projectile 239)`. |
| `hd2runtime/domains/package_residency` and `hd2runtime/domains/stratagem_authoring` | 2 each | The projectile dependency and Eagle 500kg stratagem share the catalogued call-in package. Nothing raw is copied into our request. |
| `hd2runtime/runtime/event_world` | 256–267, 306–327, 562–582 | Entity-generation check; live world pose; `entity_type` returns a **16-digit hex string**; entity-to-unit mapping. |
| `hd2runtime/api/actions` | 43–47, 467–494 | `cancel()` changes waiting status synchronously; asset watcher checks status before firing. |
| same | 574–635 | Internal development API. Host/mission guards and assets remain in place. `requested` set after guarded spawn returns. |
| `hd2runtime/runtime/event_world` | 689–736 | Game-update-only, native-prologue and projectile-row proofs, active system, row compatibility, finite position, direction, source/owner and creditor guards. Adapter bypasses none. |

Thus the reviewed source does **not** reject an unchanged unit-driven bomb
merely for being unit-driven. That is not a live success claim: version/build
proofs, packages, row readback, native context or other guards may still refuse.
The catalog marks this donor **unverified**. Do not substitute a generic blast
or another projectile to disguise a refusal.

## Important unresolved limits

- **Cockpit and seat ownership:** Native type must be Maelstrom
  `B0C9FAF4AF8903F9`; VFC revision must be `vehicle-flight-1.0.1`, flying true,
  camera template 26, role 4 by default, with a fresh heartbeat. This proves
  more than trusting the status text alone, but it is not an independent native
  seat-owner/cockpit-view query. Other VFC versions or real seat roles require
  review, not a broad allowlist. Type is checked through `entity_type`, not
  through VFC's `actor` text.
- **Landing/rearm:** Neither VFC altitude/speed nor `flying=false` proves that
  wheels are clear of terrain. No raycast or physical ground-contact sensor is
  implemented. The entry below supplies an explicit landed-and-stationary
  policy derived from flight mode and measured speed, not physical landing
  proof.
- **Geometry:** Release is 4 metres below the actual vehicle root in world -Z,
  tunable from 1 to 30. It is not a measured cockpit or bomb-bay position.
  It does not prove hull, wing, terrain, teammate, or blast clearance.
- **Original payloads:** The unchanged cloned rows retain vanilla behavior —
  e.g. type 239's nominal 500 m/s launch speed and 500 mass, not a slow
  gravity drop. The supplied investigation identifies small impact damage
  and the larger expiry blast; this adapter does not rewrite either. Unit
  creation, fuse behavior, visible projectiles and actual effects remain
  untested for all seven weapons.
- **Uncertain cancellation:** If Runtime throws or cancellation fails, the
  adapter cannot prove that no deferred action survived. It returns nil and
  faults, not false. Do not auto-retry or promise no bomb in that failure case.
- **Multiplayer:** Runtime retains its own authority checks; there is no
  bypass. This candidate supplies no proof of multiplayer synchronization or
  permission to use it in public lobbies.

## Experimental BSL entry (added, not deployed)

`../eagle_payload_entry.lua` declares
`-- HD2-Addon: mods/jacks/eagle_payload`. It requires:

| Resource | Local source |
| --- | --- |
| `mods/jacks/eagle_payload_core` | `../eagle_payload.lua` |
| `mods/jacks/eagle_runtime_adapter` | `eagle_runtime_adapter.lua` |
| `mods/jacks/eagle_camera_scope` | `../eagle_camera_scope.lua` |

`../eagle_service_point.lua` is still packaged but no longer required by the
entry; the rearm run needs no marked position.

Startup runs inside `hd2.events.run_as("mods/jacks/eagle_payload", start)`.
The singleton `JacksEaglePayloadEntryV1` prevents a duplicate chunk load from
resetting ammunition or an uncertain action. Controllers persist by Runtime
mission epoch + entity/unit key, including exits and seat changes. The 129th
distinct vehicle in one mission is refused, not evicted/refilled. Only a
positively observed new active mission epoch clears the counters and marker.

Controls, registered through `mod:bind` with ModBindingsMenu native labels:

- **X:** cycle to the next of seven weapons (500 KG x2, AIRSTRIKE x3,
  CLUSTER x4, NAPALM x3, ROCKETS x8, GAS x2, SMOKE x4). One step per press.
- **1-7:** jump straight to that weapon slot. A held key never reselects.
- **B:** one release of the selected weapon per press, minimum one second
  between releases, shared across weapons. Holding B never repeats. Initial
  held input is ignored by the payload core.
- **Home:** request a 60-second rearm run while flight is OFF and measured
  speed is at or below 0.5 m/s. It refills every weapon. Takeoff, movement,
  leaving the seat, focus/menu loss or a frame gap cancels it. There is no
  automatic rearm or autonomous fire.

The core's `landed` field is supplied **only as flight-mode policy**
(`flying=false`) and `stationary` from measured root speed. The entry never
claims physical contact. This is not a terrain, landing-gear, or
docking-contact simulation.

Every frame must have positive `dt <= 0.25`, game focus, matched live mission
host state, and no reported menu/cursor capture. It checks `hd2.ui.cursor()`:
`game_menu=false`, `held=false`, `show_cursor=false`, and no explicit lost
mouse focus. An unreadable cursor fails closed. Runtime settings also block.
**Limitation:** `game_menu` alone is sampled during cursor holds, not a complete
game-menu classifier (`runtime/mod_cursor` lines 14–18, 73–87, 121–126). The
live cursor check adds protection, but a keyboard-only screen without a cursor
may not be distinguishable. Runtime cannot consume these keys; avoid conflicting
native bindings. Positive `dt` is simulation-activity policy, not a dedicated
pause API. No claim of detecting every possible menu/pause state is made.

Assets prewarm lazily, at most three attempts per mission separated by ten
seconds; any returned job suppresses additional bulk requests. `waiting_for_assets`
release actions still cancel immediately. Status changes always log through
`mod:log`; an optional overlay shows weapon/ammo/rearm status and cannot
disable logging.

`../tests/test_eagle_payload_entry.py` supplies 19 additional offline
integration tests executing only our entry/core/adapter with injected Runtime
mocks. They cover per-weapon ammo, selection cycling, held-input suppression,
the full 60-second landed rearm run, mission reset versus read failure/exit,
flight-off rejection, gaps, menus, cancellation, uncertainty, duplicate chunk
loads, controller capacity and optional-HUD failure. No Runtime Lua or native
calls run in tests.
