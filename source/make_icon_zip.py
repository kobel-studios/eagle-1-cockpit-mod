"""Package the blue-eagle stratagem icon patch as a standalone Arsenal zip.

Layout matches the Eagle Cockpit Camera Experiment packages:
    manifest.json / README.txt / validation.json / Addon/<patch files>
Run AFTER make_icon_patch.py has produced 007e093ca718ca1a.patch_0.
"""
import hashlib
import json
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_icon_patch as mip

HERE = os.path.dirname(os.path.abspath(__file__))
ZIP_NAME = "Eagle-Stratagem-Icon-Blue-0.1.zip"

MANIFEST = {
    "Version": 1,
    "Guid": "716d3cda-0a07-4fd8-af26-5df5d5662aa5",
    "Name": "Eagle Stratagem Icon (Blue Jet) 0.1",
    "Description": ("Replaces the DropoffTank stratagem icon (StratagemBastion "
                    "vector template) with a custom top-down blue jet glyph on "
                    "the stock grey panel. Icons only; no gameplay changes."),
    "Options": [
        {
            "Name": "Blue Eagle icon for DropoffTank",
            "Description": "Install the icon patch for package 007e093ca718ca1a",
            "Include": ["Addon"],
        }
    ],
}

README = """Eagle Stratagem Icon (Blue Jet) 0.1

NOT YET TESTED IN GAME. File-level icon replacement only - no gameplay,
camera, bomb, or rearm features.

Replaces the vector contents of the "StratagemBastion" DataTemplate inside
generated_icons/stratagem_icons.xaml (package 007e093ca718ca1a, entry
7c6e2910b1a074a6). The game's DropoffTank stratagem enum resolves that
template for its icon in the loadout screen, HUD list, and stratagem ball.
The new art is a custom top-down blue jet glyph (from make_icon.py) on the
stock dark panel - it is not a recolored stock Eagle icon.

Known uncertainty: DropoffTank -> StratagemBastion is the only tank icon
binding in the game's icon dictionary, and tank_storm is the only tank
vehicle package found in the data, so this should be the Maelstrom icon.
Confirm in game before shipping.

Exit the game normally before deployment. Import through Arsenal, enable,
then deploy. No registry edits needed.
"""


def main():
    patch = os.path.join(HERE, mip.OUT_PATCH)
    with open(patch, "rb") as f:
        patch_sha = hashlib.sha256(f.read()).hexdigest()

    validation = {
        "package": mip.ICONS_PKG,
        "resource": "generated_icons/stratagem_icons.xaml",
        "entry": hex(mip.ICONS_XAML_ENTRY),
        "template_key": "StratagemBastion",
        "binding_enum": "DropoffTank",
        "patch_sha256": patch_sha,
        "game_tested": False,
    }

    out = os.path.join(HERE, ZIP_NAME)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(MANIFEST, indent=2))
        z.writestr("README.txt", README)
        z.writestr("validation.json", json.dumps(validation, indent=2))
        for suffix in ("", ".gpu_resources", ".stream"):
            src = patch + suffix
            z.write(src, "Addon/" + mip.OUT_PATCH + suffix)
    print("wrote", out)


if __name__ == "__main__":
    main()
