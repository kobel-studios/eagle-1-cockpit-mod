# Check an Eagle package before deployment

From `C:\Users\jacks\HQ`, give the checker the exact ZIP you plan to install:

```text
python downloads/hd2-mods/verify_eagle_package.py downloads/hd2-mods/Eagle-1-Cockpit-Pack-0.4.zip
```

Replace the filename when checking a newer version.

- Exit 0: archive structure, declared patch priority, resource fingerprints,
  and the packaged local Lua modules passed.
- Exit 1: the package is broken, incomplete, or older than the current source.
  Read the printed reason. Rebuild if it lists stale Lua files.

The checker reads the ZIP without extracting it. It never runs Lua, the
downloaded SDK, or game code. It never changes the package, game installation,
or Arsenal settings.

It checks every layer and its graphics sidecars against `validation.json`,
then compares the winning local Lua resources against the source files listed
by our local `build_eagle_payload.py`. It reports the ZIP's SHA-256 fingerprint
so the result can be tied to an exact build.

This is a file check. It does not prove correct cockpit geometry, seat
detection, projectile effects, Pelican arrival, or multiplayer behavior.
It also does not inspect the game installation or certify third-party code.

After deployment, run the separate deployment checker with that same ZIP:

```text
python downloads/hd2-mods/verify_eagle_deploy.py downloads/hd2-mods/Eagle-1-Cockpit-Pack-0.4.zip
```

Focused checker tests:

```text
python -m unittest discover -s downloads/hd2-mods/tests -p test_verify_eagle_package.py -v
```

These tests use synthetic archives and temporary folders inside the project.
They cover matching files, stale or missing modules, incorrect resource
fingerprints, wrong priority, missing sidecars, malformed resource bounds,
duplicate declarations, source path restrictions, and read-only behavior.
