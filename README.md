# Eagle-1 Cockpit Mod (Helldivers 2)

Fly the Eagle-1 Maelstrom like a plane, from a first-person cockpit seat,
with seven Eagle weapons on keys and a landed rearm run that calls in a
service Pelican.

> **Experimental.** Only the 500 kg bomb is proven in game so far. The other
> six weapons are unverified donors. Super Destroyer docking is not possible.

## What you need

1. **HD2 Arsenal** — the mod manager that installs everything. Two ways to get it:
   - Grab it from this repo's **Releases** page (the installer is attached there
     next to the mod zip), or
   - Run `Get-Arsenal.ps1` — it downloads the latest official installer and
     checks its SHA-256 for you.
   - Official page: <https://www.nexusmods.com/helldivers2/mods/4664>
2. **Bingus Shared Loader v18** and **HD2Runtime 0.40.0**
   (<https://github.com/SkyeShade/HD2Runtime>) — the loaders this pack runs on.
3. **Eagle-1-Cockpit-Pack-0.9.zip** — in this repo, and also attached to the
   latest release. Do not unzip it; Arsenal imports the zip as-is.

## Install

1. Install Arsenal and its two loader dependencies above.
2. In Arsenal, **Add Mod** → pick `Eagle-1-Cockpit-Pack-0.9.zip`.
3. Enable the single **Eagle-1 Cockpit Pack 0.9** entry in your profile.
   Disable the six separate old Eagle component entries and Tank Seat Kit
   if you have them. Keep them installed for rollback.
4. **Deploy**, launch the game, get in the Maelstrom.

## Controls

| Key | Action |
| --- | --- |
| **I** | Toggle flight |
| **X** or **1–7** | Pick a weapon (500kg x2, airstrike x3, cluster x4, napalm x3, rockets x8, gas x2, smoke x4) |
| **B** | Fire the selected weapon along the nose |
| **Home** | Rearm run while landed and stopped — a Pelican hovers over the parked Eagle for the 60-second refill |

Notes: the cockpit camera and HUD only engage in the verified Maelstrom
pilot/gunner seat. The ship now sinks under gravity when you let go of the
controls (hover is off), so keep your hands on the keys near the ground.

## Repo layout

- `Eagle-1-Cockpit-Pack-0.9.zip` — the importable Arsenal package
- `source/` — the Lua and Python sources and build scripts that produce it
  (`tests/` and `runtime_adapter/` have offline test suites)
- `docs/` — status log, design plan, mission-test checklist, package checks
- `Get-Arsenal.ps1` — helper that downloads the official Arsenal installer

## Credit / ownership

This pack bundles other authors' work: Eagle1 Maelstrom v5,
Vehicle Flight Control 1.0.1, and Advanced Tank Hull/Turret, plus our
cockpit, icon, and payload changes. The original authors keep ownership of
their components. Arsenal itself is by Crystal2K / Orbit-Studios.

## Run the offline tests

```text
python -m unittest discover -s source/tests -p "test*.py"
python -m unittest discover -s source/runtime_adapter -p "test*.py"
python -m unittest source.hd2tools.test_hd2tools
```

Tests run our Lua/Python with mocked game dependencies. They do not prove
in-mission behavior.
