# Eagle mod handoff

## Installed + DEPLOYED: version 0.9 - gravity, no hover

`Eagle-1-Cockpit-Pack-0.9.zip` is installed in Arsenal (profile + library,
`Eagle-1 Cockpit Pack 0.9_ARLOCAL`, sha `a21ee21bef2d`, backup
`hd2a_data.json.devin-backup-09`) AND manually deployed to game-data slots
41..46. `verify_eagle_deploy.py` reports **DEPLOY CLEAN**. Changes vs 0.8:

- **No more midair freeze**: a one-byte bytecode patch flips VFC's
  compiled-in `hover_hold` default from True to False (tag 2 -> 1 inside
  the serialized defaults table; verified by re-parsing the whole dump -
  only that field and the camera RET0 differ). The Maelstrom now sinks
  under gravity when controls are released instead of hanging in place.
  It still flies normally; you just keep flying it like a plane.
  `Eagle-Cockpit-Camera-Experiment-0.4.zip` carries the patched VFC
  resource; its test asserts byte-exact mutation.
- Everything from 0.8 stays: edge bars removed, eye inside the canopy
  (0.6 m forward, 1.15 m up), nose-forward releases, VFC options preset
  (turn 100%, roll 85%), latched flight tracking, 0.6 s camera hold.

Note: with hover off, releasing controls while airborne lets the ship
settle toward the ground - realistic, but take your hands off the keys
near the ground at your own risk.

## Installed + DEPLOYED: version 0.8 - user-requested fixes

`Eagle-1-Cockpit-Pack-0.8.zip` is installed in Arsenal (profile + library,
`Eagle-1 Cockpit Pack 0.8_ARLOCAL`, sha `3c433c8e0d24`, backup
`hd2a_data.json.devin-backup-08`) AND manually deployed: the earlier Arsenal
deploy left stale 0.6-era code in `patch_44/45`; those slots now hold the
0.8 camera and payload layers. `verify_eagle_deploy.py` reports
**DEPLOY CLEAN**. User has NOT test-flown it yet. Changes in 0.8 over 0.7:

- **Blue edge bars removed**: the fake canopy frame (four dark-blue rects
  around the screen edge + corner struts) is deleted from the entry overlay.
  Only the center crosshair and the EAGLE ammo panel remain.
- **Cockpit eye moved inside the canopy**: `first_person.eye_forward`
  220 -> 60 (2.2 m in front of the seat was past the nose - the "weird
  angle"), `eye_height` 108 -> 115. Non-fp fallback zoom 25% -> 60%.
- **Flight feel preset via VFC options file**
  (`Logs/ModOptionsMenu.values`): `vfc.turn` 200 -> 100 (the description
  says 100 is the original AFC table - less twitchy) and `vfc.roll`
  100 -> 85. File-based, reversible through the Mod Options Menu in game.
- Still inside: nose-forward release direction, proven/latched VFC
  tracking, 0.6 s camera hold, parked-seat proximity, 0.3 diagnostics
  capturing VFC aim/pitch/dist every ~0.1 s.

Tests: 177 root + 54 adapter green; verifier clean. Remaining: icon enum,
native cannon lockout, deeper physics would need VFC bytecode constants
(not exposed - only turn/roll/cam_height/flip_damage/enabled are menu
options).



## Current update: one Eagle entry, version 0.3

`Eagle-1-Cockpit-Pack-0.3.zip` has been built, scanned, extracted into Arsenal,
and added as **Eagle-1 Cockpit Pack 0.3** in the Default Profile. **It is not
deployed yet: Helldivers 2 was still running.** The previous deployed version
remains in the game data until the next deployment.

The six separate Eagle components have been removed from this profile and
retained in Arsenal's Library and their original folders for rollback.
Bingus Shared Loader and HD2Runtime remain separate, enabled dependencies.
Other mods were preserved; conflicting Tank Seat Kit is off.

The 0.3 pack includes:

- The v5 model, flight controls, vehicle drive/fire features, blue icon, payload
  and rearming in one Arsenal entry.
- A camera scope controller: request first person only for the current verified
  Maelstrom pilot/gunner seat; restore normal camera when leaving or losing valid
  context. It uses AVP's hot-reloaded settings, so switching may have a short delay.
- Generic vehicle-camera edits remain disabled. The previous 25% setting was
  observed affecting template 57 while VFC reported no controlled vehicle.
  Live settings were reset to normal distances and first person off as an
  immediate visibility fix while the update is prepared.
- Rearm progress and distance/height difference back to the service marker.
  Takeoff explicitly cancels rearming even if a stale docking flag remains set.

All 129 root-suite tests passed. Camera alias declarations also resolved in
LuaJIT without executing filesystem writes. The combined package preserves ATT
and skin archive boundaries because ATT identifies other model patches by file.
Every merged winning resource and both graphics sidecars were checked.

Guardian found no local findings; verdict UNKNOWN because VirusTotal is not
configured. ZIP SHA-256:
`538b808c8bdc56a4e28129cdd8a7348640e14f29487205fefe08f837cfc23c3e`.
Registry backup: `hd2a_data.before-combined-pack-0.3.json`.

Next: exit the game, use Arsenal's Purge then Deploy to remove old component
patches and install the combined entry, and check the winning resources and fresh
startup log. Do not re-enable the six Library copies alongside the combined pack.
The cockpit eye position, flight/shooting, bomb damage and service still need
the actual mission test. Version 0.3 has not yet passed startup testing.

## Installed: version 0.7 - aim, camera hold, diagnostics

`Eagle-1-Cockpit-Pack-0.7.zip` is built, installed in Arsenal (profile +
library entries updated to `Eagle-1 Cockpit Pack 0.7_ARLOCAL`,
contentHash = zip SHA `56e7a93c0ba7` (full:
`56e7a93c0ba7999669252aefd6b9bf570c305f09c34f0983e56413851f55f1a0`),
registry backup `hd2a_data.json.devin-backup-07`, ZIP also copied to
Downloads. **Awaiting Deploy + mission test.** Package check: 7 layers,
39 winning resources, all five local sources match current code.
Devin-CeilingHelper's claimed fixes, built overnight from the user's
live complaints:

- **Bombs now launch along the nose**, not straight down. The adapter
  previously sent a hardcoded `{0,0,-1}` world-down direction; it now
  requires the live hull `forward` vector from `unit_pose` and spawns
  with that direction (the runtime normalizes it). A
  `< 0.5 above/below horizon` clamp keeps bombs on a useful throw and
  stops spikes when the nose pitches steeply. This is nose-forward,
  not a true camera ray: the Runtime API exposes no screen-center ray
  (checked the SDK). Next-session capture of VFC's `aim`/`dist` may let
  us tilt the throw toward where the crosshair points vertically.
- **Camera stability hold**: the scope keeps the last good mode through
  a 0.6 s telemetry blip (VFC republish, SVD overlay) before restoring,
  so the camera cannot bounce per-republish. Without a clock argument
  the old immediate behavior is kept.
- **Adapter flap fix**: the VFC table is now *proven* - accepted after
  two consecutive observations 0.05-0.25 s apart with vehicle identity
  and pose continuity - then it is latched; intermediate republish
  rejects no longer reset the latch while the old vehicle still scans.
  The SVD `role_overlay_held_by_game_state` value counts as a seat
  declaration, so a parked/seated blip can no longer bounce the camera.
- **Blue canopy accent dimmed** (alpha 150, bright blue -> alpha 160,
  dark steel) so it no longer reads as a blue bar. Blue "bars around
  when fly" are most likely VFC's native speed/alt bars - needs the
  deployed-test screenshot. The Eagle side already reports per-weapon
  ammo in one text panel; the Maelstrom's own bar is VFC/AVP UI, which
  nothing in our entry suppresses.
- Diagnostics module bumped to `camera-experiment-0.3`: samples every
  6 frames (~0.1 s) and also captures VFC `frames`, `aim`, `pitch`,
  `roll`, `dist`, `speed`, `alt`, `mode`, `sets`, `impacts` so the next
  live session shows the publish cadence and aim semantics.

Known remaining issues, per Devin-ModHelper's 034 report: Maelstrom
stratagem icon still diagnostic (enum unclear), native gun not locked
out (payload safes during rearm but the Maelstrom cannon may still
fire), and "a little helicopterish" flight is unchanged - tuning is
explicitly deferred until aim/camera are proven.

All 54 adapter + 180 root tests pass; verifier clean. User test:
deploy 0.7, enter the Maelstrom, fire B at a distant target - bombs
should arc toward the nose, camera should stay first person through
telemetry hiccups, and `EagleCameraDiagnostics.log` will capture the
aim fields for the crosshair-tilt follow-up.



`Eagle-1-Cockpit-Pack-0.6.zip` is built, installed in Arsenal (profile +
library entries updated to `Eagle-1 Cockpit Pack 0.6_ARLOCAL`,
contentHash = zip SHA `ee5cb87bbe9e` (full: see registry)
— fifth build, includes HelldiversHelper's proximity + cold-seat fix
and the REAL Eagle icon),
registry backup `hd2a_data.json.devin-backup-06`. **Awaiting Deploy +
mission test.** Built from the user's live 0.5 session findings:

- **First-person eye at the canopy**: the scope now owns
  `first_person.eye_height` (120 -> 108) and `first_person.eye_forward`
  (0 -> 220) so the eye sits at canopy height pushed to the nose instead
  of perched on the roof. The same values were live-edited into the
  running INI (hot-reload) during the user's session.
- **Landed HUD heartbeat fix**: when `flying == false` and the seat is
  still held, `inspect_vehicle` accepts a stale `flight.frames` counter
  (VFC stops ticking with flight off). Previously the heartbeat went
  stale ~0.25 s after landing and the HUD/camera died on the ground.
- **Canopy overlay slimmed**: the fake frame was covering too much of
  the screen ("blue ring"); now thin bars (34/26/22 px @1080p) plus
  short struts and a 2 px edge light.
- **Service Pelican departs**: hover 75 s -> 15 s. It flies in, holds
  over the Eagle briefly, and leaves while the 60-second timer keeps
  running; ammo still lands at the end of the run.
- **Guns safed during service**: firing is already locked while a rearm
  run is active (the payload returns before fire logic); the HUD now
  says "GUNS SAFED" in the countdown line.
- **Ammo shown as counts**: the loadout strip reads `NAME xN`, and
  during a rearm run it shows `NAME cur->cap` as a refill preview.
- **Parked-seat proximity lookup** (HelldiversHelper): when flight is
  off, the seat is held, and no vehicle is cached, `inspect_vehicle`
  scans live health-record descriptors for the unique Maelstrom within
  10 m (`seat_proximity` option) of the local avatar's position, then
  runs it through the same entity/unit/type/pose verification. Two
  Maelstroms in the radius, a far avatar, or missing APIs all fail
  closed. The candidate still cannot fire ordnance — release requires
  `inspect()` (flying with live VFC text).
- **Known remaining**: a *truly cold* parked start (never flown this
  session) can show `tmpl=-1`, which the adapter still rejects before
  reaching the proximity path — CeilingHelper flagged this; the
  warm-parked case (tmpl stays 26 after having flown) is covered.
  Icon patch is deployed byte-identical but still not visibly
  applied — the `StratagemBastion` template is probably not what the
  Maelstrom row binds; needs a real binding trace.

## Previous install: version 0.5 - landed HUD + real Pelican rearm visual

`Eagle-1-Cockpit-Pack-0.5.zip` is built, installed in Arsenal (profile +
library entries updated to `Eagle-1 Cockpit Pack 0.5_ARLOCAL`,
contentHash = zip SHA `486c2ead8cb26ef83088fba334441709f98354406f94db2e3efedee5383452e1`),
registry backup `hd2a_data.json.devin-backup-pelican`. **Awaiting Deploy +
mission test.** User's 0.4 flight confirmed first person works but showed
the model's hollow interior; the canopy frame was added for 0.5.

- **Seven Eagle weapons**: **X** cycles, **1-7** jump straight to a slot,
  **B** fires. Only the 500kg is proven in-game so far:

  | Key | Weapon | Output | Ammo |
  |---|---|---|---|
  | 1 | 500 KG | eagle-500kg-bomb-projectile-239 | 2 |
  | 2 | AIRSTRIKE | eagle-airstrike-projectile-170 | 3 |
  | 3 | CLUSTER | eagle-cluster-bomb-projectile-286 | 4 |
  | 4 | NAPALM | eagle-napalm-airstrike-projectile-141 | 3 |
  | 5 | ROCKETS | eagle-110mm-rocket-pods-projectile-82 | 8 |
  | 6 | GAS | eagle-gas-airstrike-projectile-188 | 2 |
  | 7 | SMOKE | eagle-smoke-strike-projectile-130 | 4 |

- **HUD while landed**: VFC blanks `vehicle` when flight mode is off, so
  `inspect_vehicle` now falls back to the last verified vehicle while
  `SoloVehicleDriver.status == "role_overlay_held_by_game_state"` (read
  via rawget; fails closed otherwise) and the entity re-verifies through
  world_api. HUD/camera/rearm now work while seated on the ground; they
  stay off on foot. `inspect()` still requires flying.
- **Real Pelican rearm visual**: on rearm start the adapter calls
  `hd2runtime/api/pelican`.spawn over the vehicle root with
  hover = duration+15s (0.5; 0.6 uses a fixed 15 s). It is decorative: a refusal never blocks the
  60-second rearm timer, never sets the adapter fault latch, and the
  handle is only reused for the same vehicle parked within 25 m of the
  original anchor. HUD reports INBOUND/ON STATION/DEPARTING/refused.
- **Rearm run**: land (flight off), hold still, press Home, wait 60
  seconds -> all weapons refill. Moving, taking off, losing focus or the
  seat cancels. Insert marking stays removed.
- **Cockpit sight + canopy frame**: crosshair and drawn canopy border
  while seated in first person (the model has no interior).
- Offline state: 175 root-suite + 39 adapter tests pass. No mission test
  of the new weapons, Pelican, or landed HUD yet.
- Super Destroyer docking remains impossible: the ship is a menu scene,
  not a physical place in the mission.

## Backlog (user requests, not yet started)

- **Flight feel**: VFC stops dead when keys are released (hover). User wants
  momentum/inertia so the Eagle keeps drifting forward instead of floating.
  This means editing VFC's movement code; separate task after mission tests.

## Previous deployed experiments


The first experimental build is installed and deployed through HD2 Arsenal.
It is not yet proven in a mission.

## What is deployed

- Eagle Cockpit Camera Experiment 0.2: lets Advanced Vehicle Pack control the
  gunner camera while Vehicle Flight Control handles movement. First-person
  settings are applied; the actual Eagle eye position needs a flight test.
- Eagle Stratagem Icon (Blue Jet) 0.1: the custom top-down blue jet, drawn as
  vector paths in the tank stratagem template.
- HD2Runtime 0.40.0 by SkyeShade, installed separately. Its supplied mouse-wheel
  hook-off option is selected.
- Eagle Payload Experiment 0.2: two 500 kg projectiles per load and a virtual
  service marker with a 150-second rearm.

The original flight, Eagle skin and Advanced Vehicle Pack remain enabled.
Tank Seat Kit remains disabled. Existing cannon/missile controls come from AVP.
Other Eagle payload types and Super Destroyer docking are not implemented.

## Controls to test in solo/host play

1. Stand still on foot for three seconds; press **Insert** to mark your service
   point. It cannot be moved during that mission.
2. Enter the Maelstrom gunner/pilot seat. **I** toggles flight.
3. **B** requests one 500 kg projectile. There are two per load. Holding B does
   not repeat. The second drop requires another press after one second.
4. Return to the marker, switch flight off, and stop within eight metres
   horizontally/two vertically. Press **Home** and remain there for 150 seconds.

Rearming checks position and speed, not physical landing-gear contact. Leaving
the zone/seat or losing valid updates cancels it. The unchanged vanilla
projectile has a nominal 500 m/s launch speed; its flight, fuse and damage with
this aircraft are still experimental. Release is four metres below the
vehicle root, not a measured bomb-bay location. It does not inherit momentum.

## Verification performed

- The full root test suite passed 90 tests before the final HUD improvement.
  The changed entry then passed 15 tests, including the added HUD regression;
  its archive test passed too. The separate Runtime adapter suite passed 33.
- Tests execute our Lua with mocked game/Runtime dependencies. They do not
  execute native game code or prove bomb damage.
- The final packages contain the expected resource identities and Lua
  envelopes. The camera package was also read with the independent SDK.
- Both installed game binary hashes match the Runtime's supported build.
- Arsenal's UI reported deployment success. The registry confirms deployment,
  and the highest deployed VFC override matches the intended camera patch.
- A fresh game launch loaded the flight override, diagnostics, HD2Runtime and
  payload addon. Runtime registered all three keybinds and logged initialization.
- The game reached the ship. No mission was started: the account already had
  an operation in progress. That operation was left intact.
- Matchmaking was temporarily changed from Friends Only to Invite Only during
  the startup check, then restored to Friends Only through the game settings.
- The automatic verifier reported no bugs.

`startup-validation-0.2.json` records the final version's startup check when
available. Startup success is not mission success.

## Scans and package identities

Guardian found no local findings in these archives. Its verdict was UNKNOWN
because VirusTotal is not configured; this is not a guarantee of safety.

| Archive | SHA-256 |
| --- | --- |
| Eagle-Cockpit-Camera-Experiment-0.2.zip | 71fe81a0a9644ff45e609aa8422b516acbe18025f6161a4e0d0a31338a16aee0 |
| Eagle-Stratagem-Icon-Blue-0.1.zip | b15c82ab8d36c83d53c340b0fb7ad1a074aea79020b9295faba7e39a646789d0 |
| Eagle-Payload-Experiment-0.2.zip | 4ee9ad47978c95b57e8b7aae1e3e14caeaf23d9924d01c7badbc369da67b0d22 |
| HD2Runtime-0.40.0-runtime.zip | 3357d8b2b832dad23dd96af90e21d4fcdea60367a097a172d7e749ddbc1ff0ab |

The Runtime matches its publisher's release checksum. Its SDK archive was
flagged SUSPICIOUS: inspection traced the credential heuristic to the literal
Lua variable declaration `local state` embedded in `hd2.py`. The SDK builder
was not executed. The Lupa test dependency matched the official PyPI wheel;
its scan flagged expected native Python modules (.pyd). Neither result was
described as proven safe.

## Next test

During a suitable solo mission, verify the actual seat is role 4/template 26,
cockpit placement is usable, and driving/firing still work. Then check two
successful drops, a refused third drop, visible bomb/fuse/explosion, actual
damage, and complete/cancelled rearming. Do not add further payload types until
the basic bomb path is observed working.

Logs live at
`C:/Users/jacks/AppData/Local/CowboyBingus/Helldivers2/Logs/`:
`BingusSharedLoader.log`, `EagleCameraDiagnostics.log`, and `HD2Runtime.log`.

## Re-run the offline checks

From `C:/Users/jacks/HQ`:

```text
python -m unittest discover -s downloads/hd2-mods/tests -p "test*.py"
python -m unittest discover -s downloads/hd2-mods/runtime_adapter -p "test*.py"
```

## Rollback

Exit the game, disable the three Eagle experiments in Arsenal, and deploy.
The old flight mod and skin are still present. Restore
`AdvancedTankCamera.before-eagle.ini` to the original camera settings path if
reverting the camera too. HD2Runtime can be disabled if nothing else uses it.

Registry snapshots are retained under this folder; prefer Arsenal's normal
toggles over restoring a whole old registry, which could overwrite later edits.
