# AbletonMCP - Ableton Live Model Context Protocol Integration
[![smithery badge](https://smithery.ai/badge/@ahujasid/ableton-mcp)](https://smithery.ai/server/@ahujasid/ableton-mcp)

AbletonMCP connects Ableton Live to Claude AI through the Model Context Protocol (MCP), allowing Claude to directly interact with and control Ableton Live. This integration enables prompt-assisted music production, track creation, and Live session manipulation.

### Join the Community

Give feedback, get inspired, and build on top of the MCP: [Discord](https://discord.gg/3ZrMyGKnaU). Made by [Siddharth](https://x.com/sidahuj)

## What's New in This Fork

This fork extends the upstream [`ahujasid/ableton-mcp`](https://github.com/ahujasid/ableton-mcp) with significantly more capability — the goal is **a full song in one prompt**. The original PR #84 changes (clip editing, mixer controls, scene firing, audio-track creation, undo) are still present and proposed upstream as [ahujasid/ableton-mcp#84](https://github.com/ahujasid/ableton-mcp/pull/84). On top of that, this fork now adds ~35 additional MCP tools across six tiers, plus a **33-personality rule-based style system** spanning jazz, fusion, R&B, hip-hop, and modern trap — from Coltrane and Bill Evans to Timbaland and Metro Boomin.

### Tier 1 — Composite "song scaffold" tools (one call, many steps)

- **`setup_session(tempo, time_signature, tracks=[…])`** — Bootstrap an entire session in a single round-trip: tempo, time signature, plus N tracks each with optional name, instrument, volume, and pan.
- **`create_clip_with_notes(track, clip, length, notes, name?)`** — Fuses `create_clip` + `add_notes_to_clip` + `set_clip_name`.
- **`create_track(type, name?, instrument_uri?, volume?, pan?, index?)`** — Single-call replacement for the create → name → load chain.
- **`duplicate_clip(src_track, src_slot, dst_track, dst_slot)`** — Cross-track clip duplication. (Upstream's `duplicate_clip_to` only works within a single track.)

### Tier 2 — Missing primitives

- **Time signature** — `set_time_signature(numerator, denominator)`
- **Clip editing** — `set_clip_loop`, `set_clip_length`
- **Mixer state** — `set_track_arm`, `set_track_mute`, `set_track_solo`, `set_master_volume`
- **Track lifecycle** — `delete_track`
- **Devices** — `set_device_parameter` (raw Live values, clamped to the parameter's min/max)
- **Scenes** — `create_scene`, `set_scene_name`, `set_scene_tempo`

### Tier 3 — Browser improvements

- **`search_browser(query, category?)`** — Walk Ableton's browser tree by name (case-insensitive). Returns up to 50 matches with URIs ready to load.
- **`load_instrument_by_name(track_index, name, category?)`** — Server-side composite: search + load in one call. No more URI hunting.
- **`get_track_devices(track_index)`** — List the devices on a track plus every device's parameters with their value, min, and max — needed before calling `set_device_parameter`.

### Tier 4 — Musical helpers (pure server-side, no remote round-trips for note math)

- **`add_chord_progression(track, clip, chords, rhythm?, octave?)`** — Write a progression like `["Cm","Fm","G7","Cm"]` straight into a clip. Supports triads, 7ths, sus, dim, aug, 9ths, 11ths, 13ths.
- **`add_scale_run(track, clip, scale, start_beat, end_beat, direction?)`** — Generate scalar runs in any of major / minor / harmonic_minor / dorian / phrygian / lydian / mixolydian / locrian / pentatonic / blues / chromatic.
- **`add_drum_pattern(track, clip, pattern, length, kit_map?)`** — Preset patterns: `four_on_floor`, `trap`, `breakbeat`, `boom_bap`. Defaults to GM drum mapping.
- **`quantize_clip(track, clip, grid?)`** — Snap notes to 1/4, 1/8, 1/16, or 1/32.
- **`transpose_clip(track, clip, semitones)`** — Shift every note by a fixed interval.

### Tier 4 Plus — Personality system (27 named players, 4 roles, BPM-aware)

A **personality** is a rule-based profile capturing the surface stylistic features of a real-world player: note density, swing, register, scale pool, chromatic usage, dynamics, articulation. Generators combine those rules with a chord progression to produce a coherent MIDI part that reads as "in the style of" that player. Not ML — deterministic, rule-based, fast, extensible (a new personality is one dict entry).

Each personality declares a `tempo_sweet_spot` and a comfortable `tempo_min`/`tempo_max` range. Generators auto-pull the current session tempo and **scale density / swing to compensate** when the song tempo is outside the personality's range — and emit a warning so you know.

#### Tools

- **`add_personality(track, clip, personality, chord_progression, bars_per_chord?, tempo?, octave_offset?, seed?)`** — Generate a part in the named personality's style and write it into an existing MIDI clip. Auto-dispatches by role (solo / comp / bass / drums). Tempo defaults to the live session tempo.
- **`add_blended_personality_solo(track, clip, personality_a, personality_b, ratio, chord_progression, ...)`** — Generate a solo from a profile that's interpolated between two personalities (e.g. 70% Coltrane + 30% Kenny G). Numeric fields are linearly blended; categorical pools take from A when ratio<0.5, from B otherwise.
- **`list_personalities()`** — Returns every personality grouped by role with name, sweet-spot tempo, and one-line description.
- **`add_personality_solo(...)`** — Legacy alias for `add_personality` restricted to `solo` personalities.

#### Personality reference (33 total)

**Solo (9)** — melodic / lead lines

| Key | Player | Sweet spot | Surface style |
|---|---|---|---|
| `coltrane` | John Coltrane | 200 BPM | Sheets of sound, modal scalar runs with chromatic approach |
| `kenny_g` | Kenny G | 95 BPM | Sparse high-register sustained chord tones, lots of space |
| `oscar_peterson` | Oscar Peterson | 160 BPM | Swung bebop with octave doublings, blues turns, dramatic dynamics |
| `miles_davis` | Miles Davis | 120 BPM | Cool / modal — half the bar is silence, target chord tones |
| `charlie_parker` | Charlie Parker | 230 BPM | Bebop dense — chromatic approach into every chord tone |
| `wayne_shorter` | Wayne Shorter | 140 BPM | Modern angular — wide intervallic leaps, modal/altered |
| `pat_metheny` | Pat Metheny | 130 BPM | Lyrical guitar — long phrases over lydian/dorian, mostly straight |
| `stan_getz` | Stan Getz | 100 BPM | Cool / bossa — smooth long melodic phrases, mostly chord tones |
| `dizzy_gillespie` | Dizzy Gillespie | 240 BPM | Bebop trumpet — fast chromatic runs in the screaming register |

**Comp (6)** — chord voicings / comping

| Key | Player | Sweet spot | Surface style |
|---|---|---|---|
| `bill_evans` | Bill Evans | 110 BPM | Sustained rootless 3-7 voicings, half-note pulses, soft romantic |
| `mccoy_tyner` | McCoy Tyner | 180 BPM | Quartal stacks (chords in 4ths) with 16th-note percussive stabs |
| `herbie_hancock` | Herbie Hancock | 140 BPM | Rootless voicings on every offbeat — Miles 60s polyrhythmic |
| `red_garland` | Red Garland | 130 BPM | Locked-hands block chords in 4/4 quarters — hard bop |
| `chick_corea` | Chick Corea | 150 BPM | Modern fusion — dense 5-voice rootless polychords, syncopated |
| `wynton_kelly` | Wynton Kelly | 140 BPM | Hard bop bluesy shell voicings with anticipated comping |

**Bass (6)** — bass lines

| Key | Player | Sweet spot | Surface style |
|---|---|---|---|
| `james_jamerson` | James Jamerson | 105 BPM | Motown busy syncopated 8ths, ghost notes, mid P-bass register |
| `jaco_pastorius` | Jaco Pastorius | 120 BPM | Melodic fretless in upper register — chord tones, big leaps, slides |
| `pino_palladino` | Pino Palladino | 90 BPM | Smooth R&B — root and 5th in the lowest register, soft pocket |
| `marcus_miller` | Marcus Miller | 100 BPM | Slap funk — hugely percussive 16ths with massive thumb/pop dynamics |
| `ray_brown` | Ray Brown | 140 BPM | Straight quarter-note jazz walking, low register, locked-in |
| `charles_mingus` | Charles Mingus | 130 BPM | Expressive upright walking — dramatic dynamics, chromatic, slides |

**Drums (12)** — drum kit patterns

*Acoustic / live drummers*

| Key | Player | Sweet spot | Surface style |
|---|---|---|---|
| `questlove` | Questlove | 88 BPM | Deep behind-the-beat pocket, ghost notes between backbeats |
| `tony_williams` | Tony Williams | 220 BPM | Canonical jazz ride pattern, feathered kick, hard swing, ahead |
| `vinnie_colaiuta` | Vinnie Colaiuta | 130 BPM | Polyrhythmic 16th hats, syncopated kicks, ghost-note carpet, fills |
| `j_dilla` | J Dilla | 85 BPM | Drunk hip-hop — way behind the beat, irregular kicks, sloppy on purpose |
| `elvin_jones` | Elvin Jones | 220 BPM | Triplet-feel polyrhythmic ride pattern, dense triplet ghosts, ahead |
| `stewart_copeland` | Stewart Copeland | 130 BPM | Reggae-rock — sparse kicks, busy 16th hats with frequent open hat |

*Hip-hop producer kits (MPC / sampler)*

| Key | Player | Sweet spot | Surface style |
|---|---|---|---|
| `timbaland` | Timbaland | 96 BPM | Off-grid syncopated kicks, stuttering 16th hats, vocal-percussion ghosts |
| `dr_dre` | Dr. Dre | 94 BPM | G-funk tight live-feel pocket, sparse kicks on 1 and 'and-of-3', hard-hitting |
| `dj_premier` | DJ Premier | 92 BPM | Classic boom bap — hard kicks on 1 and 3, hard snares on 2 and 4, no fills |
| `pete_rock` | Pete Rock | 88 BPM | Jazzy boom bap with ghost-snare rolls and slight behind-the-beat feel |
| `metro_boomin` | Metro Boomin | 75 BPM | Modern half-time trap — kick on 1 + and-of-3, snare on 3 only, dense hat rolls |
| `madlib` | Madlib | 92 BPM | Dusty MPC off-kilter — irregular kicks, behind the beat, lo-fi looseness |

#### Examples

```
"Replace the lead in clip 0 of track 7 with a Coltrane solo over Cm Ab Eb Bb"
"Write a Bill Evans rootless comp into the chord track for the chorus"
"Generate a Jaco-style bassline for Cm Fm G7 Cm"
"Add a Questlove drum pattern to track 4, scene 3"
"Blend Coltrane and Kenny G 70/30 into a lead solo over the bridge"
"Write a Charles Mingus walking bass at the current session tempo"
```

### Tier 5 — Arrangement view (BETA)

- **`get_arrangement_info`** — Reports capability detection, song length, loop region, locators, and per-track arrangement clips.
- **`add_clip_to_arrangement(track, slot, time)`** — BETA. Drops a session clip onto the arrangement timeline. Capability-probed: returns a structured "unsupported" error on Live versions that don't expose `Track.duplicate_clip_to_arrangement`. **Verified working on Live 12.2.7.**
- **`set_arrangement_loop(start, end, on)`** — Stable across Live 11+.
- **`add_arrangement_locator(time, name)`** — Verse / chorus / bridge markers. **⚠ KNOWN ISSUE — partially working:** the rename path (when a cue already exists at the target time) is reliable, but creating a brand-new cue at an arbitrary timeline position is flaky due to a Live API quirk where `Song.current_song_time = X` writes don't always commit before `Song.set_or_delete_cue()` reads the play head, even with chained `schedule_message` callbacks. Workaround: use `⌘L` in Ableton to add locators manually at the play head position (Live's native shortcut bypasses the API).
- **`clear_all_arrangement_locators`** — Tries to delete every cue point. Same caveat as `add_arrangement_locator` — works for cues that the play head actually lands on, doesn't reliably delete every cue.
- **`bounce_session_to_arrangement(scene_order, bar_length?)`** — BETA. Renders a sequence of scenes onto the arrangement timeline as a one-call session-sketch → arrangement workflow. Requires `can_duplicate_to_arrangement: true` in `get_arrangement_info`.

### Tier 6 — Infrastructure & quality of life

- **`batch_commands(commands)`** — Send N commands in one socket round-trip. The whole batch executes inside a single main-thread closure on Live's side, so it's atomic from Live's perspective and a single subsequent `undo` reverts the entire sequence. Stops on the first failure and returns partial results.
- **Warm-path auto-reconnect** — `send_command` retries once on `BrokenPipeError` / `ConnectionResetError` so a brief Ableton restart no longer breaks the session.
- **Auto-extending clips** — `add_notes_to_clip` now extends the clip's `end_marker` if any of the supplied notes would otherwise be truncated. **This is a behavior change** vs upstream, which silently dropped notes past the clip end.
- **Extended `get_session_info`** — Now also reports `scene_count`, `scene_names`, `is_playing`, `current_song_time`, and `arrangement_length`.
- **Internal dispatch refactor** — The remote script's command if/elif chain has been replaced with two dispatch dicts, making future tool additions a one-line change instead of a 30-line edit. Also dropped three dead-code branches that referenced non-existent methods.

### Stability fixes (still included from PR #84)

- Fixed a timeout race that could affect destructive commands; `get_clip_notes` runs via direct execution.
- `load_browser_item` is correctly recognized as a modifying command.

## Features

- **Two-way communication**: Connect Claude AI to Ableton Live through a socket-based server
- **One-call session bootstrap**: `setup_session` creates a whole project (tempo, time sig, tracks, instruments, mix) in a single round-trip
- **Batched commands**: send N commands at once with atomic undo via `batch_commands`
- **33 personalities, 4 roles**: solo / comp / bass / drums in the style of Coltrane, Bill Evans, Jaco, Questlove, Timbaland, Dr. Dre, Metro Boomin, etc. — BPM-aware, blendable
- **Track manipulation**: Create, name, mute, solo, arm, delete, and mix MIDI/audio tracks
- **Devices**: Read every device's parameter list with min/max values; set parameters by raw Live value
- **Instrument and effect selection**: Search the browser by name, or load with a single composite call
- **Clip creation and editing**: Create, edit, read, duplicate (cross-track), resize, loop, and delete MIDI clips and notes (with auto-extending clip length)
- **Music theory primitives**: Chord progressions, scale runs, drum patterns, quantize, transpose
- **Mixer control**: Track and master volume, pan, and return-track sends
- **Session control**: Start/stop playback, fire individual clips or whole scenes, create scenes
- **Arrangement view (BETA)**: Capability-probed support for dropping clips onto the timeline, setting the arrangement loop, adding locators, and bouncing a scene order to a full arrangement
- **Undo support**: Revert the last action — including a whole batch as one step

## Components

The system consists of two main components:

1. **Ableton Remote Script** (`Ableton_Remote_Script/__init__.py`): A MIDI Remote Script for Ableton Live that creates a socket server to receive and execute commands
2. **MCP Server** (`server.py`): A Python server that implements the Model Context Protocol and connects to the Ableton Remote Script

## Installation

### Installing via Smithery

To install Ableton Live Integration for Claude Desktop automatically via [Smithery](https://smithery.ai/server/@ahujasid/ableton-mcp):

```bash
npx -y @smithery/cli install @ahujasid/ableton-mcp --client claude
```

### Prerequisites

- Ableton Live 10 or newer
- Python 3.8 or newer
- [uv package manager](https://astral.sh/uv)

If you're on Mac, please install uv as:
```
brew install uv
```

Otherwise, install from [uv's official website][https://docs.astral.sh/uv/getting-started/installation/]

⚠️ Do not proceed before installing UV

### Claude for Desktop Integration

[Follow along with the setup instructions video](https://youtu.be/iJWJqyVuPS8)

1. Go to Claude > Settings > Developer > Edit Config > claude_desktop_config.json to include the following:

```json
{
    "mcpServers": {
        "AbletonMCP": {
            "command": "uvx",
            "args": [
                "ableton-mcp"
            ]
        }
    }
}
```

### Cursor Integration

Run ableton-mcp without installing it permanently through uvx. Go to Cursor Settings > MCP and paste this as a command:

```
uvx ableton-mcp
```

⚠️ Only run one instance of the MCP server (either on Cursor or Claude Desktop), not both

### Installing the Ableton Remote Script

[Follow along with the setup instructions video](https://youtu.be/iJWJqyVuPS8)

1. Download the `AbletonMCP_Remote_Script/__init__.py` file from this repo

2. Copy the folder to Ableton's MIDI Remote Scripts directory. Different OS and versions have different locations. **One of these should work, you might have to look**:

   **For macOS:**
   - Method 1: Go to Applications > Right-click on Ableton Live app → Show Package Contents → Navigate to:
     `Contents/App-Resources/MIDI Remote Scripts/`
   - Method 2: If it's not there in the first method, use the direct path (replace XX with your version number):
     `/Users/[Username]/Library/Preferences/Ableton/Live XX/User Remote Scripts`
   
   **For Windows:**
   - Method 1:
     C:\Users\[Username]\AppData\Roaming\Ableton\Live x.x.x\Preferences\User Remote Scripts 
   - Method 2:
     `C:\ProgramData\Ableton\Live XX\Resources\MIDI Remote Scripts\`
   - Method 3:
     `C:\Program Files\Ableton\Live XX\Resources\MIDI Remote Scripts\`
   *Note: Replace XX with your Ableton version number (e.g., 10, 11, 12)*

4. Create a folder called 'AbletonMCP' in the Remote Scripts directory and paste the downloaded '\_\_init\_\_.py' file

3. Launch Ableton Live

4. Go to Settings/Preferences → Link, Tempo & MIDI

5. In the Control Surface dropdown, select "AbletonMCP"

6. Set Input and Output to "None"

## Usage

### Starting the Connection

1. Ensure the Ableton Remote Script is loaded in Ableton Live
2. Make sure the MCP server is configured in Claude Desktop or Cursor
3. The connection should be established automatically when you interact with Claude

### Using with Claude

Once the config file has been set on Claude, and the remote script is running in Ableton, you will see a hammer icon with tools for the Ableton MCP.

## Capabilities

- Get session, track, and arrangement information
- Bootstrap a whole session in one call (`setup_session`)
- Batch any sequence of commands as a single atomic, single-undo operation
- Create / name / arm / mute / solo / delete MIDI and audio tracks
- Create, edit, read, duplicate (cross-track), resize, and loop clips
- Add, remove, transpose, and quantize MIDI notes
- Auto-extending clips when notes overflow the current length
- Read every device's parameters (with min/max) and set them by raw Live value
- Search the Ableton browser by name and load by URI or by name
- Set track volume / pan / return-track sends and master volume
- Control tempo, time signature, playback, individual clips, and entire scenes
- Create scenes and set per-scene name / tempo
- Generate chord progressions, scale runs, and preset drum patterns
- **Generate parts in the style of named players** — 9 solo personalities (Coltrane, Kenny G, Oscar Peterson, Miles, Parker, Wayne Shorter, Metheny, Getz, Dizzy), 6 comp (Bill Evans, McCoy Tyner, Hancock, Red Garland, Chick Corea, Wynton Kelly), 6 bass (Jamerson, Jaco, Pino, Marcus Miller, Ray Brown, Mingus), 12 drums (Questlove, Tony Williams, Vinnie, J Dilla, Elvin Jones, Stewart Copeland, Timbaland, Dr. Dre, DJ Premier, Pete Rock, Metro Boomin, Madlib) — all BPM-aware
- **Blend two solo personalities** (e.g. 70% Coltrane + 30% Kenny G) into a synthetic profile
- Drop session clips onto the arrangement timeline (BETA), set the arrangement loop, and bounce a scene order to a full arrangement (BETA)
- Undo the last action — including a whole batch as one step

## Example Commands

Here are some examples of what you can ask Claude to do:

- "Create an 80s synthwave track" [Demo](https://youtu.be/VH9g66e42XA)
- "Create a Metro Boomin style hip-hop beat"
- "Create a new MIDI track with a synth bass instrument"
- "Add reverb to my drums"
- "Create a 4-bar MIDI clip with a simple melody"
- "Get information about the current Ableton session"
- "Load a 808 drum rack into the selected track"
- "Add a jazz chord progression to the clip in track 1"
- "Set the tempo to 120 BPM"
- "Play the clip in track 2"
- "Read the notes in clip 1 of track 3 and harmonize them a third up"
- "Clear all the notes from the bass clip and write a new pattern"
- "Duplicate the drum clip in slot 1 to slot 2"
- "Add an audio track and set its volume to -6 dB"
- "Pan the hi-hats slightly to the right"
- "Send 30% of the lead vocal to Return A"
- "Fire scene 2"
- "Undo that"
- "Set up a session at 90 BPM in 6/8 with four MIDI tracks: Drums, Bass, Lead, Pad" (`setup_session`)
- "Search the browser for Operator and load it on track 0" (`load_instrument_by_name`)
- "Write a Cm-Fm-G7-Cm progression into clip 0 of the chord track" (`add_chord_progression`)
- "Add a four-on-the-floor beat to track 0" (`add_drum_pattern`)
- "Quantize the lead clip to 1/16" (`quantize_clip`)
- "Transpose the bass clip up by 7 semitones" (`transpose_clip`)
- "Mute track 1 and arm track 2 for recording"
- "Show me the parameters of the device on track 3" (`get_track_devices`)
- "Set parameter 4 of the first device on track 3 to 8000" (`set_device_parameter`)
- "Set the time signature to 3/4"
- "Create a new scene named 'Bridge'"
- "Bounce scenes [0, 0, 1, 2, 1, 3] onto the arrangement" (`bounce_session_to_arrangement`, BETA)
- "Add a locator at beat 32 named 'Drop'" (`add_arrangement_locator`)
- "Replace the lead with a Coltrane solo over Cm Ab Eb Bb" (`add_personality`)
- "Write a Bill Evans rootless comp for the chorus chords" (`add_personality`)
- "Make the bass play like James Jamerson" (`add_personality`)
- "Use a Questlove drum pattern for the verse" (`add_personality`)
- "Blend Coltrane and Kenny G 70/30 into the lead" (`add_blended_personality_solo`)
- "Show me which personalities I can use" (`list_personalities`)


## Troubleshooting

- **Connection issues**: Make sure the Ableton Remote Script is loaded, and the MCP server is configured on Claude
- **Timeout errors**: Try simplifying your requests or breaking them into smaller steps
- **Have you tried turning it off and on again?**: If you're still having connection errors, try restarting both Claude and Ableton Live

## Technical Details

### Communication Protocol

The system uses a simple JSON-based protocol over TCP sockets:

- Commands are sent as JSON objects with a `type` and optional `params`
- Responses are JSON objects with a `status` and `result` or `message`

### Limitations & Security Considerations

- Creating complex musical arrangements might need to be broken down into smaller steps
- The tool is designed to work with Ableton's default devices and browser items
- Always save your work before extensive experimentation

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Disclaimer

This is a third-party integration and not made by Ableton.
