# Eagle cockpit mod

Update: the components are now packaged as **Eagle-1 Cockpit Pack 0.3** and
prepared as one Arsenal profile entry. Deployment is pending the running game
closing. See `STATUS.md` for the current state. The camera regression is addressed
by a validated-seat-only controller; normal distances were restored immediately
as a temporary fix. Do not reapply the old global 25% camera preset.

Status: the camera, icon, and payload experiments are enabled and deployed
through Arsenal. HD2Runtime 0.40.0 is installed as their separate dependency.
A fresh game launch loaded the flight override, camera diagnostics, payload
addon, and Runtime successfully. Mission behavior remains unverified.

## Implemented so far

- `Eagle-Cockpit-Camera-Experiment-0.2.zip`: exact-input VFC camera compatibility
  patch plus a diagnostic addon that logs existing mods' status. Independent
  SDK parsing confirms both Lua resources. Flight movement and host/address
  gates remain unchanged. Camera-template writes are skipped so AVP can own
  its first-person camera.
- AVP's first-person path applies only to camera template 26. Other templates
  receive zoom changes only. Correct Eagle cockpit position is untested.
- `Eagle-Payload-Experiment-0.2.zip`: two bombs, one drop per press, release
  interval, and uninterrupted 150-second virtual service. Its adapter clones
  the unchanged Eagle 500kg projectile through HD2Runtime's guarded development
  API. The startup log confirms initialization and keybind registration.
  Actual drops, visuals, fuse, damage, and rearming remain unverified. Version
  0.2 hides the payload HUD outside missions and simplifies its pilot display.
- `Eagle-Stratagem-Icon-Blue-0.1.zip`: the original custom jet geometry is now
  vector artwork replacing `StratagemBastion`, bound to `DropoffTank`. Other
  templates are unchanged. No existing enabled mod overrides that resource.
- Original and proposed camera settings are saved locally as
  `AdvancedTankCamera.before-eagle.ini` and
  `AdvancedTankCamera.eagle-candidate.ini`. The candidate was applied after the
  game closed; it selects first person and expands gunner pitch to +/-85.
- Guardian found no local findings in the camera ZIP, verdict UNKNOWN because
  VirusTotal is not configured. Do not equate that result with proven safety.
- Arsenal registry backups: `hd2a_data.before-cockpit-0.2.json`,
  `hd2a_data.before-eagle-icon-runtime.json`, `hd2a_data.before-eagle-enable.json`.
- Both installed game binary hashes match HD2Runtime's supported build.
  Its own build, host, asset, entity, and native function guards still run.

## Runtime blockers

Arsenal reported successful deployment and marks all four new entries deployed.
The winning VFC resource matches the intended camera patch. Startup succeeded,
including payload bindings. A controlled solo/host seat test is still needed.

The private ATH self-destruct explosion wrapper does not provide a demonstrated
falling projectile API. It requests an immediate local explosion; its separate
vehicle-damage call cannot prove explosion area damage. Its public state table
does not expose callable firing methods.

Calling an equipped Eagle stratagem from the seat is an existing option, but it
does not satisfy direct bomb release from this aircraft. The project does not
claim that fallback implements the requested weapons.

## Requested behavior

- Fly and drive from one first-person cockpit seat.
- Fire real Eagle weapons using buttons while remaining in control of the plane.
- Carry a limited supply of each weapon.
- Rearm at a place aboard the Super Destroyer if the game supports reaching it during a mission.
- Use the custom blue Eagle stratagem icon.

## Starting balance proposal

These are implemented controller rules, tested offline. They have not yet
been verified in a game mission.

- Carry two 500 kg bombs per full load.
- One press releases one bomb; holding the button must not release the entire load.
- Show remaining bombs in the cockpit.
- At zero, reject another drop and display "Out of bombs — rearm."
- Switching weapons or seats must not refill ammunition.
- Rearming requires landing, stopping inside the designated service area, and explicitly starting service.
- Start with a 150-second rearm period. Weapons are unavailable during service.
- Leaving the service area cancels service without refilling ammunition.
- Refill only when the complete service period finishes.
- Other weapons need their own finite capacities after their firing behavior is confirmed.

Super Destroyer docking is not implemented. The current fallback is a virtual
service marker: stand still on foot for three seconds and press Insert, then
park within eight metres horizontally/two vertically and press Home. Flight
must be off and measured speed at most 0.5 m/s. This is a position/speed check,
not physical ground-contact detection. The marker cannot move during a mission.

## Implementation gates

1. Establish a supported way to create a real 500 kg projectile, including its
   movement, impact, explosion, damage, and resource loading. A visible model
   or a function name is not enough evidence.
2. Confirm the host can authorize each drop and keep ammunition consistent.
   Consume one round only when a drop is accepted; reject duplicate requests.
3. Identify a safe cockpit camera hook compatible with Vehicle Flight Control
   and the existing drive-and-fire behavior.
4. Establish whether mission space contains a reachable Super Destroyer service
   area and whether travel preserves mission and vehicle state. Do not assume
   the ship visible in the sky is an accessible hangar.
5. Bind service checks to actual position, flight mode, measured speed, and
   elapsed game time. A physical contact sensor remains future work.
6. Package only after runtime integration exists; validate, scan with Guardian,
   and install through Arsenal. In-game testing remains required.

## Evidence so far

- Helpers identified Maelstrom package `65ee777b72347cb4` and icon atlas package
  `4c2203529ff1a9c4`.
- Extracted Vehicle Flight Control contains an escaped LuaJIT bytecode payload,
  not readable source demonstrating projectile or rearm APIs.
- Bingus Shared Loader authoring documentation is available at
  https://github.com/CowboyBingus/BingusSharedLoader/blob/main/docs/AUTHORING.md.
  Loading an addon does not by itself establish access to projectile spawning.
- Direct 500 kg spawning, all Eagle weapons, and Super Destroyer docking remain
  unconfirmed.

## Required checks once implemented

- Exactly two successful drops exhaust a full bomb load; a third creates nothing.
- Holding fire, changing seats, or switching weapons cannot bypass the limit.
- A failed spawn preserves ammunition; repeated handling of one press cannot
  create duplicate bombs.
- The bomb falls and produces the correct game damage, not only visual effects.
- Rearm cannot start while airborne or outside the service area.
- Interrupted service gives no ammunition; completed service restores the cap.
- Cockpit view, steering, and firing work together in solo/host play.
- Mission transitions and destroyed/replaced vehicles do not retain invalid state.
