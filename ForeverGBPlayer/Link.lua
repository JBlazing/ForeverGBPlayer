-- Link cable: two players' emulators swap serial bytes over addon whispers, using the same
-- channel as the FojjiCore multiplayer games (FojjiCore Games' Games.Duel on top of its
-- Comm queue). The challenge, the accept toast, "only guild and group members" and the
-- leave message all come from Duel; this file adds the byte exchange.
--
-- A real cable moves a byte in about 1 ms. A whisper takes a few hundred, so instead of
-- running in lockstep each emulator pauses while it waits for the other:
--   * A Game Boy that starts a transfer on its own clock ("master") stops until the other
--     side's byte comes back. Its game time doesn't move, so the game's timeouts never fire.
--   * A Game Boy waiting on the other's clock ("slave") keeps running, except during a burst
--     of bytes (one arrived in the last BURST seconds), when it pauses until the next one.
--   * A byte that arrives before the other game is waiting for it is held for HOLD seconds.
--     If the game still isn't waiting, the sender reads 0xFF, as with nothing plugged in.
-- So link features that swap a few hundred bytes (trades, turn-based battles) work, slowly.
-- Games that swap a byte every frame (action multiplayer) can't keep up.
--
-- Messages (Duel extra messages, after Duel's own "<sub>~<session id>~"):
--   B~seq~hh   I clocked transfer seq (counting up from 1 per session) and sent byte hh
--   Z~seq~hh   my byte for your transfer seq
--   H~title    the game I'm running now ("" = none)
-- Lost whispers: the master sends B again every RESEND seconds with the same seq, and the
-- other side answers a repeated seq with the reply it already gave.

local format = string.format

ForeverGBPlayer = ForeverGBPlayer or {}

local HOLD = 1.0      -- seconds an early byte waits for the game to start listening
local BURST = 2.0     -- seconds a listening Game Boy pauses after each byte, waiting for the next
local RESEND = 4.0    -- seconds before a master sends its byte again
local GIVE_UP = 30.0  -- seconds before a master gives up and reads 0xFF

------------------------------------------------------------------------------
-- The byte exchange, independent of WoW (tools/test_link.py drives two of these).
--   port = NewLinkPort({ send = function(sub, a, b) end, now = function() return seconds end,
--                        note = function(event, ...) end })   -- optional, for chat messages
--   port.Attach(core | nil)   the running emulator, or nil when none is running
--   port.Receive(sub, a, b)   a B or Z message from the other side
--   port.Tick()               call often (every WoW frame): resends and time-outs
--   port.Holding()            true while the emulator should not run this frame
------------------------------------------------------------------------------
function ForeverGBPlayer.NewLinkPort(io)
    local send, now = io.send, io.now
    local note = io.note or function() end
    local port = {}
    local core
    local outSeq = 0       -- our last master transfer
    local pending          -- { seq, byte, sent, first } while our transfer waits
    local inSeq, inReply = 0, nil -- the last transfer of theirs we answered, and our answer
    local held             -- { seq, byte, until } their byte, waiting for our game to listen
    local burstUntil = 0
    local stats = { out = 0, inn = 0, resent = 0, missed = 0 }
    port.stats = stats

    local function hex(b) return format("%02x", b) end

    local function reply(seq, byte)
        inSeq, inReply = seq, byte
        send("Z", seq, hex(byte))
    end

    -- Their clock moved a byte into our game; ours goes back to them.
    local function swap(seq, byte)
        local state, mine = core.SerialState()
        reply(seq, mine)
        core.SerialDone(byte)
        if state == "master" then
            -- Both sides started a transfer at once: each one gets the other's byte, and
            -- their answer to ours (when it comes) is ignored.
            pending = nil
        end
        burstUntil = now() + BURST
        stats.inn = stats.inn + 1
    end

    local hooks = {}
    function hooks.Master(byte)
        outSeq = outSeq + 1
        local t = now()
        pending = { seq = outSeq, byte = byte, sent = t, first = t }
        stats.out = stats.out + 1
        send("B", outSeq, hex(byte))
    end
    function hooks.Slave()
        if held then
            local h = held
            held = nil
            swap(h.seq, h.byte)
        end
    end

    function port.Attach(c)
        if c == core then return end
        if core then core.SetSerialPort(nil) end
        core, pending = c, nil
        if held then
            reply(held.seq, 0xFF)
            held = nil
        end
        burstUntil = 0
        if core then core.SetSerialPort(hooks) end
    end

    function port.Receive(sub, a, b)
        local seq, byte = tonumber(a), tonumber(b or "", 16)
        if not seq or not byte or byte < 0 or byte > 255 or seq % 1 ~= 0 then return end
        if sub == "Z" then
            if pending and pending.seq == seq and core then
                pending = nil
                core.SerialDone(byte)
            end
            return
        end
        if sub ~= "B" then return end
        if seq <= inSeq then
            if seq == inSeq and inReply then send("Z", seq, hex(inReply)) end -- our answer was lost
            return
        end
        if held then
            if held.seq == seq then return end -- a resend of the byte we're already holding
            reply(held.seq, 0xFF)           -- they moved on without it
            held = nil
        end
        if not core then
            reply(seq, 0xFF) -- no game running: nothing on the end of the cable
            stats.missed = stats.missed + 1
            return
        end
        if core.SerialState() then
            swap(seq, byte)
        else
            held = { seq = seq, byte = byte, ["until"] = now() + HOLD }
        end
    end

    function port.Tick()
        local t = now()
        if held and t >= held["until"] then
            reply(held.seq, 0xFF)
            held = nil
            stats.missed = stats.missed + 1
        end
        if pending then
            if t - pending.first >= GIVE_UP then
                pending = nil
                if core then core.SerialDone(0xFF) end
                note("timeout")
            elseif t - pending.sent >= RESEND then
                pending.sent = t
                stats.resent = stats.resent + 1
                send("B", pending.seq, hex(pending.byte))
            end
        end
    end

    function port.Holding()
        if not core then return false end
        local state = core.SerialState()
        if state == "master" then return true end
        return state == "slave" and now() < burstUntil
    end

    function port.Waiting() return pending ~= nil end

    return port
end

------------------------------------------------------------------------------
-- The FojjiCore side: challenge someone, then the session carries the port's messages.
------------------------------------------------------------------------------
local PREFIX = "|cff88c070ForeverGB|r: "
local function Print(...) print(PREFIX .. format(...)) end

local Link = { available = false }
ForeverGBPlayer.Link = Link

local Addon = FojjiCoreNS
local Games = Addon and Addon.Games
local NEED = "the link cable needs FojjiCore and FojjiCore Games (4.0.52 or newer) - both players need them"

local function playing() -- the emulator that is running right now, or nil
    local P = ForeverGBPlayer.play
    local running = ForeverGBPlayer.IsRunning and ForeverGBPlayer.IsRunning()
    return running and P and P.core or nil
end
local function title(core)
    core = core or playing()
    return core and (core.rom.title ~= "" and core.rom.title or core.rom.name) or ""
end
local function refresh()
    if ForeverGBPlayer.UpdateTitle then ForeverGBPlayer.UpdateTitle() end
end

if not (Games and Games.Duel and Games.Duel.Make and Games.Name) then
    function Link.Command() Print(NEED) end
    function Link.CoreChanged() end
    function Link.Holding() return false end
    function Link.Status() return nil end
    return
end
Link.available = true

local D, port, ticker
local peerGame

local function short(n) return n and Games.Name(n) or "?" end
local function linked()
    local s = D and D:Session()
    return s and not s.over and s or nil
end

local function stopTicker()
    if ticker then ticker:SetScript("OnUpdate", nil) end
end
local function startTicker()
    ticker = ticker or CreateFrame("Frame")
    ticker:SetScript("OnUpdate", function() if port then port.Tick() end end)
end

local function announce()
    if linked() then D:Send("H", (title():gsub("[~|]", ""))) end
end

local function connect(s)
    port = ForeverGBPlayer.NewLinkPort({
        send = function(sub, a, b) if linked() == s then D:Send(sub, a, b) end end,
        now = GetTime,
        note = function(event)
            if event == "timeout" then
                Print("%s didn't answer for 30 seconds - that transfer read 0xFF. /fgb link off to unplug.",
                    short(s.foe))
            end
        end,
    })
    port.Attach(playing())
    peerGame = nil
    startTicker()
    announce()
    refresh()
end

local function disconnect()
    if port then port.Attach(nil) end
    port, peerGame = nil, nil
    stopTicker()
    refresh()
end

D = Games.Duel.Make("GBL", "Game Boy Link", {
    options = function() return title() end,
    describe = function(opts) return opts ~= "" and opts or nil end,
    onInvite = function(_, state, name)
        if state == "sent" then
            Print("asked %s to link up. They need ForeverGBPlayer and FojjiCore Games.", short(name))
        end
    end,
    onStart = function(s)
        if port then return end
        connect(s)
        Print("link cable connected to %s. Start the link feature in both games; transfers are slow (a few bytes a second).",
            short(s.foe))
    end,
    onEnd = function(s, why, mine)
        disconnect()
        if not mine then Print("%s unplugged the link cable.", short(s.foe)) end
    end,
    onMessage = function(s, sub, rest)
        if not port then return end
        if sub == "H" then
            local was = peerGame
            peerGame = rest
            local mine = title()
            if rest == "" then
                if was and was ~= "" then Print("%s stopped their game.", short(s.foe)) end
            elseif rest ~= was then
                Print("%s is playing %s%s", short(s.foe), rest,
                    (mine ~= "" and mine ~= rest) and (" - you're playing " .. mine) or ".")
            end
            refresh()
        elseif sub == "B" or sub == "Z" then
            local a, b = rest:match("^(%d+)~(%x%x)$")
            if a then port.Receive(sub, a, b) end
        end
    end,
})
Link.Duel = D

-- The emulator started, switched game or stopped.
function Link.CoreChanged()
    if not port then return end
    port.Attach(playing())
    announce()
end

-- True while the emulator should skip running this frame (waiting on the other side).
function Link.Holding() return port ~= nil and port.Holding() end

-- Short text for the window's title bar, or nil when not linked.
function Link.Status()
    local s = linked()
    if not s then return nil end
    if port and port.Waiting() then return "|cff66ccffLink: waiting for " .. short(s.foe) .. "|r" end
    return "|cff66ccffLinked: " .. short(s.foe) .. "|r"
end

function Link.Command(arg)
    local word = (arg or ""):match("^(%S*)") or ""
    local lw = word:lower()
    if lw == "off" or lw == "unplug" or lw == "stop" then
        local s = linked()
        if D:Cancel() and not s then return Print("link request cancelled.") end
        if not D:Leave() then return Print("no link cable plugged in.") end
        Print("link cable unplugged.")
        return
    end
    if word == "" then
        local s = linked()
        if not s then
            if D.invite then return Print("waiting for %s to accept the link.", short(D.invite.to)) end
            return Print("not linked. /fgb link <name> asks a guild or group member to link up.")
        end
        local st = port and port.stats or {}
        return Print("linked with %s%s - bytes sent %d, received %d, resent %d, unanswered %d",
            short(s.foe), peerGame and peerGame ~= "" and (" (playing " .. peerGame .. ")") or "",
            st.out or 0, st.inn or 0, st.resent or 0, st.missed or 0)
    end
    if linked() then return Print("already linked with %s - /fgb link off first.", short(linked().foe)) end
    if D:Session() then D:Leave() end
    D:Challenge(word, title())
end

-- Let the other player know when we log out or /reload (the session doesn't survive one).
local watcher = CreateFrame("Frame")
watcher:RegisterEvent("PLAYER_LOGOUT")
watcher:SetScript("OnEvent", function()
    if D:Session() then D:Leave() end
end)
