-- ForeverGBPlayer: measures how fast a WoW addon can draw a 160x144, 4-shade
-- Game Boy screen. No emulation here - test patterns stand in for the PPU.
--
-- Renderers:
--   atlas : 5,760 textures, each showing a 4-pixel run picked from a 256-pattern
--           atlas via SetTexCoord (only called when that run changed).
--   pixel : 23,040 1x1 textures using SetColorTexture (only when changed).
--
-- Patterns:
--   static  : nothing changes after the first frame (dirty-check overhead only)
--   sprites : static background + 16 moving 8x8 blocks (typical game frame)
--   scroll  : every 4-pixel run changes every frame (worst case, e.g. full scroll)

local ADDON_NAME = ...
local floor, format = math.floor, string.format

local W, H = 160, 144
local NPIX = W * H
local SEG_W = 4
local SEGS_PER_ROW = W / SEG_W -- 40
local NSEG = SEGS_PER_ROW * H   -- 5760
local ATLAS_PATH = "Interface\\AddOns\\" .. ADDON_NAME .. "\\media\\atlas4"
local ATLAS_PX, CELL = 64, 4

local PREFIX = "|cff88c070ForeverGB|r: "
local function Print(...) print(PREFIX .. format(...)) end

------------------------------------------------------------------------------
-- Lookup tables
------------------------------------------------------------------------------
-- Shade 0..3, lightest to darkest. Must match tools/make_atlas.py.
local PAL_R = { [0] = 224 / 255, 136 / 255, 52 / 255, 8 / 255 }
local PAL_G = { [0] = 248 / 255, 192 / 255, 104 / 255, 24 / 255 }
local PAL_B = { [0] = 208 / 255, 112 / 255, 86 / 255, 32 / 255 }

-- Texcoords for pattern p = s0*64 + s1*16 + s2*4 + s3 (s0 = leftmost pixel).
-- Sample only the middle two texel rows of each 4x4 cell to avoid bleed.
local TC_L, TC_R, TC_T, TC_B = {}, {}, {}, {}
for p = 0, 255 do
    local col, row = p % 16, floor(p / 16)
    TC_L[p] = (col * CELL) / ATLAS_PX
    TC_R[p] = (col * CELL + CELL) / ATLAS_PX
    TC_T[p] = (row * CELL + 1) / ATLAS_PX
    TC_B[p] = (row * CELL + 3) / ATLAS_PX
end

------------------------------------------------------------------------------
-- Framebuffer + test patterns
------------------------------------------------------------------------------
local fb = {} -- 1-based, row-major, values 0..3
local BG = {}
for y = 0, H - 1 do
    for x = 0, W - 1 do
        local i = y * W + x + 1
        BG[i] = (floor(x / 16) + floor(y / 16)) % 4
        fb[i] = 0
    end
end

local function CopyBG()
    for i = 1, NPIX do fb[i] = BG[i] end
end

local STRIPE = {}
for k = 0, 11 do STRIPE[k] = floor(k / 3) end

local NSPR = 16
local sprites = {}

local patterns = {
    static = {
        reset = CopyBG,
        step = function() end,
    },
    scroll = {
        reset = function() end,
        step = function(t)
            -- Diagonal 3px stripes shifted by 1px per frame: every 4px run
            -- changes every frame.
            local i = 1
            for y = 0, H - 1 do
                local base = y + t
                for x = 0, W - 1 do
                    fb[i] = STRIPE[(x + base) % 12]
                    i = i + 1
                end
            end
        end,
    },
    sprites = {
        reset = function()
            CopyBG()
            for n = 1, NSPR do
                sprites[n] = {
                    x = (n * 37) % (W - 8), y = (n * 23) % (H - 8),
                    dx = (n % 2 == 0) and 1 or -1, dy = (n % 3 == 0) and 1 or -1,
                    drawn = false,
                }
            end
        end,
        step = function()
            for n = 1, NSPR do -- erase
                local s = sprites[n]
                if s.drawn then
                    for yy = 0, 7 do
                        local row = (s.y + yy) * W + s.x + 1
                        for xx = 0, 7 do fb[row + xx] = BG[row + xx] end
                    end
                end
            end
            for n = 1, NSPR do -- move + draw
                local s = sprites[n]
                s.x, s.y = s.x + s.dx, s.y + s.dy
                if s.x <= 0 or s.x >= W - 8 then s.dx = -s.dx end
                if s.y <= 0 or s.y >= H - 8 then s.dy = -s.dy end
                for yy = 0, 7 do
                    local row = (s.y + yy) * W + s.x + 1
                    local edge = (yy == 0 or yy == 7)
                    for xx = 0, 7 do
                        fb[row + xx] = (edge or xx == 0 or xx == 7) and 3 or 0
                    end
                end
                s.drawn = true
            end
        end,
    },
}

------------------------------------------------------------------------------
-- ROMs come from separate "ROM pack" addons (ForeverGBPlayer_Rom_<name>), made by
-- tools/rom2lua.py or tools/rom-converter.html. Each pack's .toc has
-- "## Dependencies: ForeverGBPlayer", so WoW loads this addon first, and the pack calls
-- the public API below while the game starts:
--
--   ForeverGBPlayer.API_VERSION                  -- 1
--   ForeverGBPlayer.RegisterRom(rom, source)     -- -> true | false, errorMessage
--   ForeverGBPlayer.GetRom(name)                 -- -> rom table | nil
--   ForeverGBPlayer.ListRoms()                   -- -> sorted array of names
--
-- rom = { name = "lowercase-name", title, size, sha1, cartType, cartName, cgbFlag, cgb,
--         ramSize, numBanks, banks = { [0] = <16384-byte string>, ... } }
------------------------------------------------------------------------------
local strbyte = string.byte
local romLibrary = {}
GBRomLibrary = romLibrary -- read-only view kept for older tools; register through the API

ForeverGBPlayer = ForeverGBPlayer or {}
ForeverGBPlayer.API_VERSION = 1

function ForeverGBPlayer.RegisterRom(rom, source)
    if type(rom) ~= "table" then return false, "RegisterRom expects a ROM table" end
    local name = rom.name
    if type(name) ~= "string" or not name:match("^[a-z0-9_%-]+$") then
        return false, "rom.name must be lowercase letters, digits, '-' or '_'"
    end
    local n = rom.numBanks
    if type(rom.banks) ~= "table" or type(n) ~= "number" or n < 1 or n % 1 ~= 0 then
        return false, name .. ": rom.banks / rom.numBanks are missing"
    end
    for b = 0, n - 1 do
        if type(rom.banks[b]) ~= "string" or #rom.banks[b] ~= 0x4000 then
            return false, format("%s: bank %d is missing or not 16 KB (truncated file?)", name, b)
        end
    end
    if rom.size ~= n * 0x4000 then return false, name .. ": rom.size doesn't match its banks" end
    if type(rom.cartType) ~= "number" then return false, name .. ": rom.cartType is missing" end
    local existing = romLibrary[name]
    if existing then
        if existing.sha1 == rom.sha1 then return true end -- the same ROM installed twice
        return false, format("a different ROM named '%s' is already registered by %s",
            name, tostring(existing.source))
    end
    rom.source = source or "unknown addon"
    romLibrary[name] = rom
    return true
end

function ForeverGBPlayer.GetRom(name)
    return type(name) == "string" and romLibrary[name:lower()] or nil
end

local function RomNames()
    local names = {}
    for name in pairs(romLibrary) do names[#names + 1] = name end
    table.sort(names)
    return names
end
ForeverGBPlayer.ListRoms = RomNames

local function RomByte(rom, addr) -- addr: absolute 0-based ROM address
    return strbyte(rom.banks[floor(addr / 0x4000)], addr % 0x4000 + 1)
end

local function FindRom(name)
    if name then return romLibrary[name:lower()] end
    local first = RomNames()[1]
    return first and romLibrary[first]
end

local NO_ROMS = "no games added yet. Open 'ROM Converter.html' in the ForeverGBPlayer addon folder, "
    .. "convert a game, drag its folder into AddOns and restart WoW."

-- Recomputes the cartridge checksums from the loaded Lua data.
local function VerifyRom(rom)
    local size = 0
    for b = 0, rom.numBanks - 1 do size = size + #rom.banks[b] end
    local hdr = 0
    for a = 0x134, 0x14C do hdr = (hdr - RomByte(rom, a) - 1) % 256 end
    local sum = 0
    for b = 0, rom.numBanks - 1 do
        local s = rom.banks[b]
        for i = 1, #s do sum = sum + strbyte(s, i) end
    end
    local stored = RomByte(rom, 0x14E) * 256 + RomByte(rom, 0x14F)
    sum = (sum - RomByte(rom, 0x14E) - RomByte(rom, 0x14F)) % 65536
    return size == rom.size, hdr == RomByte(rom, 0x14D), sum == stored
end

local view = { rom = nil, offset = 0 } -- ROM + byte offset for the logo/tiles patterns

------------------------------------------------------------------------------
-- Sound: all four Game Boy channels played from pre-rendered samples in sound\
-- (tools/make_sound_pack.py + tools/make_wave_pack.py). Addons can't synthesise audio,
-- change pitch or set per-sound volume, so each WoW frame every channel's state is
-- mapped to a file, which is started / stopped / restarted when the state changes.
--   ch 1+2 square: nearest semitone, 25/50% duty, 4 volume levels. A note with a fading
--                  envelope plays a file with that fade baked in, start to end, with no
--                  restarts (mid-note restarts were heard as uneven rhythm). Constant or
--                  rising volume restarts when the level changes.
--   ch 3 wave:     per-game waveform set (GBSoundWaves[pattern hex]), triangle if unknown.
--   ch 4 noise:    one file per NR43 setting; envelope followed by restarts (restarting
--                  noise doesn't click).
------------------------------------------------------------------------------
local SOUND_DIR = "Interface\\AddOns\\" .. ADDON_NAME .. "\\sound\\"
local function MidiTable(clock, lo, hi) -- 11-bit frequency register -> MIDI note or false
    local t = {}
    for x = 0, 2047 do
        local m = floor(69 + 12 * math.log(clock / (2048 - x) / 440) / math.log(2) + 0.5)
        t[x] = (m >= lo and m <= hi) and m or false
    end
    return t
end
local SQ_MIDI = MidiTable(131072, 36, 107)   -- square: f = 131072 / (2048 - x)
local WAVE_MIDI = MidiTable(65536, 24, 95)   -- wave: one 32-step period
local DUTY_FILE = { [0] = "25", "25", "50", "25" } -- 12.5%/75% approximated by 25%
local VOL_LEVEL = { [0] = 0 }
for v = 1, 15 do VOL_LEVEL[v] = floor((v + 3) / 4) end -- 1-4 / 5-8 / 9-12 / 13-15
local WAVE_LEVEL = { [15] = 3, [8] = 2, [4] = 1 }   -- 100% / 50% / 25%
local FILE_PREFIX = { "sq\\sq", "sq\\sq", "wave\\w", "noise\\n" }
local RETRIGGER_AFTER = { 1.9, 1.9, 1.9, 0.9 } -- just before each file type runs out

-- mode "envelope" (default): fading square notes use baked-fade files.
-- mode "steps": follow every envelope step by switching files (the first test version).
local sound = {
    enabled = true, mode = "envelope", fade = 0, plays = 0, since = 0,
    ch = { {}, {}, {}, {} }, use = { true, true, true, true },
}

local function SoundStop(a)
    if a.handle then StopSound(a.handle, sound.fade) end
    a.handle, a.base = nil, nil
end

local function SoundStopAll()
    for c = 1, 4 do
        SoundStop(sound.ch[c])
        sound.ch[c].trig = nil
    end
end

local function SoundUpdate(core)
    local st = core.GetAudioState()
    local now = GetTime()
    for c = 1, 4 do
        local s, a = st[c], sound.ch[c]
        -- base = timbre + pitch of what should be sounding (nil = silence)
        local base, level
        if sound.use[c] and s.on and s.vol > 0 and (s.left or s.right) then
            if c <= 2 then
                local m = SQ_MIDI[s.freq]
                if m then base, level = DUTY_FILE[s.duty] .. "_" .. m, VOL_LEVEL[s.vol] end
            elseif c == 3 then
                local m = WAVE_MIDI[s.freq]
                if m then
                    base = ((GBSoundWaves and GBSoundWaves[s.wave]) or "tri") .. "_" .. m
                    level = WAVE_LEVEL[s.vol]
                end
            elseif s.nr43 < 0xE0 then -- shift 14/15: noise LFSR not clocked
                base, level = tostring(s.nr43), VOL_LEVEL[s.vol]
            end
        end

        if not base then
            if a.base then SoundStop(a) end
        else
            local file
            local newNote = base ~= a.base or s.trig ~= a.trig
            if newNote then
                a.baked = c <= 2 and sound.mode == "envelope" and s.pace > 0 and not s.up
                if a.baked then file = "sq\\sqd" .. base .. "_" .. level .. "_" .. s.pace end
            end
            if not a.baked and (newNote or level ~= a.level or now - a.started >= RETRIGGER_AFTER[c]) then
                file = FILE_PREFIX[c] .. base .. "_" .. level
            end
            if file then
                SoundStop(a)
                local willPlay, handle = PlaySoundFile(SOUND_DIR .. file .. ".ogg", "Master")
                if willPlay then a.handle = handle end
                a.base, a.level, a.started = base, level, now
                sound.plays = sound.plays + 1
            end
        end
        a.trig = s.trig
    end
end

-- "play": the emulator itself is the pattern, and the renderer draws the core's
-- framebuffer instead of ours. Paced to the real Game Boy rate (59.73 Hz) whatever
-- WoW's frame rate is; runs at most 3 GB frames per WoW frame and drops time beyond
-- that (so a hitch slows the game briefly instead of fast-forwarding).
local GB_FRAME_S = 70224 / 4194304
local play = { core = nil, acc = 0 }
patterns.play = {
    reset = function() end,
    step = function(_, elapsed)
        local core = play.core
        if not core then return end
        local acc = play.acc + (elapsed or GB_FRAME_S)
        if acc > GB_FRAME_S * 3 then acc = GB_FRAME_S * 3 end
        while acc >= GB_FRAME_S do
            core.RunFrame()
            acc = acc - GB_FRAME_S
        end
        play.acc = acc
        if sound.enabled then SoundUpdate(core) end
    end,
}

------------------------------------------------------------------------------
-- Battery saves: cartridge RAM persisted in SavedVariables (ForeverGBPlayerDB.saves),
-- keyed by ROM SHA-1 so renaming a converted ROM keeps its save. WoW writes
-- SavedVariables to disk on logout and /reload; we copy the RAM in on PLAYER_LOGOUT,
-- /fgb stop and when switching ROMs.
------------------------------------------------------------------------------
local function SaveDB()
    ForeverGBPlayerDB = ForeverGBPlayerDB or {}
    ForeverGBPlayerDB.saves = ForeverGBPlayerDB.saves or {}
    return ForeverGBPlayerDB.saves
end

local function FlushSave(core)
    core = core or play.core
    if not (core and core.hasBattery and core.IsSaveDirty()) then return false end
    SaveDB()[core.rom.sha1] = {
        name = core.rom.name, title = core.rom.title, data = core.GetSaveRAM(), time = time(),
    }
    core.ClearSaveDirty()
    return true
end

local function LoadSave(core)
    if not core.hasBattery then return end
    local s = SaveDB()[core.rom.sha1]
    if s and core.LoadSaveRAM(s.data) then
        Print("loaded battery save for %s (from %s)", core.rom.name, date("%Y-%m-%d %H:%M", s.time or 0))
    elseif s then
        Print("battery save for %s is unreadable - starting fresh (old save kept until overwritten)", core.rom.name)
    else
        Print("%s has battery-backed RAM - progress is saved on /reload, logout or /fgb stop", core.rom.name)
    end
end

local function ClearFB(shade)
    for i = 1, NPIX do fb[i] = shade end
end

-- Nintendo logo at 0x104: 48 bytes, 48x8 px 1bpp. Bytes come in pairs forming
-- 4x4 blocks (each nibble = one 4px row); 12 blocks across, top half then bottom.
-- Drawn at 2x, as the boot ROM does.
patterns.logo = {
    reset = function()
        ClearFB(0)
        local rom = view.rom
        if not rom then return end
        local ox, oy = (W - 96) / 2, 56
        for half = 0, 1 do
            for blk = 0, 11 do
                for k = 0, 1 do
                    local b = RomByte(rom, 0x104 + half * 24 + blk * 2 + k)
                    for nib = 0, 1 do
                        local bits = (nib == 0) and floor(b / 16) or (b % 16)
                        local ly = half * 4 + k * 2 + nib
                        for bit = 0, 3 do
                            if floor(bits / 2 ^ (3 - bit)) % 2 == 1 then
                                local lx = blk * 4 + bit
                                for sy = 0, 1 do
                                    local row = (oy + ly * 2 + sy) * W + ox + lx * 2 + 1
                                    fb[row] = 3
                                    fb[row + 1] = 3
                                end
                            end
                        end
                    end
                end
            end
        end
    end,
    step = function() end,
}

-- Raw ROM bytes decoded as 2bpp Game Boy tiles (16 bytes per 8x8 tile, two
-- bitplanes per row), 20x18 tiles = one full screen = 5,760 bytes from view.offset.
patterns.tiles = {
    reset = function()
        ClearFB(0)
        local rom = view.rom
        if not rom then return end
        for t = 0, 20 * 18 - 1 do
            local base = view.offset + t * 16
            if base + 15 >= rom.size then break end
            local tx, ty = (t % 20) * 8, floor(t / 20) * 8
            for r = 0, 7 do
                local lo, hi = RomByte(rom, base + r * 2), RomByte(rom, base + r * 2 + 1)
                local row = (ty + r) * W + tx + 1
                for x = 0, 7 do
                    local m = 2 ^ (7 - x)
                    fb[row + x] = (floor(hi / m) % 2) * 2 + floor(lo / m) % 2
                end
            end
        end
    end,
    step = function() end,
}

------------------------------------------------------------------------------
-- Renderers
------------------------------------------------------------------------------
local function CreateAtlasRenderer(parent)
    local holder = CreateFrame("Frame", nil, parent)
    holder:SetAllPoints(parent)
    holder:Hide()
    local segs, prev = {}, {}
    for s = 1, NSEG do
        local idx = s - 1
        local tex = holder:CreateTexture(nil, "ARTWORK")
        tex:SetTexture(ATLAS_PATH, "CLAMP", "CLAMP", "NEAREST")
        tex:SetSize(SEG_W, 1)
        tex:SetPoint("TOPLEFT", holder, "TOPLEFT",
            (idx % SEGS_PER_ROW) * SEG_W, -floor(idx / SEGS_PER_ROW))
        segs[s] = tex
    end
    local SetTexCoord = segs[1].SetTexCoord -- skip the method lookup per call

    local r = { name = "atlas", frame = holder, textures = NSEG, segs = segs }
    function r.Invalidate()
        for s = 1, NSEG do prev[s] = -1 end
    end
    function r.Render(fb, force) -- fb: 1-based 160x144 array of shades 0..3
        local calls, i = 0, 1
        for s = 1, NSEG do
            local code = fb[i] * 64 + fb[i + 1] * 16 + fb[i + 2] * 4 + fb[i + 3]
            i = i + 4
            if force or prev[s] ~= code then
                prev[s] = code
                SetTexCoord(segs[s], TC_L[code], TC_R[code], TC_T[code], TC_B[code])
                calls = calls + 1
            end
        end
        return calls
    end
    r.Invalidate()
    return r
end

-- RGB555 -> 0..1 channel lookups for Game Boy Color output (built on first use).
local C15_R, C15_G, C15_B
local function GetC15()
    if not C15_R then
        C15_R, C15_G, C15_B = {}, {}, {}
        for v = 0, 32767 do
            local r = v % 32
            local g = ((v - r) / 32) % 32
            local b = (v - v % 1024) / 1024
            C15_R[v], C15_G[v], C15_B[v] = r / 31, g / 31, b / 31
        end
    end
    return C15_R, C15_G, C15_B
end

local function CreatePixelRenderer(parent)
    local holder = CreateFrame("Frame", nil, parent)
    holder:SetAllPoints(parent)
    holder:Hide()
    local px, prev = {}, {}
    for i = 1, NPIX do
        local idx = i - 1
        local tex = holder:CreateTexture(nil, "ARTWORK")
        tex:SetSize(1, 1)
        tex:SetPoint("TOPLEFT", holder, "TOPLEFT", idx % W, -floor(idx / W))
        px[i] = tex
    end
    local SetColorTexture = px[1].SetColorTexture

    local r = { name = "pixel", frame = holder, textures = NPIX, px = px }
    function r.Invalidate()
        for i = 1, NPIX do prev[i] = -1 end
    end
    -- fb: 1-based 160x144 array of shades 0..3, or RGB555 colours when color is true.
    function r.Render(fb, force, color)
        local R, G, B = PAL_R, PAL_G, PAL_B
        if color then R, G, B = GetC15() end
        local calls = 0
        for i = 1, NPIX do
            local v = fb[i]
            if force or prev[i] ~= v then
                prev[i] = v
                SetColorTexture(px[i], R[v], G[v], B[v])
                calls = calls + 1
            end
        end
        return calls
    end
    r.Invalidate()
    return r
end

local RENDERER_CTORS = { atlas = CreateAtlasRenderer, pixel = CreatePixelRenderer }

------------------------------------------------------------------------------
-- UI
------------------------------------------------------------------------------
local state = { renderer = "atlas", pattern = "sprites", force = false, scale = 3, t = 0 }
local root, screen, statsText, driver
local renderers, creation = {}, {}
local active -- current renderer, or nil for the "none" baseline

local function ApplyScale()
    -- Make one screen unit = `scale` physical pixels so the image is crisp.
    local physH = GetPhysicalScreenSize and select(2, GetPhysicalScreenSize())
    local s
    if physH and physH > 0 then
        s = (state.scale * 768 / physH) / root:GetEffectiveScale()
    else
        s = state.scale
    end
    screen:SetScale(s)
    screen:ClearAllPoints()
    screen:SetPoint("TOPLEFT", root, "TOPLEFT", 8 / s, -26 / s)
    root:SetSize(W * s + 16, H * s + 26 + 34)
end

------------------------------------------------------------------------------
-- Keyboard input: only while playing AND focused (click the screen; Esc releases).
--
-- Uses temporary override key bindings (the standard way addons take over keys): while
-- focused, each mapped key is bound to a hidden button via SetOverrideBindingClick, and
-- that button reports press AND release. Unmapped keys keep their normal bindings.
-- ClearOverrideBindings restores everything; nothing is written to the user's bindings.
-- Override bindings are protected in combat, so focus is dropped when combat starts.
------------------------------------------------------------------------------
local KEYMAP = {
    UP = "up", W = "up", DOWN = "down", S = "down",
    LEFT = "left", A = "left", RIGHT = "right", D = "right",
    ["]"] = "a", ["["] = "b",
    ENTER = "start", BACKSPACE = "select", RSHIFT = "select",
    ESCAPE = "release",
}
local KEY_HELP = "arrows/WASD = d-pad, ] = A, [ = B, Enter = Start, Backspace = Select, Esc = release keyboard"
local titleText
local inputFocused = false
local keyDebug = false
local pendingClear = false
local SetInputFocus -- forward declaration (the release button calls it)

local inputButtons = {}
local function InputButtonName(btn)
    local name = "ForeverGBPlayerInput_" .. btn
    if not inputButtons[btn] then
        local b = CreateFrame("Button", name, UIParent)
        b:RegisterForClicks("AnyDown", "AnyUp")
        b:SetScript("OnClick", function(_, _, down)
            down = down and true or false
            if keyDebug then Print("key -> %s %s", btn, down and "down" or "up") end
            if btn == "release" then
                if down then SetInputFocus(false) end
            elseif play.core then
                play.core.SetButton(btn, down)
            end
        end)
        inputButtons[btn] = b
    end
    return name
end

local function UpdateTitle()
    if not titleText then return end
    if state.pattern == "play" and play.core then
        titleText:SetText(inputFocused and "|cff88ff88Keyboard: ON|r  (Esc to release)"
            or "|cffffcc00Click the screen to play|r")
    else
        titleText:SetText("Forever GB Player  (drag to move, /fgb help)")
    end
end

SetInputFocus = function(on)
    on = on and root ~= nil and state.pattern == "play" and play.core ~= nil
    if on and InCombatLockdown() then
        Print("can't take the keyboard in combat")
        on = false
    end
    if inputFocused ~= on then
        if on then
            for key, btn in pairs(KEYMAP) do
                SetOverrideBindingClick(root, true, key, InputButtonName(btn))
            end
        elseif InCombatLockdown() then
            pendingClear = true -- protected now; cleared on PLAYER_REGEN_ENABLED
        else
            ClearOverrideBindings(root)
        end
        inputFocused = on
        -- Key-ups are lost once the bindings go, so never leave a button held.
        if not on and play.core then play.core.ReleaseAllButtons() end
        if keyDebug then Print("keyboard %s", on and "captured" or "released") end
    end
    UpdateTitle()
end

local combatWatcher = CreateFrame("Frame")
combatWatcher:RegisterEvent("PLAYER_REGEN_DISABLED")
combatWatcher:RegisterEvent("PLAYER_REGEN_ENABLED")
combatWatcher:RegisterEvent("PLAYER_LOGOUT") -- also fires on /reload
combatWatcher:SetScript("OnEvent", function(_, event)
    if event == "PLAYER_LOGOUT" then
        FlushSave()
    elseif event == "PLAYER_REGEN_DISABLED" then
        -- Fires just before lockdown begins, so the bindings can still be cleared here.
        if inputFocused then
            SetInputFocus(false)
            Print("keyboard released - you entered combat")
        end
    elseif pendingClear and root then
        pendingClear = false
        ClearOverrideBindings(root)
    end
end)

local function BuildUI()
    root = CreateFrame("Frame", "ForeverGBPlayerFrame", UIParent)
    root:SetPoint("CENTER")
    root:SetFrameStrata("HIGH")
    root:SetClampedToScreen(true)
    root:SetMovable(true)
    root:EnableMouse(true)
    root:RegisterForDrag("LeftButton")
    root:SetScript("OnDragStart", root.StartMoving)
    root:SetScript("OnDragStop", root.StopMovingOrSizing)
    root:SetScript("OnMouseDown", function() SetInputFocus(true) end)
    root:Hide()

    local bg = root:CreateTexture(nil, "BACKGROUND")
    bg:SetAllPoints(root)
    bg:SetColorTexture(0, 0, 0, 0.85)

    local title = root:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    title:SetPoint("TOPLEFT", root, "TOPLEFT", 8, -7)
    title:SetText("Forever GB Player  (drag to move, /fgb help)")
    titleText = title

    local close = CreateFrame("Button", nil, root, "UIPanelCloseButton")
    close:SetPoint("TOPRIGHT", root, "TOPRIGHT", 2, 2)
    close:SetScript("OnClick", function() SlashCmdList.FOREVERGB("stop") end)

    screen = CreateFrame("Frame", nil, root)
    screen:SetSize(W, H)

    statsText = root:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    statsText:SetPoint("BOTTOMLEFT", root, "BOTTOMLEFT", 8, 6)
    statsText:SetJustifyH("LEFT")
    statsText:SetText("")

    driver = CreateFrame("Frame")
    ApplyScale()
end

local function GetRenderer(name)
    if not renderers[name] then
        collectgarbage("collect")
        local kb0, t0 = collectgarbage("count"), debugprofilestop()
        renderers[name] = RENDERER_CTORS[name](screen)
        local info = { ms = debugprofilestop() - t0, kb = collectgarbage("count") - kb0 }
        creation[name] = info
        Print("created '%s' renderer: %d textures in %.0f ms, ~%.0f KB Lua memory",
            name, renderers[name].textures, info.ms, info.kb)
    end
    return renderers[name]
end

-- Accumulator for the on-screen rolling stats (every 60 frames).
local acc = { n = 0, gen = 0, render = 0, rmax = 0, calls = 0, fps = 0 }
local function ResetAcc(a)
    a.n, a.gen, a.render, a.rmax, a.calls, a.fps = 0, 0, 0, 0, 0, 0
end
local lastReport

local function Activate(rendererName, patternName, force)
    state.renderer, state.pattern, state.force = rendererName, patternName, force
    for _, r in pairs(renderers) do r.frame:Hide() end
    if rendererName == "none" then
        active = nil
    else
        active = GetRenderer(rendererName)
        active.Invalidate()
        active.frame:Show()
        patterns[patternName].reset()
    end
    state.t = 0
    ResetAcc(acc)
    if patternName ~= "play" then SetInputFocus(false) end
end

------------------------------------------------------------------------------
-- Benchmark sequence
------------------------------------------------------------------------------
local WARMUP, MEASURE = 30, 240
local BENCH_CASES = {
    { "none", "static", false },
    { "atlas", "static", false },
    { "atlas", "sprites", false },
    { "atlas", "scroll", false },
    { "pixel", "static", false },
    { "pixel", "sprites", false },
    { "pixel", "scroll", false },
    { "pixel", "scroll", true }, -- scroll only changes 1/3 of pixels; force = all 23,040
}
local bench -- nil when not benchmarking

local function FinishBench()
    Print("benchmark results (%d measured frames each):", MEASURE)
    print("  renderer/pattern   gen ms   render ms avg/max   API calls/frame   fps")
    for _, res in ipairs(bench.results) do
        print(format("  %-17s %7.2f   %8.2f / %6.2f   %15.0f   %5.1f",
            res.label, res.gen, res.render, res.rmax, res.calls, res.fps))
    end
    for name, info in pairs(creation) do
        print(format("  create %-6s: %.0f ms, ~%.0f KB", name, info.ms, info.kb))
    end
    local saved = bench.saved
    bench = nil
    Activate(saved.renderer, saved.pattern, saved.force)
end

local function StartBenchCase()
    local c = BENCH_CASES[bench.i]
    Activate(c[1], c[2], c[3])
    bench.frame = 0
    ResetAcc(bench.acc)
end

local function BenchTick(gen, render, calls, fps)
    bench.frame = bench.frame + 1
    if bench.frame <= WARMUP then return end
    local a = bench.acc
    a.n, a.gen, a.render, a.calls, a.fps = a.n + 1, a.gen + gen, a.render + render, a.calls + calls, a.fps + fps
    if render > a.rmax then a.rmax = render end
    if a.n >= MEASURE then
        local c = BENCH_CASES[bench.i]
        bench.results[#bench.results + 1] = {
            label = c[1] .. "/" .. c[2] .. (c[3] and "+force" or ""),
            gen = a.gen / a.n, render = a.render / a.n, rmax = a.rmax,
            calls = a.calls / a.n, fps = a.fps / a.n,
        }
        bench.i = bench.i + 1
        if bench.i > #BENCH_CASES then FinishBench() else StartBenchCase() end
    end
end

------------------------------------------------------------------------------
-- Frame loop
------------------------------------------------------------------------------
local function OnUpdate(_, elapsed)
    local gen, render, calls = 0, 0, 0
    if active then
        local t0 = debugprofilestop()
        patterns[state.pattern].step(state.t, elapsed)
        local t1 = debugprofilestop()
        local core = state.pattern == "play" and play.core
        calls = active.Render(core and core.fb or fb, state.force, core and core.cgb)
        local t2 = debugprofilestop()
        gen, render = t1 - t0, t2 - t1
        state.t = state.t + 1
    end
    local fps = GetFramerate()

    if bench then BenchTick(gen, render, calls, fps) end

    acc.n, acc.gen, acc.render, acc.calls, acc.fps = acc.n + 1, acc.gen + gen, acc.render + render, acc.calls + calls, acc.fps + fps
    if render > acc.rmax then acc.rmax = render end
    if acc.n >= 60 then
        local n = acc.n
        lastReport = format("%s/%s%s | " .. (state.pattern == "play" and "emu" or "gen") .. " %.2fms | render %.2fms (max %.2f) | calls %.0f | fps %.1f",
            active and active.name or "none", state.pattern, state.force and " [force]" or "",
            acc.gen / n, acc.render / n, acc.rmax, acc.calls / n, acc.fps / n)
        statsText:SetText((bench and format("BENCH %d/%d  ", bench.i, #BENCH_CASES) or "") .. lastReport)
        ResetAcc(acc)
    end
end

local function Start()
    if not root then BuildUI() end
    root:Show()
    Activate(state.renderer, state.pattern, state.force)
    driver:SetScript("OnUpdate", OnUpdate)
end

local function Stop()
    SoundStopAll()
    if FlushSave() then Print("saved %s", play.core.rom.name) end
    SetInputFocus(false)
    bench = nil
    if driver then driver:SetScript("OnUpdate", nil) end
    if root then root:Hide() end
end

------------------------------------------------------------------------------
-- CPU runner: /fgb cpu [rom] - runs GBCore one Game Boy frame per WoW frame,
-- echoes serial output (Blargg test results) to chat and reports CPU cost.
------------------------------------------------------------------------------
local cpuRun, cpuFrame
local GB_FRAME_MS = 70224 / 4194304 * 1000 -- 16.74 ms of Game Boy time per frame

local function StopCpu(reason)
    if not cpuRun then return end
    local r = cpuRun
    cpuRun = nil
    cpuFrame:SetScript("OnUpdate", nil)
    local avg = r.totalMs / math.max(r.frames, 1)
    Print("cpu %s: %s after %.1fs emulated / %.1fs real - avg %.2f ms per GB frame (max speed ~%.0f%%)",
        r.core.rom.name, reason, r.frames * GB_FRAME_MS / 1000, r.real, avg, GB_FRAME_MS / avg * 100)
end

local function CpuOnUpdate(_, elapsed)
    local r = cpuRun
    local t0 = debugprofilestop()
    r.core.RunFrame()
    local ms = debugprofilestop() - t0
    r.frames, r.totalMs, r.real = r.frames + 1, r.totalMs + ms, r.real + elapsed
    r.winMs, r.winN = r.winMs + ms, r.winN + 1
    if ms > r.maxMs then r.maxMs = ms end

    local s = r.core.GetSerial()
    if #s > r.serialLen then
        r.line = r.line .. s:sub(r.serialLen + 1)
        r.serialLen = #s
        local nl = r.line:find("\n", 1, true)
        while nl do
            local line = r.line:sub(1, nl - 1)
            r.line = r.line:sub(nl + 1)
            if line:match("%S") then Print("serial: %s", line) end
            nl = r.line:find("\n", 1, true)
        end
        if s:find("Passed", 1, true) then
            if r.line:match("%S") then Print("serial: %s", r.line) end
            return StopCpu("PASSED")
        elseif s:find("Failed", 1, true) then
            if r.line:match("%S") then Print("serial: %s", r.line) end
            return StopCpu("FAILED")
        end
    end
    if r.core.IsLocked() then return StopCpu("CPU locked (illegal opcode)") end

    if r.winN >= 300 then -- ~5 s
        local avg = r.winMs / r.winN
        Print("cpu: %.2f ms per GB frame (max %.2f), max speed ~%.0f%%, game fps %.0f",
            avg, r.maxMs, GB_FRAME_MS / avg * 100, GetFramerate())
        r.winMs, r.winN, r.maxMs = 0, 0, 0
    end
end

local function StartCpu(romName)
    if not GBCore then return Print("GBCore not loaded - check core\\Core.lua is in the .toc") end
    local rom = FindRom(romName)
    if not rom then
        return Print(romName and ("no ROM named '" .. romName .. "' - see /fgb roms")
            or NO_ROMS)
    end
    StopCpu("restarted")
    local t0 = debugprofilestop()
    local core, err = GBCore.New(rom)
    if not core then return Print("cannot run %s: %s", rom.name, err) end
    Print("cpu: booted %s (%s) in %.0f ms - running 1 GB frame per WoW frame; /fgb stop to end",
        rom.name, core.mbc, debugprofilestop() - t0)
    cpuFrame = cpuFrame or CreateFrame("Frame")
    cpuRun = { core = core, frames = 0, totalMs = 0, real = 0, winMs = 0, winN = 0, maxMs = 0,
               serialLen = 0, line = "" }
    cpuFrame:SetScript("OnUpdate", CpuOnUpdate)
end

------------------------------------------------------------------------------
-- Slash command
------------------------------------------------------------------------------
local HELP = {
    "/fgb            - show/hide and start/stop",
    "/fgb atlas|pixel  - choose renderer",
    "/fgb static|sprites|scroll - choose test pattern",
    "/fgb force      - toggle redrawing every segment every frame (no dirty check)",
    "/fgb scale N    - N physical pixels per GB pixel (default 3)",
    "/fgb bench      - run every renderer/pattern combo and print a table",
    "/fgb report     - print the latest rolling stats",
    "/fgb roms       - list converted ROMs and verify their checksums",
    "/fgb logo [rom] - draw the ROM header's Nintendo logo",
    "/fgb tiles [rom] [hexoffset] - view ROM bytes as 2bpp tiles (one screen = 0x1680 bytes)",
    "/fgb cpu [rom]  - run the CPU core on a ROM; prints serial output (test results) + cost",
    "/fgb play [rom] - play a ROM: click the screen for keyboard, Esc releases it",
    "    keys: arrows/WASD d-pad, ] = A, [ = B, Enter = Start, Backspace = Select",
    "/fgb keys       - toggle key debug (prints every Game Boy button press/release)",
    "/fgb sound [on|off|fade ms|mode envelope|steps|channels 1234] - sound; prints sounds started/second",
    "/fgb stop       - stop and hide",
}

-- Internals exposed for debugging and the offline test harness (not part of the API).
ForeverGBPlayer.fb, ForeverGBPlayer.W, ForeverGBPlayer.H = fb, W, H
ForeverGBPlayer.RomByte, ForeverGBPlayer.VerifyRom = RomByte, VerifyRom
ForeverGBPlayer.play, ForeverGBPlayer.renderers = play, renderers

SLASH_FOREVERGB1 = "/fgb"
SLASH_FOREVERGB2 = "/gbspike" -- the old name, kept as an alias
SlashCmdList.FOREVERGB = function(msg)
    local cmd, arg = (msg or ""):match("^%s*(%S*)%s*(.-)%s*$")
    cmd = cmd:lower()
    local running = root and root:IsShown()

    if cmd == "" then
        if running then Stop() else Start() end
    elseif cmd == "help" then
        for _, line in ipairs(HELP) do print(line) end
    elseif cmd == "stop" then
        StopCpu("stopped")
        Stop()
    elseif cmd == "cpu" then
        StartCpu(arg ~= "" and arg or nil)
    elseif cmd == "sound" then
        local opt, val = arg:match("^(%S*)%s*(%S*)$")
        if opt == "on" or opt == "off" then
            sound.enabled = opt == "on"
            if not sound.enabled then SoundStopAll() end
        elseif opt == "fade" and tonumber(val) then
            sound.fade = math.max(0, math.min(200, floor(tonumber(val))))
        elseif opt == "mode" and (val == "envelope" or val == "steps") then
            sound.mode = val
            SoundStopAll()
        elseif opt == "channels" and val:match("^[1-4]*$") then
            for c = 1, 4 do sound.use[c] = val:find(tostring(c), 1, true) ~= nil end
            SoundStopAll()
        end
        local chs = ""
        for c = 1, 4 do if sound.use[c] then chs = chs .. c end end
        local secs = GetTime() - sound.since
        Print("sound %s, mode %s, channels %s, stop fade %d ms - %d sounds started, %.1f/s%s",
            sound.enabled and "ON" or "OFF", sound.mode, chs ~= "" and chs or "none", sound.fade,
            sound.plays, secs > 0 and sound.plays / secs or 0,
            GBSoundWaves and "" or " (no sound\\waves.lua: bass uses the triangle fallback)")
        sound.plays, sound.since = 0, GetTime()
    elseif cmd == "keys" then
        keyDebug = not keyDebug
        Print("key debug %s - keyboard is %s, playing: %s", keyDebug and "ON" or "OFF",
            inputFocused and "captured" or "NOT captured (click the screen)",
            play.core and play.core.rom.name or "nothing")
    elseif cmd == "play" then
        if not GBCore then return Print("GBCore not loaded - check core\\Core.lua is in the .toc") end
        local rom = FindRom(arg ~= "" and arg or nil)
        if not rom then
            return Print(arg ~= "" and ("no ROM named '" .. arg .. "' - see /fgb roms")
                or NO_ROMS)
        end
        local core, err = GBCore.New(rom)
        if not core then return Print("cannot run %s: %s", rom.name, err) end
        StopCpu("switched to play")
        if FlushSave() then Print("saved %s", play.core.rom.name) end
        SetInputFocus(false) -- releases buttons on the previous core
        SoundStopAll()
        LoadSave(core)
        play.core, play.acc = core, 0
        state.pattern = "play"
        -- The atlas renderer only knows 4 shades; Game Boy Color output needs per-pixel colour.
        state.renderer = core.cgb and "pixel" or "atlas"
        if running then Activate(state.renderer, state.pattern, state.force) else Start() end
        SetInputFocus(true)
        Print("play: %s (%s, %s) - 'emu' in the stats line = CPU+PPU ms per WoW frame",
            rom.name, core.mbc, core.cgb and "Game Boy Color, pixel renderer" or "Game Boy, atlas renderer")
        Print("keys: %s", KEY_HELP)
    elseif cmd == "roms" then
        local names = RomNames()
        if #names == 0 then Print(NO_ROMS) end
        for _, name in ipairs(names) do
            local rom = romLibrary[name]
            local sizeOk, hdrOk, globalOk = VerifyRom(rom)
            local save = SaveDB()[rom.sha1]
            Print("%s: \"%s\" %d KB, %s, CGB %s - size %s, header checksum %s, global checksum %s%s [%s]",
                name, rom.title, rom.size / 1024, rom.cartName, rom.cgb,
                sizeOk and "OK" or "BAD", hdrOk and "OK" or "BAD", globalOk and "OK" or "BAD",
                save and (", save from " .. date("%Y-%m-%d %H:%M", save.time or 0)) or "", rom.source)
        end
    elseif cmd == "logo" or cmd == "tiles" then
        local romName, offset
        for word in arg:gmatch("%S+") do
            local hex = word:match("^0[xX](%x+)$") or word:match("^%$(%x+)$")
            if hex then offset = tonumber(hex, 16) else romName = word end
        end
        local rom = FindRom(romName)
        if not rom then
            Print(romName and ("no ROM named '" .. romName .. "' - see /fgb roms")
                or NO_ROMS)
            return
        end
        view.rom = rom
        view.offset = offset or (cmd == "tiles" and view.offset) or 0
        if view.offset >= rom.size then view.offset = 0 end
        state.pattern = cmd
        if running then Activate(state.renderer, state.pattern, state.force) else Start() end
        Print("%s: %s%s", cmd, rom.name, cmd == "tiles" and format(" @ 0x%04X", view.offset) or "")
    elseif RENDERER_CTORS[cmd] then
        if cmd == "atlas" and state.pattern == "play" and play.core and play.core.cgb then
            return Print("the atlas renderer is 4-shade only; Game Boy Color games use the pixel renderer")
        end
        state.renderer = cmd
        if running then Activate(state.renderer, state.pattern, state.force) else Start() end
    elseif patterns[cmd] then
        state.pattern = cmd
        if running then Activate(state.renderer, state.pattern, state.force) else Start() end
    elseif cmd == "force" then
        state.force = not state.force
        Print("force redraw %s", state.force and "ON" or "OFF")
    elseif cmd == "scale" then
        local n = tonumber(arg)
        if n and n >= 1 and n <= 8 then
            state.scale = floor(n)
            if root then ApplyScale() end
        else
            Print("usage: /fgb scale 1-8")
        end
    elseif cmd == "bench" then
        if not running then Start() end
        Print("benchmarking %d cases, ~%d frames each - stand still and don't touch the UI",
            #BENCH_CASES, WARMUP + MEASURE)
        bench = {
            i = 1, frame = 0, acc = {}, results = {},
            saved = { renderer = state.renderer, pattern = state.pattern, force = state.force },
        }
        StartBenchCase()
    elseif cmd == "report" then
        Print("%s", lastReport or "no stats yet")
    else
        Print("unknown command '%s' - try /fgb help", cmd)
    end
end
