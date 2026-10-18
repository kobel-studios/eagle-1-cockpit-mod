# Eagle-1 Cockpit Pack — mission test checklist (0.6)

Run this after the pack is rebuilt and deployed. Everything here is what a
successful test should show; none of it is proven until seen in a real
solo/host mission.

## Before launch

- [ ] Game fully closed
- [ ] Arsenal profile: `Eagle-1 Cockpit Pack 0.6` enabled; the six old Eagle
      component entries and TankSeatKit **disabled** (seat-feature conflict)
- [ ] Arsenal Purge, then Deploy
- [ ] `python verify_eagle_package.py <pack.zip>` — source/layers match
- [ ] `python verify_eagle_deploy.py` — prints the pack name, ends `DEPLOY CLEAN`
- [ ] Launch game, confirm mod load lines in the log (bindings B/X/1-7/HOME/I)

## In mission (solo/host only — the adapter refuses as a client)

### Seat + HUD
- [ ] Call in the Maelstrom, enter the control seat
- [ ] Parked with no HUD? Press `I` once (flight on then off) — known
      limitation: the adapter cannot ID the vehicle until VFC has seen it once
- [ ] HUD reads `EAGLE | 500 KG  2 / 2` and `X: WEAPON    B: FIRE    HOME: REARM`
- [ ] HUD stays visible while landed (flight off), hidden on foot

### Camera
- [ ] First person: eye at canopy height pushed to the nose — not the roof
      view seen on 0.5 (`eye_height=108, eye_forward=220` while seated only)
- [ ] Thin canopy frame bars drawn around the view edge, plus centre crosshair
- [ ] Camera + HUD restore when leaving the seat

### Weapons
- [ ] `X` cycles 500 KG → AIRSTRIKE → CLUSTER → NAPALM → ROCKETS → GAS →
      SMOKE → wraps to 500 KG
- [ ] `1`–`7` jump straight to a slot; a held key does not repeat
- [ ] While flying, `B` fires the selected weapon — one release per press
- [ ] Watch each weapon's projectile: 500 KG proven; AIRSTRIKE/CLUSTER seen
      spawning on 0.5; NAPALM/ROCKETS/GAS/SMOKE unverified donors — note what
      each actually does (visual, damage, nothing?)

### Rearm run + service Pelican
- [ ] Land (flight mode off), hold still, press `HOME` — run starts
- [ ] Service Pelican flies in and hovers over the parked Eagle ~15 s, then
      departs on its own — the 60 s timer continues after it leaves
- [ ] HUD shows the countdown and `SERVICE PELICAN ON STATION`/stage text;
      ammo row shows the refill preview
- [ ] Firing is locked while a rearm run is active
- [ ] At 60 s every weapon refills to capacity
- [ ] Cancels correctly: moving, taking off, or leaving the seat aborts the
      run with no refill

## Known limitations (expected, not test failures)

- Custom blue stratagem icon does not visibly apply — the icon→stratagem
  binding is still being traced
- Flight stops dead when controls are released — momentum/drift is backlog
- Eye position is a tuned approximation; the model has no real cockpit interior
- A requested spawn is not proof of real damage/visuals for donor weapons

## If something fails

- Note the exact HUD/status line and game log section; check
  `hd2-mods/STATUS.md` and report in mailbox before redeploying.
