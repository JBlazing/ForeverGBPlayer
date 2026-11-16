"""Convert Game Boy / Game Boy Color ROMs (.gb / .gbc) into ROM pack addons for
ForeverGBPlayer (addons have no file I/O, so ROM data has to ship as Lua source).

    py tools/rom2lua.py path/to/game.gb [more.gbc ...] [--name NAME] [--out-dir DIR]

Each ROM becomes its own small addon (default --out-dir: rom-addons/ in the repo;
point it at World of Warcraft/<flavor>/Interface/AddOns to install directly):

  ForeverGBPlayer_Rom_<name>/
    ForeverGBPlayer_Rom_<name>.toc (+ _Camelot, _TBC)   "## Dependencies: ForeverGBPlayer"
    <name>.lua   builds the ROM table and calls ForeverGBPlayer.RegisterRom(rom, addonName)
                 at load. Each 16 KB bank is one Lua string; read byte at absolute
                 address A with string.byte(rom.banks[floor(A / 0x4000)], A % 0x4000 + 1).

The dependency makes WoW load ForeverGBPlayer first, so the ROM is registered while the
game starts. Disable or delete the pack to remove the ROM; no shared file to edit.

Bytes are written as plain characters when printable ASCII and as 3-digit
decimal escapes (\\ddd) otherwise, which every Lua 5.1 lexer (WoW's included)
reads natively and with no decode step at load time. Expect the .lua to be
roughly 2-3x the ROM size on disk; in memory it is ~1x.

.gba files are rejected: that is a different console (ARM CPU) and needs a
different emulator entirely.
"""
import argparse
import hashlib
import pathlib
import re
import sys

BANK = 0x4000
CHUNK = 512  # bytes per string literal; keeps source lines ~1-2 KB

NINTENDO_LOGO = bytes.fromhex(
    "CEED6666CC0D000B03730083000C000D0008111F8889000EDCCC6EE6DDDDD999"
    "BBBB67636E0EECCCDDDC999FBBB9333E"
)

CART_TYPES = {
    0x00: "ROM ONLY", 0x01: "MBC1", 0x02: "MBC1+RAM", 0x03: "MBC1+RAM+BATTERY",
    0x05: "MBC2", 0x06: "MBC2+BATTERY", 0x08: "ROM+RAM", 0x09: "ROM+RAM+BATTERY",
    0x0F: "MBC3+TIMER+BATTERY", 0x10: "MBC3+TIMER+RAM+BATTERY", 0x11: "MBC3",
    0x12: "MBC3+RAM", 0x13: "MBC3+RAM+BATTERY", 0x19: "MBC5", 0x1A: "MBC5+RAM",
    0x1B: "MBC5+RAM+BATTERY", 0x1C: "MBC5+RUMBLE", 0x1D: "MBC5+RUMBLE+RAM",
    0x1E: "MBC5+RUMBLE+RAM+BATTERY",
}
RAM_SIZES = {0x00: 0, 0x01: 2 * 1024, 0x02: 8 * 1024, 0x03: 32 * 1024, 0x04: 128 * 1024, 0x05: 64 * 1024}

DEFAULT_OUT = pathlib.Path(__file__).resolve().parent.parent / "rom-addons"
ADDON_PREFIX = "ForeverGBPlayer_Rom_"
# .toc variants, mirroring ForeverGBPlayer's own: (file suffix, Interface, AllowLoadGameType)
TOC_FLAVORS = [("", 16001, "camelot"), ("_Camelot", 16001, "camelot"), ("_TBC", 20506, None)]


class RomError(Exception):
    pass


def parse_header(rom):
    if len(rom) < 0x150:
        raise RomError(f"file is only {len(rom)} bytes; too small to be a Game Boy ROM")
    cgb_flag = rom[0x143]
    title_end = 0x143 if cgb_flag in (0x80, 0xC0) else 0x144
    title = rom[0x134:title_end].split(b"\0", 1)[0].decode("ascii", "replace").strip()

    hdr = 0
    for b in rom[0x134:0x14D]:
        hdr = (hdr - b - 1) & 0xFF
    glob = (sum(rom) - rom[0x14E] - rom[0x14F]) & 0xFFFF

    rom_size_code = rom[0x148]
    return {
        "title": title,
        "cgb_flag": cgb_flag,
        "cgb": {0x80: "supported", 0xC0: "required"}.get(cgb_flag, "no"),
        "sgb": rom[0x146] == 0x03,
        "cart_type": rom[0x147],
        "cart_name": CART_TYPES.get(rom[0x147], f"unknown 0x{rom[0x147]:02X}"),
        "rom_size_declared": (32 * 1024) << rom_size_code if rom_size_code <= 8 else None,
        "ram_size": RAM_SIZES.get(rom[0x149]),
        "logo_ok": rom[0x104:0x134] == NINTENDO_LOGO,
        "header_checksum": rom[0x14D],
        "header_checksum_ok": hdr == rom[0x14D],
        "global_checksum": (rom[0x14E] << 8) | rom[0x14F],
        "global_checksum_ok": glob == ((rom[0x14E] << 8) | rom[0x14F]),
    }


def lua_string(data):
    out = ['"']
    n = len(data)
    for i, b in enumerate(data):
        if 0x20 <= b < 0x7F and b not in (0x22, 0x5C):  # printable, not " or \
            out.append(chr(b))
        elif i + 1 < n and 0x30 <= data[i + 1] <= 0x39:
            out.append(f"\\{b:03d}")  # next char is a digit: pad so it can't merge into the escape
        else:
            out.append(f"\\{b}")
    out.append('"')
    return "".join(out)


def sanitize_name(s):
    s = re.sub(r"[^a-z0-9_-]+", "-", s.lower()).strip("-")
    if not s:
        raise RomError("could not derive a ROM name; pass --name")
    return s


def lua_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return "nil"
    if isinstance(v, int):
        return str(v)
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def convert(src, name, out_dir):
    if src.suffix.lower() == ".gba":
        raise RomError(f"{src.name}: .gba is a Game Boy Advance ROM (ARM CPU) - not supported by a "
                       "Game Boy emulator. Use .gb or .gbc ROMs.")
    rom = src.read_bytes()
    hdr = parse_header(rom)

    if len(rom) % BANK != 0:
        raise RomError(f"{src.name}: size {len(rom)} is not a multiple of 16 KB")
    warnings = []
    if hdr["rom_size_declared"] and hdr["rom_size_declared"] != len(rom):
        warnings.append(f"header declares {hdr['rom_size_declared']} bytes, file has {len(rom)}")
    if not hdr["logo_ok"]:
        warnings.append("Nintendo logo mismatch (real hardware would refuse to boot)")
    if not hdr["header_checksum_ok"]:
        warnings.append("header checksum mismatch (real hardware would refuse to boot)")
    if not hdr["global_checksum_ok"]:
        warnings.append("global checksum mismatch (harmless; hardware ignores it)")

    name = sanitize_name(name or src.stem)
    addon = addon_name(name)
    files = {f"{addon}{suffix}.toc": toc_text(name, hdr, interface, game_type)
             for suffix, interface, game_type in TOC_FLAVORS}
    files[f"{name}.lua"] = lua_source(rom, src.name, name, hdr)

    out = out_dir / addon
    out.mkdir(parents=True, exist_ok=True)
    for fname, text in files.items():
        # newline="\n": keep LF; ROM bytes are escaped so line endings can't corrupt data
        (out / fname).write_text(text, encoding="ascii", newline="\n")
    return out / f"{name}.lua", name, hdr, warnings


def addon_name(name):
    """Addon folder name for a ROM name (folder names: letters, digits, underscores)."""
    return ADDON_PREFIX + re.sub(r"[^A-Za-z0-9_]", "_", name)


def toc_text(name, hdr, interface, game_type):
    title = re.sub(r"[^ -~]|\|", "", hdr["title"]) or name  # printable ASCII, no WoW escapes
    lines = [f"## Interface: {interface}"]
    if game_type:
        lines.append(f"## AllowLoadGameType: {game_type}")
    lines += [
        f"## Title: GB ROM: {title}",
        f"## Notes: Game Boy ROM for ForeverGBPlayer. Play it with /fgb play {name}",
        "## Dependencies: ForeverGBPlayer",
        "## Group: ForeverGBPlayer",
        "## Version: 1",
        "",
        f"{name}.lua",
    ]
    return "\n".join(lines) + "\n"


def lua_source(rom, file_name, name, hdr):
    nbanks = len(rom) // BANK
    sha1 = hashlib.sha1(rom).hexdigest()
    lines = [
        f"-- Generated by ForeverGBPlayer rom2lua from {file_name}. Do not edit.",
        "-- ROM pack addon: registers this ROM with ForeverGBPlayer while the game loads.",
        "local ADDON = ...",
        "local rom = {",
    ]
    meta = {
        "name": name, "file": file_name, "size": len(rom), "sha1": sha1,
        "title": hdr["title"], "cgbFlag": hdr["cgb_flag"], "cgb": hdr["cgb"], "sgb": hdr["sgb"],
        "cartType": hdr["cart_type"], "cartName": hdr["cart_name"], "ramSize": hdr["ram_size"],
        "numBanks": nbanks,
    }
    for k, v in meta.items():
        lines.append(f"    {k} = {lua_value(v)},")
    lines.append("    banks = {")
    for b in range(nbanks):
        bank = rom[b * BANK:(b + 1) * BANK]
        lines.append(f"        [{b}] = table.concat({{")
        for off in range(0, BANK, CHUNK):
            lines.append("            " + lua_string(bank[off:off + CHUNK]) + ",")
        lines.append("        }),")
    lines.append("    },")
    lines.append("}")
    lines += [
        "local api = ForeverGBPlayer",
        "if not (api and api.RegisterRom) then",
        '    print("|cffff6060" .. tostring(ADDON) .. ":|r ForeverGBPlayer isn\'t loaded, so this ROM wasn\'t added.")',
        "    return",
        "end",
        "local ok, err = api.RegisterRom(rom, ADDON)",
        'if not ok then print("|cffff6060" .. tostring(ADDON) .. ":|r " .. tostring(err)) end',
    ]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("roms", nargs="+", type=pathlib.Path)
    ap.add_argument("--name", help="library name (only with a single ROM); default: file stem")
    ap.add_argument("--out-dir", type=pathlib.Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    if args.name and len(args.roms) > 1:
        ap.error("--name only works with a single ROM")

    failed = False
    for src in args.roms:
        try:
            out, name, hdr, warnings = convert(src, args.name, args.out_dir)
        except (RomError, OSError) as e:
            print(f"ERROR: {e}", file=sys.stderr)
            failed = True
            continue
        print(f"{src.name} -> {out.parent} ({out.stat().st_size:,} bytes of Lua)")
        print(f"  name={name} title={hdr['title']!r} cart={hdr['cart_name']} "
              f"cgb={hdr['cgb']} ram={hdr['ram_size']}  ->  /fgb play {name}")
        for w in warnings:
            print(f"  WARNING: {w}")
    if not failed and args.out_dir.resolve() == DEFAULT_OUT.resolve():
        print(f"Copy the folder(s) from {DEFAULT_OUT} into World of Warcraft/<flavor>/Interface/AddOns, "
              "or pass --out-dir <that AddOns folder> to install directly. Then /reload.")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
