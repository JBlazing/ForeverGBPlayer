"""Generate the 4-pixel pattern atlas used by the ForeverGBPlayer addon.

A DMG Game Boy pixel is one of 4 shades (2 bits), so a horizontal run of
4 pixels has 4^4 = 256 possible patterns. Each pattern gets a 4x4 cell in a
64x64 texture (16 x 16 cells). The 4 rows of a cell are identical; the addon
samples only the middle two rows so that bilinear/neighbour bleed from the
cells above/below can never show up.

Pattern code p = s0*64 + s1*16 + s2*4 + s3, where s0 is the LEFTMOST pixel.
This must match the packing in ForeverGBPlayer.lua.

Output: uncompressed 32-bit TGA (WoW loads power-of-two .tga files directly).
"""
import pathlib
import struct

# Classic DMG green palette, lightest (shade 0) to darkest (shade 3).
PALETTE = [(224, 248, 208), (136, 192, 112), (52, 104, 86), (8, 24, 32)]
SIZE = 64
CELL = 4
CELLS_PER_ROW = SIZE // CELL  # 16


def build_pixels():
    img = [[(0, 0, 0)] * SIZE for _ in range(SIZE)]  # top-down rows
    for p in range(256):
        col, row = p % CELLS_PER_ROW, p // CELLS_PER_ROW
        shades = [(p >> 6) & 3, (p >> 4) & 3, (p >> 2) & 3, p & 3]
        for dy in range(CELL):
            for dx in range(CELL):
                img[row * CELL + dy][col * CELL + dx] = PALETTE[shades[dx]]
    return img


def write_tga(path, img):
    header = struct.pack(
        "<BBBHHBHHHHBB",
        0,      # id length
        0,      # no colour map
        2,      # uncompressed true-colour
        0, 0, 0,  # colour map spec
        0, 0,   # x/y origin
        SIZE, SIZE,
        32,     # bits per pixel
        8,      # 8 alpha bits, bottom-left origin
    )
    body = bytearray()
    for row in reversed(img):  # bottom-left origin => last row first
        for r, g, b in row:
            body += bytes((b, g, r, 255))
    path.write_bytes(header + body)


if __name__ == "__main__":
    out = pathlib.Path(__file__).resolve().parent.parent / "ForeverGBPlayer" / "media" / "atlas4.tga"
    out.parent.mkdir(parents=True, exist_ok=True)
    write_tga(out, build_pixels())
    print(f"wrote {out} ({out.stat().st_size} bytes)")
