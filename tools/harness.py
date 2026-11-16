"""Run ForeverGBPlayer.lua outside WoW, under real Lua 5.1 (via lupa), with a
minimal mock of the WoW API. Catches runtime errors, checks that the atlas
texcoords select the right pixels, and runs /fgb bench.

Timings here are Lua-side only (mock API calls are empty Lua functions), so
treat them as a LOWER bound on what WoW will show.

    py -m pip install lupa
    py tools/harness.py
"""
import hashlib
import pathlib
import re
import struct
import sys
import time

from lupa import lua51

ROOT = pathlib.Path(__file__).resolve().parent.parent
ADDON = ROOT / "ForeverGBPlayer" / "ForeverGBPlayer.lua"
CORE = ROOT / "ForeverGBPlayer" / "core" / "Core.lua"
ATLAS = ROOT / "ForeverGBPlayer" / "media" / "atlas4.tga"

MOCK = r"""
local calls = { SetTexCoord = 0, SetColorTexture = 0, CreateTexture = 0 }
MOCK_CALLS = calls
MOCK_TEXCOORDS = {}  -- last texcoord set on the first texture created by atlas
local function noop() end

local Region = {}
Region.__index = Region
for _, m in ipairs({ "SetSize", "SetPoint", "SetAllPoints", "ClearAllPoints", "SetText",
    "SetJustifyH", "SetFrameStrata", "SetClampedToScreen", "SetMovable", "EnableMouse",
    "RegisterForDrag", "StartMoving", "StopMovingOrSizing", "RegisterEvent" }) do
    Region[m] = noop
end
function Region:RegisterForClicks(...) self._clicks = { ... } end
MOCK_COMBAT = false
function InCombatLockdown() return MOCK_COMBAT end
-- Override bindings: key -> button name. Protected in combat, like the real API.
MOCK_BINDINGS = {}
function SetOverrideBindingClick(owner, priority, key, buttonName)
    assert(not MOCK_COMBAT, "SetOverrideBindingClick in combat (protected)")
    assert(type(key) == "string" and type(buttonName) == "string")
    assert(_G[buttonName], "binding to a button with no global name: " .. buttonName)
    MOCK_BINDINGS[key] = buttonName
end
function ClearOverrideBindings(owner)
    assert(not MOCK_COMBAT, "ClearOverrideBindings in combat (protected)")
    MOCK_BINDINGS = {}
end
-- What WoW does when a bound key goes down/up: click the bound button. Returns false
-- if the key is not overridden (i.e. it would reach the game's normal bindings).
function MOCK_KEY(key, down)
    local name = MOCK_BINDINGS[key]
    if not name then return false end
    local b = _G[name]
    b._scripts.OnClick(b, "LeftButton", down)
    return true
end
function Region:Show() self._shown = true end
function Region:Hide() self._shown = false end
function Region:IsShown() return self._shown end
function Region:SetScale(s) self._scale = s end
function Region:GetEffectiveScale() return 0.71 end
function Region:SetScript(name, fn) self._scripts = self._scripts or {}; self._scripts[name] = fn end
function Region:SetTexture(path, wh, wv, filter)
    assert(type(path) == "string" and wh and wv and filter, "SetTexture args")
end
function Region:SetTexCoord(l, r, t, b)
    calls.SetTexCoord = calls.SetTexCoord + 1
    self._tc = { l, r, t, b }
end
function Region:SetColorTexture(r, g, b, a)
    assert(type(r) == "number" and type(g) == "number" and type(b) == "number", "SetColorTexture args")
    calls.SetColorTexture = calls.SetColorTexture + 1
    self._r, self._g, self._b = r, g, b
end
time = os.time
date = os.date
function Region:CreateTexture(name, layer)
    calls.CreateTexture = calls.CreateTexture + 1
    return setmetatable({ _shown = true }, Region)
end
function Region:CreateFontString(name, layer, template)
    return setmetatable({ _shown = true }, Region)
end

ALL_FRAMES = {}
function CreateFrame(kind, name, parent, template)
    local f = setmetatable({ _shown = true }, Region)
    if name then _G[name] = f end
    ALL_FRAMES[#ALL_FRAMES + 1] = f
    return f
end
-- Fire every frame's OnUpdate once (what WoW does each rendered frame).
-- Sound: a simulated clock plus a log of every PlaySoundFile / StopSound call.
MOCK_TIME = 1000
MOCK_SOUND_LOG = {}
local nextHandle = 0
function GetTime() return MOCK_TIME end
function PlaySoundFile(path, channel)
    assert(type(path) == "string" and path:find("^Interface\\AddOns\\"), "bad sound path")
    nextHandle = nextHandle + 1
    MOCK_SOUND_LOG[#MOCK_SOUND_LOG + 1] = { op = "play", t = MOCK_TIME, path = path, handle = nextHandle }
    return true, nextHandle
end
function StopSound(handle, fade)
    MOCK_SOUND_LOG[#MOCK_SOUND_LOG + 1] = { op = "stop", t = MOCK_TIME, handle = handle, fade = fade or 0 }
end

function MOCK_TICK(elapsed)
    MOCK_TIME = MOCK_TIME + elapsed
    for _, f in ipairs(ALL_FRAMES) do
        local s = f._scripts and f._scripts.OnUpdate
        if s then s(f, elapsed) end
    end
end
UIParent = CreateFrame("Frame")
SlashCmdList = {}
function GetPhysicalScreenSize() return 2560, 1440 end
function GetFramerate() return 60 end
function debugprofilestop() return os.clock() * 1000 end
PRINTED = {}
local rawprint = print
function print(...)
    local parts = {}
    for i = 1, select("#", ...) do parts[#parts + 1] = tostring(select(i, ...)) end
    local line = table.concat(parts, " ")
    PRINTED[#PRINTED + 1] = line
    rawprint(line)
end
"""


def read_tga(path):
    data = path.read_bytes()
    w, h = struct.unpack_from("<HH", data, 12)
    px = data[18:]
    def get(x, y):  # y top-down; file is bottom-up
        o = ((h - 1 - y) * w + x) * 4
        b, g, r, a = px[o:o + 4]
        return (r, g, b)
    return w, h, get


SHADES = " .+#"


def dump_fb(lua, y0, y1, x0=0, x1=160):
    fb = lua.globals().ForeverGBPlayer.fb
    for y in range(y0, y1):
        print("  |" + "".join(SHADES[fb[y * 160 + x + 1]] for x in range(x0, x1)) + "|")


def load_pack(lua, addon_dir):
    """Load a ROM pack addon the way WoW does: read its .toc, then run each listed file
    with `...` = the addon's folder name (ForeverGBPlayer is already loaded: the dependency)."""
    toc = (addon_dir / f"{addon_dir.name}.toc").read_text(encoding="ascii")
    if "## Dependencies: ForeverGBPlayer" not in toc:
        sys.exit(f"{addon_dir.name}: .toc doesn't depend on ForeverGBPlayer")
    loadstring = lua.eval("loadstring")
    for f in (l.strip() for l in toc.splitlines()):
        if not f or f.startswith("#"):
            continue
        src = (addon_dir / f).read_text(encoding="ascii")
        chunk = loadstring(src, "@" + f)
        if chunk is None:
            sys.exit(f"{addon_dir.name}/{f}: Lua syntax error")
        chunk(addon_dir.name)
    return len(toc)


TEST_PACK_ROMS = [
    ROOT / "testroms" / "acid2" / "dmg-acid2.gb",
    ROOT / "testroms" / "acid2" / "cgb-acid2.gbc",
    ROOT / "testroms" / "blargg" / "cpu_instrs" / "cpu_instrs.gb",
]


def test_roms(lua, slash):
    """Build ROM pack addons for the test ROMs, load them like WoW, check every ROM end
    to end, then exercise the RegisterRom API's edge cases."""
    sys.path.insert(0, str(ROOT / "tools"))
    import rom2lua
    import tempfile
    roms = [p for p in TEST_PACK_ROMS if p.exists()]
    if not roms:
        print("ROM tests skipped: testroms/ not present")
        return
    with tempfile.TemporaryDirectory() as tmp:
        for p in roms:
            out, name, _, _ = rom2lua.convert(p, None, pathlib.Path(tmp))
            t0 = time.perf_counter()
            load_pack(lua, out.parent)
            print(f"loaded pack {out.parent.name}: {out.stat().st_size:,} bytes of Lua "
                  f"in {(time.perf_counter() - t0) * 1000:.1f} ms")
        # Also check a pack whose main addon is missing (fresh runtime, mock only).
        lone = lua51.LuaRuntime(unpack_returned_tuples=True)
        lone.execute(MOCK)
        load_pack(lone, pathlib.Path(tmp) / "ForeverGBPlayer_Rom_dmg_acid2")
        lone_msgs = list(lone.globals().PRINTED.values())

    g = lua.globals()
    api = g.ForeverGBPlayer
    failures = []

    def check(label, cond):
        print(f"  {'ok  ' if cond else 'FAIL'} {label}")
        if not cond:
            failures.append(label)

    reg = lua.eval("function(r, s) local ok, err = ForeverGBPlayer.RegisterRom(r, s); return ok, err end")
    names = list(api.ListRoms().values())
    check(f"API_VERSION 1, ListRoms() sorted: {names}", api.API_VERSION == 1 and names == sorted(names))
    check("GetRom is case-insensitive and records the source addon",
          api.GetRom("DMG-ACID2").source == "ForeverGBPlayer_Rom_dmg_acid2")
    ok, err = reg(api.GetRom("dmg-acid2"), "SomeOtherPack")
    check("registering the same ROM twice is accepted quietly", ok is True)
    fake = lua.eval("""function(src) local r = {} for k, v in pairs(src) do r[k] = v end
        r.sha1 = "different"; return r end""")(api.GetRom("dmg-acid2"))
    ok, err = reg(fake, "SomeOtherPack")
    check(f"a different ROM with a taken name is refused: {err}", ok is False and "already registered" in err)
    bad = lua.eval("""function() return { name = "broken", numBanks = 2, size = 32768, cartType = 0,
        banks = { [0] = string.rep("x", 16384), [1] = "short" } } end""")()
    ok, err = reg(bad, "BrokenPack")
    check(f"a truncated ROM is refused: {err}", ok is False and "bank 1" in err)
    ok, err = reg(lua.eval('{ name = "Bad Name" }'), "x")
    check("an invalid name is refused", ok is False)
    check("a pack without ForeverGBPlayer prints a clear message instead of erroring",
          any("isn't loaded" in m for m in lone_msgs))
    if failures:
        sys.exit(f"ROM API test failed: {failures}")

    to_hex = lua.eval(r"""function(rom)
        local parts = {}
        for b = 0, rom.numBanks - 1 do
            parts[#parts + 1] = (rom.banks[b]:gsub(".", function(c) return string.format("%02x", c:byte()) end))
        end
        return table.concat(parts)
    end""")
    lib = lua.globals().GBRomLibrary
    ns = lua.globals().ForeverGBPlayer
    for name in sorted(lib.keys()):
        rom = lib[name]
        data = bytes.fromhex(to_hex(rom))
        sha_ok = hashlib.sha1(data).hexdigest() == rom.sha1 and len(data) == rom.size
        size_ok, hdr_ok, glob_ok = ns.VerifyRom(rom)
        print(f"ROM {name}: {len(data):,} bytes, sha1 round-trip {'OK' if sha_ok else 'MISMATCH'}, "
              f"Lua VerifyRom size={size_ok} header={hdr_ok} global={glob_ok}")
        if not (sha_ok and size_ok and hdr_ok):
            sys.exit(f"ROM {name} failed verification")

        slash("roms")
        slash("logo " + name)
        print("  logo from ROM header (rows 56-71):")
        dump_fb(lua, 56, 72, 32, 128)

        # pick the densest 16-byte-aligned stretch past the header to show as tiles
        best = max(range(0x150, len(data) - 0x1680, 0x100),
                   key=lambda o: sum(1 for b in data[o:o + 0x400] if b))
        slash(f"tiles {name} 0x{best:X}")
        print(f"  tiles view @ 0x{best:X} (first 2 tile rows):")
        dump_fb(lua, 0, 16)
    slash("stop")


def test_cpu_command(lua, slash):
    """Run a Blargg ROM through the in-addon /fgb cpu path until it reports a result."""
    rom_path = ROOT / "testroms" / "blargg" / "cpu_instrs" / "individual" / "06-ld r,r.gb"
    if not rom_path.exists():
        print("cpu command test skipped: testroms/ not present")
        return
    name = load_rom_into(lua, rom_path, "blargg-06")
    printed = lua.globals().PRINTED
    start = len(printed)
    slash("cpu " + name)
    tick = lua.globals().MOCK_TICK
    for _ in range(600):
        tick(1 / 60)
        lines = [printed[i] for i in range(start + 1, len(printed) + 1)]
        if any("PASSED" in l or "FAILED" in l for l in lines):
            break
    lines = [printed[i] for i in range(start + 1, len(printed) + 1)]
    if not any("PASSED" in l for l in lines):
        sys.exit("/fgb cpu did not report PASSED")


def test_play(lua, slash):
    """/fgb play dmg-acid2, then decode what the atlas textures show and compare with
    the reference image: covers core -> framebuffer -> renderer -> texcoords end to end."""
    ref_png = ROOT / "testroms" / "acid2" / "reference-dmg.png"
    if lua.globals().GBRomLibrary["dmg-acid2"] is None or not ref_png.exists():
        print("play test skipped: needs testroms/acid2/dmg-acid2.gb and reference-dmg.png")
        return
    sys.path.insert(0, str(ROOT / "tools"))
    from test_ppu import reference_shades
    slash("atlas")
    slash("play dmg-acid2")
    tick = lua.globals().MOCK_TICK
    for _ in range(60):
        tick(1 / 60)
    shown = lua.eval(r"""function(segs)
        local out = {}
        for s = 1, 5760 do
            local tc = segs[s]._tc
            local col = math.floor(tc[1] * 16 + 0.5)
            local row = math.floor((tc[3] * 64 - 1) / 4 + 0.5)
            local p = row * 16 + col
            out[#out + 1] = string.format("%d%d%d%d",
                math.floor(p / 64) % 4, math.floor(p / 16) % 4, math.floor(p / 4) % 4, p % 4)
        end
        return table.concat(out)
    end""")(lua.globals().ForeverGBPlayer.renderers["atlas"].segs)
    ours = [int(c) for c in shown]
    ref = reference_shades(ref_png)
    bad = sum(1 for a, b in zip(ours, ref) if a != b)
    print(f"play dmg-acid2 through atlas renderer: {'MATCH' if bad == 0 else f'{bad} pixels differ'}")
    slash("report")
    slash("stop")
    if bad:
        sys.exit("play test failed")


def load_rom_into(lua, rom_path, name):
    """Convert a ROM into a pack addon and load it through the real RegisterRom API."""
    sys.path.insert(0, str(ROOT / "tools"))
    import rom2lua
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        out, name, _, _ = rom2lua.convert(rom_path, name, pathlib.Path(tmp))
        load_pack(lua, out.parent)
    return name


def test_color_play(lua, slash):
    """/fgb play cgb-acid2 must pick the pixel renderer and show the reference colours."""
    ref_png = ROOT / "testroms" / "acid2" / "reference-cgb.png"
    if lua.globals().GBRomLibrary["cgb-acid2"] is None or not ref_png.exists():
        print("colour play test skipped: needs testroms/acid2/cgb-acid2.gbc and reference-cgb.png")
        return
    from test_ppu import reference_rgb555
    g = lua.globals()
    slash("play cgb-acid2")
    for _ in range(60):
        g.MOCK_TICK(1 / 60)
    slash("atlas")  # must be refused for a CGB game
    px = g.ForeverGBPlayer.renderers["pixel"].px
    shown = lua.eval("""function(px)
        local t = {}
        for i = 1, 23040 do
            local x = px[i]
            local r, g, b = math.floor(x._r * 31 + 0.5), math.floor(x._g * 31 + 0.5), math.floor(x._b * 31 + 0.5)
            t[i] = r + g * 32 + b * 1024
        end
        return table.concat(t, ",")
    end""")(px)
    ours = [int(v) for v in shown.split(",")]
    ref = reference_rgb555(ref_png)
    bad = sum(1 for a, b in zip(ours, ref) if a != b)
    print(f"play cgb-acid2 through pixel renderer (colour): {'MATCH' if bad == 0 else f'{bad} pixels differ'}")
    slash("stop")
    if bad:
        sys.exit("colour play test failed")


def test_saves(lua, slash):
    """Battery RAM -> ForeverGBPlayerDB on PLAYER_LOGOUT / stop, and back on the next play."""
    rom_path = ROOT / "testroms" / "cgb" / "save-test.gb"
    if not rom_path.exists():
        print("save test skipped: run tools/make_cgb_tests.py")
        return
    g = lua.globals()
    name = load_rom_into(lua, rom_path, "save-test")
    sha1 = g.GBRomLibrary[name].sha1

    def fire(event):
        for f in g.ALL_FRAMES.values():
            if f._scripts and f._scripts.OnEvent:
                f._scripts.OnEvent(f, event)

    def counters():
        d = g.ForeverGBPlayerDB.saves[sha1].data
        return int(d[0:2], 16), int(d[2 * 0x4000:2 * 0x4000 + 2], 16)

    failures = []

    def check(label, cond):
        print(f"  {'ok  ' if cond else 'FAIL'} {label}")
        if not cond:
            failures.append(label)

    slash("play " + name)
    for _ in range(10):
        g.MOCK_TICK(1 / 60)
    fire("PLAYER_LOGOUT")
    check("PLAYER_LOGOUT writes the save into ForeverGBPlayerDB", g.ForeverGBPlayerDB.saves[sha1] is not None)
    check("boot 1 counters 00/02", counters() == (0x00, 0x02))
    slash("play " + name)  # like a /reload: new core, save loaded
    for _ in range(10):
        g.MOCK_TICK(1 / 60)
    slash("stop")
    check("stop flushes; boot 2 continued from the save (01/05)", counters() == (0x01, 0x05))
    check("save stored as a plain string", type(g.ForeverGBPlayerDB.saves[sha1].data) is str)
    slash("roms")
    if failures:
        sys.exit(f"save test failed: {failures}")
    print("save test: PASS")


def test_input(lua, slash):
    """Keyboard -> SetButton via the real OnKeyDown/OnKeyUp handlers, on the joypad test
    ROM, plus frame pacing (144 WoW fps must still give ~60 GB frames per second)."""
    rom_path = ROOT / "testroms" / "joypad" / "joypad-test.gb"
    if not rom_path.exists():
        print("input test skipped: run tools/make_joypad_test.py")
        return
    sys.path.insert(0, str(ROOT / "tools"))
    import rom2lua
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        out, name, _, _ = rom2lua.convert(rom_path, "joypad-test", pathlib.Path(tmp))
        lua.eval("loadstring")(out.read_text(encoding="ascii"), "@" + out.name)()

    g = lua.globals()
    tick = g.MOCK_TICK
    root = g.ForeverGBPlayerFrame
    slash("play " + name)
    core = g.ForeverGBPlayer.play.core
    key = g.MOCK_KEY
    failures = []

    def check(label, cond):
        print(f"  {'ok  ' if cond else 'FAIL'} {label}")
        if not cond:
            failures.append(label)

    def bound():
        return sorted(g.MOCK_BINDINGS.keys())

    def fire(event):
        for f in g.ALL_FRAMES.values():
            if f._scripts and f._scripts.OnEvent:
                f._scripts.OnEvent(f, event)

    check("keys overridden after /fgb play", "UP" in bound() and "]" in bound() and "[" in bound() and "X" not in bound() and "ESCAPE" in bound())
    tick(1 / 60)
    check("UP is bound to us (not moving the character)", key("UP", True))
    tick(1 / 60)
    check("UP -> d-pad up read by ROM, 1 IRQ", (core.Read(0xC000), core.Read(0xC002)) == (0xEB, 1))
    check("unmapped key T keeps its normal binding", not key("T", True))
    key("ENTER", True)
    tick(1 / 60)
    check("ENTER -> start read by ROM, 2 IRQs", (core.Read(0xC001), core.Read(0xC002)) == (0xD7, 2))
    key("UP", False)
    key("ENTER", False)
    key("]", True)
    tick(1 / 60)
    check("release + ] -> only A held", (core.Read(0xC000), core.Read(0xC001), core.Read(0xC002)) == (0xEF, 0xDE, 3))
    key("ESCAPE", True)
    check("ESC releases keyboard (all overrides cleared)", bound() == [])
    root._scripts.OnMouseDown(root)
    check("click re-captures", "UP" in bound())

    # WoW fires PLAYER_REGEN_DISABLED just before lockdown starts.
    fire("PLAYER_REGEN_DISABLED")
    g.MOCK_COMBAT = True
    check("combat releases keyboard", bound() == [])
    root._scripts.OnMouseDown(root)
    check("click in combat does not capture (and doesn't touch protected API)", bound() == [])
    g.MOCK_COMBAT = False
    fire("PLAYER_REGEN_ENABLED")

    # Lockdown already active when releasing: the clear is deferred to combat end.
    root._scripts.OnMouseDown(root)
    g.MOCK_COMBAT = True
    slash("atlas")  # stays in play mode
    slash("static")  # leaving play mode releases focus -> must not call protected API now
    check("release during lockdown defers the clear", "UP" in bound())
    g.MOCK_COMBAT = False
    fire("PLAYER_REGEN_ENABLED")
    check("...and clears once combat ends", bound() == [])
    slash("play " + name)
    core = g.ForeverGBPlayer.play.core

    c0 = core.GetCycles()
    for _ in range(144):
        tick(1 / 144)
    frames = (core.GetCycles() - c0) / 70224
    check(f"1s at 144 fps ran {frames:.1f} GB frames (~59.7)", 58.5 <= frames <= 61)
    c0 = core.GetCycles()
    for _ in range(30):
        tick(1 / 30)
    frames = (core.GetCycles() - c0) / 70224
    check(f"1s at 30 fps ran {frames:.1f} GB frames (~59.7)", 58.5 <= frames <= 61)
    slash("keys")
    key("LEFT", True)
    slash("keys")
    slash("stop")
    check("stop releases keyboard", bound() == [])
    if failures:
        sys.exit(f"input test failed: {failures}")
    print("input test: PASS")


def main():
    lua = lua51.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(MOCK)
    for path in (CORE, ADDON):  # same order as the .toc
        chunk = lua.eval("loadstring")(path.read_text(encoding="utf-8"), "@" + path.name)
        if chunk is None:
            sys.exit(f"syntax error loading {path.name}")
        chunk("ForeverGBPlayer")
    slash = lua.globals().SlashCmdList.FOREVERGB

    # --- atlas correctness: sample texture at every 4px segment's texcoords ---
    w, h, get = read_tga(ATLAS)
    palette = [(224, 248, 208), (136, 192, 112), (52, 104, 86), (8, 24, 32)]
    check = lua.execute(r"""
        local out = {}
        -- re-derive texcoords exactly as the addon does
        for p = 0, 255 do
            local col, row = p % 16, math.floor(p / 16)
            out[p] = { (col*4)/64, (col*4+4)/64, (row*4+1)/64, (row*4+3)/64 }
        end
        return out
    """)
    bad = 0
    for p in range(256):
        l, r, t, b = (check[p][i] for i in range(1, 5))
        expected = [(p >> 6) & 3, (p >> 4) & 3, (p >> 2) & 3, p & 3]
        for k in range(4):  # nearest sampling at each output pixel centre
            u = l + (r - l) * (k + 0.5) / 4
            for v in (t + (b - t) * 0.25, t + (b - t) * 0.75):
                got = get(int(u * w), int(v * h))
                if got != palette[expected[k]]:
                    bad += 1
    print(f"atlas check: {'OK' if bad == 0 else f'{bad} BAD samples'} (256 patterns x 4 px x 2 rows)")

    # --- drive the addon ---
    frame = lua.globals().ForeverGBPlayerFrame

    slash("help")
    slash("")  # start (atlas/sprites)
    driver_onupdate = lua.execute(r"""
        -- find the driver's OnUpdate via the upvalues of the slash handler
        local fn = SlashCmdList.FOREVERGB
        local function scan(f, seen)
            seen = seen or {}
            if seen[f] then return end
            seen[f] = true
            for i = 1, 60 do
                local n, v = debug.getupvalue(f, i)
                if not n then break end
                if n == "driver" and v and v._scripts then return v end
                if type(v) == "function" then
                    local r = scan(v, seen)
                    if r then return r end
                end
            end
        end
        return scan(fn)._scripts.OnUpdate
    """)
    assert driver_onupdate is not None, "driver OnUpdate not set"
    for _ in range(120):
        driver_onupdate()
    slash("report")
    for cmd in ("pixel", "scroll", "force", "force", "scale 4", "scale 99", "atlas", "bogus"):
        slash(cmd)
        for _ in range(61):
            driver_onupdate()
    slash("report")

    slash("bench")
    frames = 0
    while frames < 5000:
        driver_onupdate()
        frames += 1
        printed = list(lua.globals().PRINTED.values())
        if any(line.strip().startswith("create ") for line in printed[-3:]):
            break
    slash("stop")
    test_roms(lua, slash)
    test_cpu_command(lua, slash)
    test_play(lua, slash)
    test_input(lua, slash)
    test_color_play(lua, slash)
    test_saves(lua, slash)
    calls = lua.globals().MOCK_CALLS
    print(f"mock totals: CreateTexture={calls.CreateTexture} "
          f"SetTexCoord={calls.SetTexCoord} SetColorTexture={calls.SetColorTexture}")
    print("harness finished without Lua errors")


if __name__ == "__main__":
    main()
