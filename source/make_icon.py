"""Draw a custom HD2-style stratagem icon: blue Eagle jet glyph on the
standard grey tile with the little blue corner tab."""

from PIL import Image, ImageDraw

S = 512  # power of 2, HD2 rule

# --- colors sampled to match vanilla stratagem tiles ---
TILE_BG = (58, 62, 68, 255)        # dark grey tile
FRAME = (150, 158, 165, 255)       # thin inner border
GLYPH = (94, 184, 232, 255)        # eagle blue
GLYPH_HI = (160, 216, 245, 255)    # lighter blue edge shine
TAB = (94, 184, 232, 255)          # corner tab blue

img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# tile
r = int(S * 0.06)
d.rounded_rectangle([4, 4, S - 4, S - 4], radius=r, fill=TILE_BG)

# inner thin frame (double line look like vanilla tiles)
d.rounded_rectangle([int(S*0.055), int(S*0.055), S - int(S*0.055), S - int(S*0.055)],
                    radius=int(r * 0.7), outline=FRAME, width=max(2, S // 256))
d.rounded_rectangle([int(S*0.085), int(S*0.085), S - int(S*0.085), S - int(S*0.085)],
                    radius=int(r * 0.5), outline=FRAME, width=max(1, S // 512))

# small blue tab top-right corner
tab_w, tab_h = int(S * 0.10), int(S * 0.065)
tx0, ty0 = S - int(S * 0.16), int(S * 0.075)
d.rounded_rectangle([tx0, ty0, tx0 + tab_w, ty0 + tab_h], radius=int(tab_h * 0.4), fill=TAB)

# ---- eagle jet glyph (top-down silhouette, nose up) ----
cx = S // 2
# fuselage: long dart from nose (top) to tail
fus = [
    (cx, int(S*0.16)),                    # nose tip
    (cx + int(S*0.035), int(S*0.30)),     # canopy right
    (cx + int(S*0.045), int(S*0.52)),     # mid body right
    (cx + int(S*0.05),  int(S*0.72)),     # tail body right
    (cx - int(S*0.05),  int(S*0.72)),     # tail body left
    (cx - int(S*0.045), int(S*0.52)),     # mid body left
    (cx - int(S*0.035), int(S*0.30)),     # canopy left
]
d.polygon(fus, fill=GLYPH)

# swept delta wings (big triangle each side, slight notch)
lw = [(cx - int(S*0.04), int(S*0.40)),
      (cx - int(S*0.30), int(S*0.58)),
      (cx - int(S*0.335), int(S*0.62)),
      (cx - int(S*0.05), int(S*0.56))]
rw = [(cx + int(S*0.04), int(S*0.40)),
      (cx + int(S*0.30), int(S*0.58)),
      (cx + int(S*0.335), int(S*0.62)),
      (cx + int(S*0.05), int(S*0.56))]
d.polygon(lw, fill=GLYPH)
d.polygon(rw, fill=GLYPH)

# tail fins (small outward stubs near the back)
lt = [(cx - int(S*0.04), int(S*0.66)),
      (cx - int(S*0.13), int(S*0.75)),
      (cx - int(S*0.05), int(S*0.74))]
rt = [(cx + int(S*0.04), int(S*0.66)),
      (cx + int(S*0.13), int(S*0.75)),
      (cx + int(S*0.05), int(S*0.74))]
d.polygon(lt, fill=GLYPH)
d.polygon(rt, fill=GLYPH)

# engine nozzle hint at tail (darker cut) + canopy shine
d.polygon([(cx - int(S*0.03), int(S*0.70)),
           (cx + int(S*0.03), int(S*0.70)),
           (cx + int(S*0.02), int(S*0.735)),
           (cx - int(S*0.02), int(S*0.735))], fill=TILE_BG)
d.polygon([(cx - int(S*0.014), int(S*0.26)),
           (cx + int(S*0.014), int(S*0.26)),
           (cx + int(S*0.02), int(S*0.30)),
           (cx - int(S*0.02), int(S*0.30))], fill=GLYPH_HI)

img.save(r"C:\Users\jacks\HQ\downloads\hd2-mods\eagle_icon.png")
print("saved eagle_icon.png")
