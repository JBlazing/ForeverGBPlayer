# Forever GB Player

**Play Game Boy and Game Boy Color games in a window inside World of Warcraft.**

Waiting for a queue, a raid to form or a flight to land? Open a little handheld screen and play
your own Game Boy games without leaving the game. It plays in colour, has sound, and keeps your
saves between sessions.

## Features

- **Game Boy and Game Boy Color.** Colour games show in colour, and original Game Boy games keep the classic green screen.
- **Your saves are kept.** Games that save on the cartridge, like most RPGs, remember your progress
  after `/reload`, logging out, or closing the game.
- **Sound.** Music and sound effects are played back as closely as World of Warcraft allows. You
  can turn them off.
- **Plays at the real speed**, even on a high frame rate monitor.
- **Keyboard controls** that let go of your keys whenever you need them, and automatically when
  you enter combat.
- **A window you can move and resize.**
- **Each game is its own small addon**, so you can switch games on and off in the AddOns list.

**No games are included.** Only use ROMs you legally own: backups you made yourself from your own
cartridges (see *Where do I get games?* below).

## Getting started

It takes about two minutes. The first part only needs doing once per game.

### 1. Install Forever GB Player

Install it with the CurseForge app like any other addon.

### 2. Turn your game into an addon

World of Warcraft can't open game files directly, so each game is converted into a small addon first.
The **ROM Converter** does this in your web browser. Your game file stays on your computer and
is never uploaded anywhere.

1. Open the ROM Converter:
   **[jblazing.github.io/ForeverGBPlayer/tools/rom-converter.html](https://jblazing.github.io/ForeverGBPlayer/tools/rom-converter.html)**
2. Drag your game file (`.gb` or `.gbc`) onto the page. You can add several games at once. For each one it shows
   the game's name and the name you'll type to play it, for example `/fgb play tetris`.
3. Click **Download zip**.

*Offline?* The same converter comes with the addon. Open the **ForeverGBPlayer** folder inside your AddOns folder
(see step 3) and double-click **ROM Converter.html**.

### 3. Add it to the game

1. Open your **AddOns** folder. It's usually
   `C:\Program Files (x86)\World of Warcraft\<your game version>\Interface\AddOns`.
   For an easy way to find it, open the **Battle.net** app, click the gear icon next to **Play** and choose
   **Show in Explorer**. Then open your game version's folder, then `Interface`, then `AddOns`.
2. Double-click the zip you downloaded to open it. Inside is a folder named like
   **ForeverGBPlayer_Rom_tetris**.
3. **Drag that folder into your AddOns folder**, next to the ForeverGBPlayer folder.
   Don't use "Extract All", because it puts the folder one level too deep and the game won't find it.
4. **Restart World of Warcraft.** A `/reload` isn't enough for new addons.
5. On the character screen, click **AddOns** and check that both **Forever GB Player** and
   **GB ROM: (your game)** are ticked.

### 4. Play

Type `/fgb play tetris`, using the name the converter showed you. The screen appears and your keyboard controls
the game straight away.

## Controls

| Game Boy | Keyboard |
| --- | --- |
| D-pad | Arrow keys or W A S D |
| A | `]` |
| B | `[` |
| Start | Enter |
| Select | Backspace |
| **Give the keyboard back to WoW** | **Esc** |
| Take the keyboard again | Click the game screen |

While the game has the keyboard, those keys control the game, not your character. Every other key works as normal.
Press **Esc** whenever you need to move or type in chat. Entering combat gives your keys back automatically.

## Commands

| Command | What it does |
| --- | --- |
| `/fgb play tetris` | Start a game. Use the name the converter showed you. |
| `/fgb roms` | List the games you've added. |
| `/fgb stop` | Close the game. It also saves your progress. The window's **X** does the same. |
| `/fgb sound off` | Turn the sound off. Use `/fgb sound on` to turn it back on. |
| `/fgb scale 4` | Make the screen bigger or smaller, from 1 to 8. The default is 3. |
| `/fgb help` | Show every command. |

Drag the window by its title bar to move it.

## Where do I get games?

Forever GB Player doesn't come with any games.

**Only use ROMs you legally own.** That means backups you made yourself from Game Boy or Game Boy Color
cartridges you own. Don't download copies of commercial games from the internet. Please don't ask for,
share or link ROM files in the comments.

Free homebrew games are also fine, because their authors give them away to download. **Homebrew Hub**
(hh.gbdev.io) has hundreds of them.

Game Boy **Advance** games (`.gba`) are a different console and won't work.

## Good to know

- **Most games work.** These won't work fully:
  - A few early cartridge types won't start. The converter warns you.
  - Games with a built-in clock, such as Pokémon Gold, Silver and Crystal, may run, but their in-game clock won't work.
  - Link-cable multiplayer isn't supported.
  - A few games use unusual graphics tricks and may show small glitches.
- **Sound is an approximation.** WoW addons can only play recorded sounds, so the music is
  rebuilt from pre-recorded notes. It's recognisable, but not exactly like the original.
- **Performance.** The emulator uses a little of your computer's power while a game is running.
  If your frame rate drops, stop the game with `/fgb stop`.

## Troubleshooting

- **"No games added yet" or `/fgb roms` lists nothing.** Make sure the game's folder is directly inside AddOns and not
  inside another folder. Restart WoW, then check **GB ROM: (your game)** is ticked in the AddOns list.
- **"ForeverGBPlayer isn't loaded, so this ROM wasn't added."** Tick **Forever GB Player** in the AddOns list.
- **The keys don't move anything in the game.** Click the game screen to give it the keyboard. The title bar says
  **Keyboard: ON** when it's listening.
- **I can't move my character.** The game has the keyboard. Press **Esc**.
