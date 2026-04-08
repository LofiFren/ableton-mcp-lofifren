"""Rule-based personality system for the AbletonMCP Tier 4 tools.

A personality is a profile dict describing surface stylistic features of a
real-world player. Profiles are organized by **role**:

    solo   — melodic / lead lines (sax, lead synth, melody)
    comp   — chord voicings / comping (piano, keys, guitar)
    bass   — bass lines (electric / upright / synth bass)
    drums  — drum kit patterns (kick / snare / hat)

Each role has its own generator function. The unified
``generate_personality_part`` dispatches by role. Adding a new personality is
one dict entry plus (if it's a new role) one new generator. All personalities
are tempo-aware: profiles declare ``tempo_sweet_spot`` / ``tempo_min`` /
``tempo_max`` and the generators scale note density and swing relative to
the actual session BPM.

Style blending (``blend_personalities``) interpolates numeric profile fields
and unions categorical pools so you can mix two players (e.g. 70% Coltrane
+ 30% Kenny G).
"""
from __future__ import annotations
import random
from typing import Any, Dict, List, Optional, Tuple

from MCP_Server.music import (
    NOTE_TO_SEMITONE,
    SCALES,
    CHORDS,
    parse_chord,
    parse_scale,
    chord_quality,
    chord_root_pitch,
    scale_pitches_in_range,
)


# ===================== Personality profiles =====================

# Each profile carries:
#   role:                "solo" | "comp" | "bass" | "drums"
#   name:                display name
#   instrument_hint:     what the part sounds like on (informational only)
#   tempo_sweet_spot:    BPM where this style lives (single number)
#   tempo_min, tempo_max: outside this range, the generator warns but still produces
#   description:         one-line summary
#   ... role-specific fields below
#
# Solo fields:
#   density:             "low" | "medium" | "medium-high" | "high"
#   swing:               0.5 = straight, 0.62 ≈ medium swing, 0.66 = hard swing
#   range:               (low_midi, high_midi) inclusive
#   minor_scale_pool:    list of scale modes preferred over minor chords
#   major_scale_pool:    list of scale modes preferred over major chords
#   use_chromatic:       whether chromatic approach notes are allowed
#   chromatic_chance:    probability per note
#   chord_tone_emphasis: 0..1 — bias toward chord tones on strong beats
#   velocity_range:      (min, max)
#   rest_chance:         per-step probability of resting
#   octave_jump_chance:  per-step probability of jumping an octave
#   long_notes:          if True, sustain notes across multiple steps
#   phrase_arc:          "rising" | "ascend_then_descend" | "arched" | "static"
#
# Comp fields:
#   voicing_style:       "rootless" | "quartal" | "block" | "shell"
#   voice_count:         how many notes per voicing
#   voicing_range:       (low_midi, high_midi)
#   rhythm_pattern:      list of (beat_offset, duration) pairs in one bar
#   velocity_range:      (min, max)
#   swing:               0.5..0.7
#   use_extensions:      if True, add 9/13/etc tensions
#
# Bass fields:
#   walking_density:     "low" (root on 1) | "medium" (root + 5th + chord tone) | "high" (walking 8ths)
#   range:               (low_midi, high_midi)  electric bass = (28, 60)
#   ghost_note_chance:   0..1
#   slide_chance:        0..1 — whether to add chromatic slides
#   chord_tone_priority: 0..1
#   velocity_range:      (min, max)
#   syncopation:         0..1 (how off-beat the rhythm is)
#   swing:               0.5..0.7
#
# Drums fields:
#   kit_map:             dict drum_key -> midi pitch (default GM)
#   pocket:              "behind" | "on_top" | "ahead" — micro-timing
#   pocket_offset_beats: how much to shift (e.g. 0.02 behind)
#   kick_pattern:        list of beat positions in one bar
#   snare_pattern:       list of beat positions in one bar
#   hat_pattern:         list of beat positions in one bar
#   ghost_snare_chance:  0..1
#   ride_instead_of_hat: bool (use ride cymbal MIDI 51)
#   open_hat_chance:     0..1 on the "and" of 4
#   velocity_range:      (min, max) — strong vs ghost
#   swing:               0.5..0.7
#   fill_chance:         0..1 — chance of a fill at end of 4-bar phrase

PERSONALITIES: Dict[str, Dict[str, Any]] = {

    # ============== SOLO ==============

    "coltrane": {
        "role": "solo",
        "name": "John Coltrane",
        "instrument_hint": "tenor sax / soprano sax",
        "tempo_sweet_spot": 200,
        "tempo_min": 80,
        "tempo_max": 280,
        "density": "high",
        "swing": 0.62,
        "range": (60, 88),
        "minor_scale_pool": ["dorian", "minor_pentatonic", "blues", "altered"],
        "major_scale_pool": ["altered", "lydian", "pentatonic"],
        "use_chromatic": True,
        "chromatic_chance": 0.30,        # was 0.18 — more "sheets of sound" chromaticism
        "chord_tone_emphasis": 0.40,     # was 0.55 — Coltrane is MORE scalar than chord-targeting
        "velocity_range": (85, 118),     # was (78,112) — louder, more dramatic
        "rest_chance": 0.02,             # was 0.04 — almost no rests
        "octave_jump_chance": 0.05,
        "long_notes": False,
        "phrase_arc": "ascend_then_descend",
        "description": "Sheets of sound — fast modal scalar runs with heavy chromatic approach, almost no rests",
    },
    "kenny_g": {
        "role": "solo",
        "name": "Kenny G",
        "instrument_hint": "soprano sax",
        "tempo_sweet_spot": 95,
        "tempo_min": 60,
        "tempo_max": 130,
        "density": "low",
        "swing": 0.54,
        "range": (78, 98),               # was (74,98) — even higher, only soprano sax sweet spot
        "minor_scale_pool": ["minor_pentatonic", "dorian"],
        "major_scale_pool": ["pentatonic", "major"],
        "use_chromatic": False,
        "chromatic_chance": 0.0,
        "chord_tone_emphasis": 0.95,     # was 0.85 — almost ALWAYS a chord tone
        "velocity_range": (60, 88),      # was (65,95) — softer
        "rest_chance": 0.35,             # was 0.22 — way more breathing room
        "octave_jump_chance": 0.0,
        "long_notes": True,
        "phrase_arc": "rising",
        "description": "Sparse high-register sustained chord tones — almost no rhythmic activity, lots of space",
    },
    "oscar_peterson": {
        "role": "solo",
        "name": "Oscar Peterson",
        "instrument_hint": "jazz piano",
        "tempo_sweet_spot": 160,
        "tempo_min": 70,
        "tempo_max": 260,
        "density": "medium-high",
        "swing": 0.68,                   # was 0.66 — harder swing
        "range": (48, 84),
        "minor_scale_pool": ["minor_pentatonic", "blues", "dorian"],
        "major_scale_pool": ["bebop", "blues", "pentatonic"],
        "use_chromatic": True,
        "chromatic_chance": 0.15,
        "chord_tone_emphasis": 0.65,
        "velocity_range": (55, 120),     # was (62,115) — more dynamic range
        "rest_chance": 0.06,
        "octave_jump_chance": 0.15,      # was 0.08 — Oscar's signature octave doubling
        "long_notes": False,
        "phrase_arc": "arched",
        "description": "Swung bebop with frequent octave doublings, blues turns, dramatic dynamics",
    },
    "miles_davis": {
        "role": "solo",
        "name": "Miles Davis",
        "instrument_hint": "muted trumpet",
        "tempo_sweet_spot": 120,
        "tempo_min": 60,
        "tempo_max": 200,
        "density": "low",
        "swing": 0.58,
        "range": (58, 78),               # was (58,82) — Miles stays mid-range
        "minor_scale_pool": ["dorian", "minor_pentatonic"],
        "major_scale_pool": ["lydian", "pentatonic"],
        "use_chromatic": False,
        "chromatic_chance": 0.03,
        "chord_tone_emphasis": 0.85,
        "velocity_range": (45, 85),      # was (55,100) — softer, more cool
        "rest_chance": 0.50,             # was 0.30 — HALF the time he rests
        "octave_jump_chance": 0.02,
        "long_notes": True,
        "phrase_arc": "arched",
        "description": "Cool / modal — half the bar is silence, target chord tones with long sustained notes",
    },
    "charlie_parker": {
        "role": "solo",
        "name": "Charlie Parker",
        "instrument_hint": "alto sax",
        "tempo_sweet_spot": 230,
        "tempo_min": 120,
        "tempo_max": 320,
        "density": "high",
        "swing": 0.68,
        "range": (60, 92),               # was (60,90) — alto goes a bit higher
        "minor_scale_pool": ["bebop", "minor_pentatonic", "blues"],
        "major_scale_pool": ["bebop", "blues"],
        "use_chromatic": True,
        "chromatic_chance": 0.35,        # was 0.22 — bebop is HEAVY on chromatic approach
        "chord_tone_emphasis": 0.85,     # was 0.70 — bebop targets chord tones aggressively
        "velocity_range": (75, 118),
        "rest_chance": 0.03,
        "octave_jump_chance": 0.10,
        "long_notes": False,
        "phrase_arc": "arched",
        "description": "Bebop dense — chromatic approach into every chord tone, virtuosic alto runs",
    },
    "wayne_shorter": {
        "role": "solo",
        "name": "Wayne Shorter",
        "instrument_hint": "tenor / soprano sax",
        "tempo_sweet_spot": 140,
        "tempo_min": 70,
        "tempo_max": 220,
        "density": "medium",
        "swing": 0.6,
        "range": (58, 88),
        "minor_scale_pool": ["dorian", "altered", "melodic_minor"],
        "major_scale_pool": ["lydian", "altered"],
        "use_chromatic": True,
        "chromatic_chance": 0.08,
        "chord_tone_emphasis": 0.45,     # was 0.50 — more outside playing
        "velocity_range": (55, 110),
        "rest_chance": 0.25,             # was 0.15 — more deliberate spacing
        "octave_jump_chance": 0.20,      # was 0.12 — wide intervallic leaps
        "long_notes": False,
        "phrase_arc": "static",
        "description": "Modern angular — wide intervallic leaps, modal/altered, deliberate spacing",
    },
    "pat_metheny": {
        "role": "solo",
        "name": "Pat Metheny",
        "instrument_hint": "jazz guitar (warm hollow body)",
        "tempo_sweet_spot": 130,
        "tempo_min": 70,
        "tempo_max": 200,
        "density": "medium",
        "swing": 0.55,                   # mostly straight 8ths
        "range": (55, 84),               # G3-C6 — guitar register
        "minor_scale_pool": ["dorian", "melodic_minor", "minor_pentatonic"],
        "major_scale_pool": ["lydian", "pentatonic", "major"],
        "use_chromatic": True,
        "chromatic_chance": 0.06,
        "chord_tone_emphasis": 0.6,
        "velocity_range": (60, 105),
        "rest_chance": 0.18,
        "octave_jump_chance": 0.05,
        "long_notes": False,
        "phrase_arc": "rising",
        "description": "Lyrical guitar — long phrases over lydian/dorian, mostly straight 8ths, midwest-warm",
    },
    "stan_getz": {
        "role": "solo",
        "name": "Stan Getz",
        "instrument_hint": "tenor sax (cool / bossa)",
        "tempo_sweet_spot": 100,
        "tempo_min": 60,
        "tempo_max": 160,
        "density": "low",
        "swing": 0.55,                   # bossa is straight-ish
        "range": (62, 86),               # D4-D6 — tenor sweet spot
        "minor_scale_pool": ["dorian", "minor_pentatonic"],
        "major_scale_pool": ["pentatonic", "major", "lydian"],
        "use_chromatic": False,
        "chromatic_chance": 0.02,
        "chord_tone_emphasis": 0.85,
        "velocity_range": (55, 95),
        "rest_chance": 0.30,
        "octave_jump_chance": 0.03,
        "long_notes": True,
        "phrase_arc": "arched",
        "description": "Cool / bossa — smooth long melodic phrases, sparse, mostly chord tones",
    },
    "dizzy_gillespie": {
        "role": "solo",
        "name": "Dizzy Gillespie",
        "instrument_hint": "trumpet (high register)",
        "tempo_sweet_spot": 240,
        "tempo_min": 140,
        "tempo_max": 320,
        "density": "high",
        "swing": 0.66,
        "range": (67, 96),               # G4-C7 — trumpet GOES high
        "minor_scale_pool": ["bebop", "minor_pentatonic", "blues"],
        "major_scale_pool": ["bebop", "blues", "altered"],
        "use_chromatic": True,
        "chromatic_chance": 0.30,
        "chord_tone_emphasis": 0.75,
        "velocity_range": (80, 122),     # bright loud trumpet
        "rest_chance": 0.04,
        "octave_jump_chance": 0.12,      # leaps to scream notes
        "long_notes": False,
        "phrase_arc": "ascend_then_descend",
        "description": "Bebop trumpet — fast chromatic runs in the high register, dramatic leaps to scream notes",
    },

    # ============== COMP ==============

    "bill_evans": {
        "role": "comp",
        "name": "Bill Evans",
        "instrument_hint": "acoustic / electric piano",
        "tempo_sweet_spot": 110,
        "tempo_min": 50,
        "tempo_max": 200,
        "voicing_style": "rootless",
        "voice_count": 4,
        "voicing_range": (52, 74),                # E3-D5 — Evans's left-hand zone
        # Half-note pulses sustain through Operator's amp envelope better than
        # one-per-bar held notes, and make the part sound like comping rather
        # than a single chord. Two retriggers per bar = 8 voicings/4-bar clip.
        "rhythm_pattern": [(0.0, 2.0), (2.0, 2.0)],
        "velocity_range": (50, 80),               # softer than the others
        "swing": 0.56,
        "use_extensions": True,
        "description": "Sustained rootless 3-7 voicings, half-note pulses, soft dynamics, romantic ballad",
    },
    "mccoy_tyner": {
        "role": "comp",
        "name": "McCoy Tyner",
        "instrument_hint": "acoustic piano",
        "tempo_sweet_spot": 180,
        "tempo_min": 90,
        "tempo_max": 280,
        "voicing_style": "quartal",
        "voice_count": 4,
        "voicing_range": (40, 80),                # E2-G#5 — Tyner uses the WHOLE range
        # 16th-note short stabs landing on/off the beat — percussive and rhythmic.
        "rhythm_pattern": [
            (0.0, 0.25), (0.75, 0.25), (1.5, 0.25),
            (2.0, 0.25), (2.5, 0.25), (3.0, 0.25), (3.75, 0.25),
        ],
        "velocity_range": (90, 122),              # LOUD — way louder than Evans (50-80)
        "swing": 0.64,
        "use_extensions": False,
        "description": "Quartal stacks (chords in 4ths) with 16th-note percussive stabs, very loud",
    },
    "herbie_hancock": {
        "role": "comp",
        "name": "Herbie Hancock",
        "instrument_hint": "acoustic / electric piano (Rhodes era)",
        "tempo_sweet_spot": 140,
        "tempo_min": 70,
        "tempo_max": 220,
        "voicing_style": "rootless",
        "voice_count": 4,
        "voicing_range": (53, 78),                # F3-F#5
        # Comping ON THE OFFBEATS — the 'and' of 1, 'and' of 2, 'and' of 3.
        # This is the Miles 60s quintet polyrhythmic feel.
        "rhythm_pattern": [(0.5, 0.4), (1.5, 0.4), (2.5, 0.4), (3.75, 0.25)],
        "velocity_range": (65, 100),
        "swing": 0.6,
        "use_extensions": True,
        "description": "Rootless voicings comping on every offbeat — polyrhythmic Miles 60s quintet feel",
    },
    "red_garland": {
        "role": "comp",
        "name": "Red Garland",
        "instrument_hint": "acoustic piano (locked-hands)",
        "tempo_sweet_spot": 130,
        "tempo_min": 70,
        "tempo_max": 220,
        "voicing_style": "block",
        "voice_count": 4,
        "voicing_range": (50, 76),                # D3-E5
        # Quarter-note retriggers for the locked-hands swing feel
        "rhythm_pattern": [(0.0, 1.0), (1.0, 1.0), (2.0, 1.0), (3.0, 1.0)],
        "velocity_range": (62, 100),
        "swing": 0.62,
        "use_extensions": False,
        "description": "Locked-hands block-chord comping in 4/4 quarters — Miles 50s quintet hard bop feel",
    },
    "chick_corea": {
        "role": "comp",
        "name": "Chick Corea",
        "instrument_hint": "acoustic / electric piano (fusion)",
        "tempo_sweet_spot": 150,
        "tempo_min": 80,
        "tempo_max": 240,
        "voicing_style": "rootless",
        "voice_count": 5,                          # denser polychord-style
        "voicing_range": (50, 84),                 # very wide
        # Mixed eighth-and-sixteenth syncopated stabs
        "rhythm_pattern": [(0.0, 0.5), (0.75, 0.25), (1.5, 0.5), (2.5, 0.5), (3.0, 0.25), (3.5, 0.5)],
        "velocity_range": (70, 115),
        "swing": 0.55,                             # mostly straight (fusion)
        "use_extensions": True,
        "description": "Modern fusion — dense 5-voice rootless polychords with mixed-meter syncopation",
    },
    "wynton_kelly": {
        "role": "comp",
        "name": "Wynton Kelly",
        "instrument_hint": "acoustic piano (hard bop blues)",
        "tempo_sweet_spot": 140,
        "tempo_min": 70,
        "tempo_max": 240,
        "voicing_style": "shell",                  # 1-3-7 or 3-7 minimal
        "voice_count": 3,
        "voicing_range": (48, 70),                 # C3-A#4
        # Bluesy hard bop comping — anticipations and the upbeat of 4
        "rhythm_pattern": [(0.0, 0.75), (1.5, 0.5), (2.0, 0.5), (3.5, 0.5)],
        "velocity_range": (62, 105),
        "swing": 0.66,
        "use_extensions": False,
        "description": "Hard bop bluesy shell voicings (1-3-7) with anticipated comping accents",
    },

    # ============== BASS ==============

    "james_jamerson": {
        "role": "bass",
        "name": "James Jamerson",
        "instrument_hint": "Fender Precision (Motown)",
        "tempo_sweet_spot": 105,
        "tempo_min": 70,
        "tempo_max": 140,
        "walking_density": "high",
        "range": (28, 55),                       # E1-G3
        "register_preference": "mid",            # ~middle of range — classic P-bass register
        "ghost_note_chance": 0.30,               # was 0.18 — Jamerson is famous for ghost notes
        "slide_chance": 0.05,
        "chord_tone_priority": 0.7,
        "velocity_range": (50, 115),             # was (60,110) — bigger contrast for ghosts vs hits
        "syncopation": 0.6,
        "swing": 0.56,
        "description": "Motown busy syncopated 8ths, lots of ghost notes, mid-register P-bass tone",
    },
    "jaco_pastorius": {
        "role": "bass",
        "name": "Jaco Pastorius",
        "instrument_hint": "fretless electric bass",
        "tempo_sweet_spot": 120,
        "tempo_min": 60,
        "tempo_max": 220,
        "walking_density": "high",
        "range": (40, 67),                       # was (28,67) — Jaco goes HIGH, force upper half
        "register_preference": "high",           # actively bias to upper part of range
        "ghost_note_chance": 0.05,
        "slide_chance": 0.25,                    # fretless signature
        "chord_tone_priority": 0.85,             # was 0.80 — even more chord-tone melodic
        "velocity_range": (75, 118),             # was (70,115) — punchier
        "syncopation": 0.3,
        "swing": 0.55,
        "description": "Melodic fretless in upper register — chord tones, big intervallic moves, slides",
    },
    "pino_palladino": {
        "role": "bass",
        "name": "Pino Palladino",
        "instrument_hint": "fretless / Precision (R&B)",
        "tempo_sweet_spot": 90,
        "tempo_min": 60,
        "tempo_max": 130,
        "walking_density": "low",
        "range": (28, 43),                       # was (28,50) — Pino stays VERY low
        "register_preference": "low",            # bias to bottom of range
        "ghost_note_chance": 0.05,
        "slide_chance": 0.15,
        "chord_tone_priority": 0.95,             # was 0.90 — almost all chord tones
        "velocity_range": (50, 90),              # was (55,100) — softer R&B touch
        "syncopation": 0.15,
        "swing": 0.55,
        "description": "Smooth R&B bass — root and 5th in the lowest register, soft pocket, lots of space",
    },
    "marcus_miller": {
        "role": "bass",
        "name": "Marcus Miller",
        "instrument_hint": "slap bass (Fender Jazz)",
        "tempo_sweet_spot": 100,
        "tempo_min": 70,
        "tempo_max": 140,
        "walking_density": "high",
        "range": (28, 60),                       # E1-C4 — slap bass goes high too
        "register_preference": "mid",
        "ghost_note_chance": 0.45,               # slaps and pops are essentially ghost-velocity
        "slide_chance": 0.05,
        "chord_tone_priority": 0.55,             # walks AROUND chord tones with chromatic slides
        "velocity_range": (40, 127),             # HUGE dynamic range — slap pops are loud
        "syncopation": 0.85,                     # heavily syncopated funk
        "swing": 0.5,                            # straight 16ths
        "description": "Slap funk — hugely percussive, dense 16ths with massive velocity contrast for thumb/pop",
    },
    "ray_brown": {
        "role": "bass",
        "name": "Ray Brown",
        "instrument_hint": "upright bass (straight-ahead jazz)",
        "tempo_sweet_spot": 140,
        "tempo_min": 70,
        "tempo_max": 280,
        "walking_density": "medium",             # straight quarter-note walk
        "range": (28, 52),                       # E1-E3 — upright fundamental zone
        "register_preference": "low",
        "ghost_note_chance": 0.05,
        "slide_chance": 0.0,
        "chord_tone_priority": 0.55,             # walking includes plenty of passing tones
        "velocity_range": (65, 105),             # locked-in even dynamics
        "syncopation": 0.1,
        "swing": 0.62,
        "description": "Straight quarter-note jazz walking, low register, locked-in dynamics, classic upright tone",
    },
    "charles_mingus": {
        "role": "bass",
        "name": "Charles Mingus",
        "instrument_hint": "upright bass (expressive)",
        "tempo_sweet_spot": 130,
        "tempo_min": 60,
        "tempo_max": 240,
        "walking_density": "high",
        "range": (28, 55),                       # full upright range
        "register_preference": "mid",
        "ghost_note_chance": 0.12,
        "slide_chance": 0.10,                    # expressive bends and slides
        "chord_tone_priority": 0.50,             # frequent chromatic excursions
        "velocity_range": (45, 120),             # huge dynamic range, dramatic
        "syncopation": 0.45,
        "swing": 0.62,
        "description": "Expressive upright walking — dramatic dynamics, chromatic excursions, slides, syncopation",
    },

    # ============== DRUMS ==============

    "questlove": {
        "role": "drums",
        "name": "Questlove",
        "instrument_hint": "acoustic kit (hip-hop pocket)",
        "tempo_sweet_spot": 88,
        "tempo_min": 65,
        "tempo_max": 110,
        "pocket": "behind",
        "pocket_offset_beats": 0.06,              # was 0.025 — much more obviously behind
        "kick_pattern": [0.0, 2.5],               # kick on 1 and "and of 3"
        "snare_pattern": [1.0, 3.0],              # backbeat
        "hat_pattern": [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5],  # 8ths
        "ghost_snare_chance": 0.55,               # was 0.2 — Quest is FAMOUS for ghost notes
        "ride_instead_of_hat": False,
        "open_hat_chance": 0.0,
        "velocity_range": (35, 115),              # was (50,110) — wider so ghosts are clearly soft
        "swing": 0.52,
        "fill_chance": 0.10,
        "description": "Deep behind-the-beat pocket, lots of ghost notes between backbeats, sparse kicks",
    },
    "tony_williams": {
        "role": "drums",
        "name": "Tony Williams",
        "instrument_hint": "acoustic jazz kit",
        "tempo_sweet_spot": 220,
        "tempo_min": 100,
        "tempo_max": 320,
        "pocket": "ahead",
        "pocket_offset_beats": -0.025,            # ahead of the beat
        "kick_pattern": [0.0],                    # was [0,1,2,3] — Tony "feathers" beat 1 only
        "snare_pattern": [1.0, 3.0],
        # Canonical jazz ride: "ding ding-da ding ding-da" — quarter, quarter,
        # off-beat 8th, quarter, quarter, off-beat 8th. The off-beat 8ths get
        # swung by the swing factor.
        "hat_pattern": [0.0, 1.0, 1.5, 2.0, 3.0, 3.5],
        "ghost_snare_chance": 0.10,
        "ride_instead_of_hat": True,              # uses MIDI 51 (ride cymbal)
        "open_hat_chance": 0.0,
        "velocity_range": (40, 120),
        "swing": 0.70,                            # was 0.66 — Tony swings hard
        "fill_chance": 0.4,
        "description": "Canonical jazz ride pattern (ding-ding-da), feathered kick on 1, ahead of the beat, hard swing",
    },
    "vinnie_colaiuta": {
        "role": "drums",
        "name": "Vinnie Colaiuta",
        "instrument_hint": "acoustic kit (fusion)",
        "tempo_sweet_spot": 130,
        "tempo_min": 70,
        "tempo_max": 240,
        "pocket": "on_top",
        "pocket_offset_beats": 0.0,
        # Aggressively syncopated kicks — placed on the "and" of beats
        "kick_pattern": [0.0, 0.75, 1.5, 2.0, 2.75, 3.5],
        "snare_pattern": [1.0, 3.0],
        "hat_pattern": [0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.25, 3.5, 3.75],
        "ghost_snare_chance": 0.50,               # was 0.35 — even more
        "ride_instead_of_hat": False,
        "open_hat_chance": 0.20,                  # was 0.10
        "velocity_range": (30, 122),              # huge dynamic range
        "swing": 0.5,                             # straight 16ths
        "fill_chance": 0.6,
        "description": "Polyrhythmic 16th hats, syncopated kicks on every offbeat, ghost-note carpet, huge fills",
    },
    "j_dilla": {
        "role": "drums",
        "name": "J Dilla",
        "instrument_hint": "MPC / drunk hip-hop",
        "tempo_sweet_spot": 85,
        "tempo_min": 65,
        "tempo_max": 105,
        "pocket": "behind",
        "pocket_offset_beats": 0.10,              # WAY behind — Dilla's signature drunk pocket
        "kick_pattern": [0.0, 1.75, 2.5],          # irregular, off-grid
        "snare_pattern": [1.0, 3.0],
        "hat_pattern": [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5],
        "ghost_snare_chance": 0.40,
        "ride_instead_of_hat": False,
        "open_hat_chance": 0.0,
        "velocity_range": (35, 115),
        "swing": 0.58,                             # slightly swung 8ths
        "fill_chance": 0.05,                       # rarely fills — keeps the pocket
        "description": "Drunk hip-hop pocket — way behind the beat, irregular kicks, sloppy-on-purpose feel",
    },
    "elvin_jones": {
        "role": "drums",
        "name": "Elvin Jones",
        "instrument_hint": "acoustic jazz kit (Coltrane Quartet)",
        "tempo_sweet_spot": 220,
        "tempo_min": 120,
        "tempo_max": 320,
        "pocket": "ahead",
        "pocket_offset_beats": -0.02,
        # Triplet-feel kicks — beat 1 + 2 triplet positions in the bar
        "kick_pattern": [0.0, 1.333, 2.667],
        "snare_pattern": [1.0, 3.0],
        # Triplet ride pattern — ding on every beat + two triplet "da"s in the bar
        "hat_pattern": [0.0, 0.667, 1.0, 1.667, 2.0, 2.667, 3.0, 3.667],
        "ghost_snare_chance": 0.35,                # triplet ghost flurries
        "ride_instead_of_hat": True,
        "open_hat_chance": 0.0,
        "velocity_range": (40, 122),
        "swing": 0.66,                             # heavy triplet feel
        "fill_chance": 0.5,
        "description": "Triplet-feel polyrhythmic ride pattern, dense triplet ghost notes, ahead of the beat",
    },
    "stewart_copeland": {
        "role": "drums",
        "name": "Stewart Copeland",
        "instrument_hint": "acoustic kit (Police-era reggae rock)",
        "tempo_sweet_spot": 130,
        "tempo_min": 90,
        "tempo_max": 180,
        "pocket": "on_top",
        "pocket_offset_beats": 0.0,
        # Reggae-influenced rock kick: 1 + 2.5 (kind of one-drop ish)
        "kick_pattern": [0.0, 2.5],
        "snare_pattern": [1.0, 3.0],
        # 16th hats with accents on the off-beats — Stewart's hi-hat showcase
        "hat_pattern": [0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.25, 3.5, 3.75],
        "ghost_snare_chance": 0.10,
        "ride_instead_of_hat": False,
        "open_hat_chance": 0.40,                   # SIGNATURE — open hat all over
        "velocity_range": (55, 118),
        "swing": 0.5,
        "fill_chance": 0.30,
        "description": "Reggae-influenced rock — sparse kicks, busy 16th hats with frequent open hat accents",
    },

    # ============== HIP-HOP PRODUCER DRUMS ==============

    "timbaland": {
        "role": "drums",
        "name": "Timbaland",
        "instrument_hint": "MPC / sampled tribal kit + vocal percussion",
        "tempo_sweet_spot": 96,
        "tempo_min": 70,
        "tempo_max": 120,
        "pocket": "on_top",
        "pocket_offset_beats": 0.0,
        # Off-grid syncopated kicks — Timbo lives between the beats
        "kick_pattern": [0.0, 1.5, 2.75, 3.5],
        "snare_pattern": [1.0, 3.0],
        # Stuttering 16th hats with internal rhythmic flow
        "hat_pattern": [0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.25, 3.5, 3.75],
        "ghost_snare_chance": 0.30,                 # vocal-percussion-style ghosts
        "ride_instead_of_hat": False,
        "open_hat_chance": 0.18,
        "velocity_range": (40, 118),
        "swing": 0.52,
        "fill_chance": 0.20,
        "description": "Off-grid syncopated kicks, stuttering 16th hats, vocal-percussion ghost flurries",
    },
    "dr_dre": {
        "role": "drums",
        "name": "Dr. Dre",
        "instrument_hint": "G-funk MPC kit (live-feel)",
        "tempo_sweet_spot": 94,
        "tempo_min": 80,
        "tempo_max": 110,
        "pocket": "on_top",
        "pocket_offset_beats": 0.005,               # almost zero, very tight live-feel
        "kick_pattern": [0.0, 2.5],                 # 1 + "and-of-3" classic G-funk
        "snare_pattern": [1.0, 3.0],
        "hat_pattern": [0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.25, 3.5, 3.75],
        "ghost_snare_chance": 0.15,
        "ride_instead_of_hat": False,
        "open_hat_chance": 0.04,
        "velocity_range": (60, 120),                # hard hitting, narrow dynamic range
        "swing": 0.52,
        "fill_chance": 0.10,                        # rarely fills, very tight pocket
        "description": "G-funk tight live-feel pocket, sparse kicks on 1 and 'and-of-3', hard-hitting",
    },
    "dj_premier": {
        "role": "drums",
        "name": "DJ Premier",
        "instrument_hint": "MPC boom bap + scratch hits",
        "tempo_sweet_spot": 92,
        "tempo_min": 80,
        "tempo_max": 105,
        "pocket": "on_top",
        "pocket_offset_beats": 0.0,
        # Classic boom bap: kick on 1 and 3 with extra "and" of 2
        "kick_pattern": [0.0, 1.5, 2.0],
        "snare_pattern": [1.0, 3.0],
        # 8th note hat foundation
        "hat_pattern": [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5],
        "ghost_snare_chance": 0.05,                 # Premo doesn't ghost — he scratches
        "ride_instead_of_hat": False,
        "open_hat_chance": 0.0,
        "velocity_range": (55, 122),                # huge dynamic range — hits HARD
        "swing": 0.5,
        "fill_chance": 0.05,                        # almost never fills (scratches instead)
        "description": "Classic boom bap — hard kicks on 1 and 3, hard snares on 2 and 4, no fills",
    },
    "pete_rock": {
        "role": "drums",
        "name": "Pete Rock",
        "instrument_hint": "MPC jazzy boom bap (big snare reverb)",
        "tempo_sweet_spot": 88,
        "tempo_min": 75,
        "tempo_max": 105,
        "pocket": "behind",
        "pocket_offset_beats": 0.04,                # slight Soul Brother behind-feel
        "kick_pattern": [0.0, 0.75, 2.5],
        "snare_pattern": [1.0, 3.0],
        "hat_pattern": [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5],
        "ghost_snare_chance": 0.35,                 # jazz drum-style ghost rolls between backbeats
        "ride_instead_of_hat": False,
        "open_hat_chance": 0.08,
        "velocity_range": (45, 118),
        "swing": 0.55,
        "fill_chance": 0.20,                        # jazz-influenced fills more frequently
        "description": "Jazzy boom bap with ghost-snare rolls and slight behind-the-beat feel",
    },
    "metro_boomin": {
        "role": "drums",
        "name": "Metro Boomin",
        "instrument_hint": "modern trap kit (dark atmospheric)",
        "tempo_sweet_spot": 75,
        "tempo_min": 60,
        "tempo_max": 95,
        "pocket": "on_top",
        "pocket_offset_beats": 0.0,
        # Half-time trap: kick on 1 and "and-of-3"
        "kick_pattern": [0.0, 2.5],
        # Half-time snare: only on beat 3 (the big snare hit)
        "snare_pattern": [2.0],
        # 16th hats with rolls — Metro signature is the hat triplet/32nd rolls
        "hat_pattern": [0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.125, 3.25, 3.375, 3.5, 3.625, 3.75, 3.875],
        "ghost_snare_chance": 0.05,
        "ride_instead_of_hat": False,
        "open_hat_chance": 0.10,
        "velocity_range": (50, 122),
        "swing": 0.5,
        "fill_chance": 0.40,                        # frequent hat rolls (handled as fills)
        "description": "Modern half-time trap — kick on 1 + and-of-3, snare on 3 only, dense hat rolls",
    },
    "madlib": {
        "role": "drums",
        "name": "Madlib",
        "instrument_hint": "MPC dusty / off-kilter",
        "tempo_sweet_spot": 92,
        "tempo_min": 75,
        "tempo_max": 110,
        "pocket": "behind",
        "pocket_offset_beats": 0.07,                # dusty behind-the-beat
        # Irregular kicks landing in unexpected places
        "kick_pattern": [0.0, 1.25, 2.75],
        "snare_pattern": [1.0, 3.0],
        "hat_pattern": [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5],
        "ghost_snare_chance": 0.25,
        "ride_instead_of_hat": False,
        "open_hat_chance": 0.10,
        "velocity_range": (35, 115),                # very loose dynamic range
        "swing": 0.56,
        "fill_chance": 0.15,
        "description": "Dusty MPC off-kilter — irregular kicks, behind the beat, lo-fi dynamic looseness",
    },
}


# ===================== Public API helpers =====================

# ===================== Instrument suggestion hints =====================

# For each personality, ordered list of browser search queries that should
# surface a sonically appropriate instrument from Ableton's library. The
# loader (``load_instrument_for_personality``) tries each query in order
# and picks the highest-scored Instrument Rack / Device Preset.
#
# Hints are intentionally GENERIC ("tenor sax", "rhodes") so they match the
# vocabulary Ableton uses in its library naming. They're not URIs — that
# would tie us to a specific user's installed library.
BROWSER_HINTS: Dict[str, List[str]] = {
    # ===== solo (melodic / lead) =====
    "coltrane":         ["tenor sax", "saxophone", "sax", "brass", "wind"],
    "kenny_g":          ["soprano sax", "sax", "saxophone"],
    "oscar_peterson":   ["jazz piano", "grand piano", "acoustic piano", "piano"],
    "miles_davis":      ["trumpet", "muted trumpet", "horn", "brass"],
    "charlie_parker":   ["alto sax", "saxophone", "sax", "brass"],
    "wayne_shorter":    ["tenor sax", "soprano sax", "saxophone", "sax"],
    "pat_metheny":      ["jazz guitar", "guitar", "electric guitar", "clean guitar"],
    "stan_getz":        ["tenor sax", "sax", "saxophone"],
    "dizzy_gillespie":  ["trumpet", "horn", "brass"],

    # ===== comp (polyphonic chord instrument) =====
    "bill_evans":       ["rhodes", "electric piano daze", "electric piano", "jazz piano", "piano"],
    "mccoy_tyner":      ["jazz piano", "grand piano", "acoustic piano", "piano"],
    "herbie_hancock":   ["rhodes", "electric piano", "fender rhodes", "wurli"],
    "red_garland":      ["jazz piano", "grand piano", "acoustic piano", "piano"],
    "chick_corea":      ["rhodes", "electric piano", "fender rhodes", "jazz piano"],
    "wynton_kelly":     ["jazz piano", "grand piano", "blues piano", "piano"],

    # ===== bass =====
    "james_jamerson":   ["electric bass", "p bass", "fender bass", "motown bass", "bass"],
    "jaco_pastorius":   ["fretless bass", "fretless", "jaco", "bass"],
    "pino_palladino":   ["fretless bass", "fretless", "smooth bass", "bass"],
    "marcus_miller":    ["slap bass", "funk bass", "jazz bass", "bass"],
    "ray_brown":        ["upright bass", "double bass", "acoustic bass", "jazz bass", "bass"],
    "charles_mingus":   ["upright bass", "double bass", "acoustic bass", "bass"],

    # ===== drums (acoustic) =====
    "questlove":        ["drum rack", "acoustic kit", "vintage kit", "soul kit"],
    "tony_williams":    ["jazz kit", "drum rack", "brushes", "swing"],
    "vinnie_colaiuta":  ["drum rack", "fusion kit", "studio kit"],
    "j_dilla":          ["mpc", "hip hop kit", "lo-fi", "drum rack"],
    "elvin_jones":      ["jazz kit", "drum rack", "brushes"],
    "stewart_copeland": ["rock kit", "drum rack", "live kit"],

    # ===== drums (hip-hop producers) =====
    "timbaland":        ["drum rack", "808 kit", "hip hop kit", "mpc"],
    "dr_dre":           ["drum rack", "hip hop kit", "mpc", "808 kit", "g funk"],
    "dj_premier":       ["drum rack", "hip hop kit", "mpc", "boom bap", "vintage kit"],
    "pete_rock":        ["drum rack", "hip hop kit", "mpc", "boom bap"],
    "metro_boomin":     ["808 kit", "trap kit", "drum rack", "hip hop kit"],
    "madlib":           ["mpc", "drum rack", "lo-fi", "hip hop kit", "vintage"],
}


def list_personalities() -> List[Dict[str, Any]]:
    """Return a serializable summary of every available personality, grouped
    by role. Each entry has key/name/role/description/tempo_sweet_spot."""
    return [
        {
            "key": k,
            "name": p["name"],
            "role": p["role"],
            "instrument_hint": p.get("instrument_hint"),
            "tempo_sweet_spot": p.get("tempo_sweet_spot"),
            "tempo_range": [p.get("tempo_min"), p.get("tempo_max")],
            "description": p["description"],
        }
        for k, p in PERSONALITIES.items()
    ]


def _resolve(personality: str) -> Dict[str, Any]:
    key = personality.strip().lower().replace(" ", "_")
    if key not in PERSONALITIES:
        raise ValueError("Unknown personality '{0}'. Known: {1}".format(
            personality, sorted(PERSONALITIES.keys())))
    return PERSONALITIES[key]


def _tempo_warning(profile: Dict[str, Any], tempo: Optional[float]) -> Optional[str]:
    if tempo is None:
        return None
    lo, hi = profile.get("tempo_min"), profile.get("tempo_max")
    if lo is None or hi is None:
        return None
    if tempo < lo:
        return "tempo {0} is below {1}'s comfortable range ({2}-{3} BPM); generator will compensate but feel may be off".format(
            tempo, profile["name"], lo, hi)
    if tempo > hi:
        return "tempo {0} is above {1}'s comfortable range ({2}-{3} BPM); density will be reduced".format(
            tempo, profile["name"], lo, hi)
    return None


def _tempo_density_factor(profile: Dict[str, Any], tempo: Optional[float]) -> float:
    """Return a multiplier (>=1) to apply to the base step length when the
    tempo is much faster than the personality's sweet spot. Faster tempo →
    larger step (fewer notes per bar) so the part stays playable."""
    if tempo is None:
        return 1.0
    sweet = profile.get("tempo_sweet_spot")
    if not sweet:
        return 1.0
    ratio = tempo / sweet
    if ratio > 2.0:
        return 4.0
    if ratio > 1.5:
        return 2.0
    if ratio < 0.4:
        return 0.5
    return 1.0


def _tempo_swing_factor(profile: Dict[str, Any], tempo: Optional[float]) -> float:
    """At very fast tempos, swing tends to flatten out (8ths get too tight to
    swing). At very slow tempos, even un-swung styles can swing more."""
    if tempo is None:
        return profile.get("swing", 0.5)
    swing = profile.get("swing", 0.5)
    sweet = profile.get("tempo_sweet_spot", 120)
    if tempo > sweet * 1.5 and swing > 0.55:
        # straighten out
        return 0.5 + (swing - 0.5) * 0.5
    return swing


# ===================== Solo generator =====================

_DENSITY_TO_STEP: Dict[str, float] = {
    "low":         1.0,
    "medium":      0.5,
    "medium-high": 0.5,
    "high":        0.25,
}


def _resolve_scale_for_chord(profile: Dict[str, Any], chord_symbol: str) -> Tuple[int, List[int]]:
    quality = chord_quality(chord_symbol).lower()
    is_minor = quality.startswith("m") and not quality.startswith("maj")
    pool = profile.get("minor_scale_pool" if is_minor else "major_scale_pool", [])
    s = chord_symbol.strip()
    if len(s) >= 2 and s[1] in ("#", "b"):
        root_name = s[:2]
    else:
        root_name = s[:1]
    for mode in pool:
        try:
            return parse_scale("{0} {1}".format(root_name, mode.replace("_", " ")))
        except Exception:
            continue
    return parse_scale("{0} {1}".format(root_name, "minor" if is_minor else "major"))


def _phrase_arc_pitch_pref(arc: str, step_idx: int, n_steps: int) -> float:
    if n_steps <= 1:
        return 0.5
    progress = step_idx / float(n_steps - 1)
    if arc == "rising":
        return 0.4 + 0.5 * progress
    if arc == "ascend_then_descend":
        return 0.3 + 0.7 * (1.0 - abs(progress - 0.5) * 2.0)
    if arc == "arched":
        return 0.2 + 0.8 * (1.0 - (abs(progress - 0.5) * 2.0) ** 1.5)
    return 0.5  # static


def generate_personality_solo(
    personality: str,
    chord_progression: List[str],
    bars_per_chord: int = 1,
    tempo: Optional[float] = None,
    octave_offset: int = 0,
    seed: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Generate a melodic solo in the named personality's style."""
    profile = _resolve(personality)
    if profile["role"] != "solo":
        raise ValueError("personality '{0}' has role '{1}', not 'solo'".format(
            personality, profile["role"]))
    return _generate_solo_impl(profile, chord_progression, bars_per_chord, tempo, octave_offset, seed)


def _generate_solo_impl(
    profile: Dict[str, Any],
    chord_progression: List[str],
    bars_per_chord: int,
    tempo: Optional[float],
    octave_offset: int,
    seed: Optional[int],
) -> List[Dict[str, Any]]:
    rng = random.Random(seed)
    bar_beats = 4.0 * bars_per_chord
    base_step = _DENSITY_TO_STEP[profile["density"]]
    step = base_step * _tempo_density_factor(profile, tempo)
    swing = _tempo_swing_factor(profile, tempo)
    range_low, range_high = profile["range"]
    range_low += octave_offset * 12
    range_high += octave_offset * 12

    notes: List[Dict[str, Any]] = []
    prev_pitch: Optional[int] = None

    for bar_idx, chord_sym in enumerate(chord_progression):
        bar_start = bar_idx * bar_beats
        try:
            root_sem, intervals = _resolve_scale_for_chord(profile, chord_sym)
        except Exception:
            continue
        valid_pitches = scale_pitches_in_range(root_sem, intervals, range_low, range_high)
        if not valid_pitches:
            continue
        chord_tone_pcs = set(p % 12 for p in parse_chord(chord_sym, 4))

        n_steps = max(1, int(bar_beats / step))
        for step_idx in range(n_steps):
            beat_in_chord = step_idx * step
            t = bar_start + beat_in_chord
            # swing the off-beats
            if step <= 0.5 and step_idx % 2 == 1:
                t += (swing - 0.5) * step

            if rng.random() < profile["rest_chance"]:
                continue

            on_strong = (beat_in_chord % 1.0 < 0.001) and (int(beat_in_chord) % 2 == 0)
            on_beat = (beat_in_chord % 1.0 < 0.001)

            target_norm = _phrase_arc_pitch_pref(profile["phrase_arc"], step_idx, n_steps)
            target_pitch = range_low + (range_high - range_low) * target_norm
            window = (range_high - range_low) * 0.3
            arc_cands = [p for p in valid_pitches if abs(p - target_pitch) <= window] or valid_pitches

            if on_beat and rng.random() < profile["chord_tone_emphasis"]:
                chord_cands = [p for p in arc_cands if p % 12 in chord_tone_pcs]
                cands = chord_cands or arc_cands
            else:
                cands = arc_cands

            if prev_pitch is not None:
                cands_sorted = sorted(cands, key=lambda p: abs(p - prev_pitch))
                top_n = max(1, min(5, len(cands_sorted)))
                pitch = rng.choice(cands_sorted[:top_n])
            else:
                pitch = rng.choice(cands)

            if profile["use_chromatic"] and prev_pitch is not None and rng.random() < profile["chromatic_chance"]:
                if abs(pitch - prev_pitch) > 2:
                    direction = 1 if pitch > prev_pitch else -1
                    chromatic_pitch = pitch - direction
                    if range_low <= chromatic_pitch <= range_high:
                        notes.append({
                            "pitch": int(chromatic_pitch),
                            "start_time": float(t - step * 0.5),
                            "duration": float(step * 0.45),
                            "velocity": int((profile["velocity_range"][0] + profile["velocity_range"][1]) // 2),
                            "mute": False,
                        })

            if rng.random() < profile["octave_jump_chance"]:
                jumped = pitch + (12 if rng.random() < 0.5 else -12)
                if range_low <= jumped <= range_high:
                    pitch = jumped

            if profile.get("long_notes"):
                duration = step * (2.5 + rng.random() * 1.5)
            else:
                duration = step * 0.92

            vmin, vmax = profile["velocity_range"]
            v_range = vmax - vmin
            if on_strong:
                velocity = vmin + int(v_range * (0.65 + rng.random() * 0.35))
            else:
                velocity = vmin + int(v_range * (0.30 + rng.random() * 0.50))

            notes.append({
                "pitch": int(pitch),
                "start_time": float(t),
                "duration": float(duration),
                "velocity": int(max(1, min(127, velocity))),
                "mute": False,
            })
            prev_pitch = int(pitch)

    return notes


# ===================== Comping generator =====================

def _voicing_for_chord(profile: Dict[str, Any], chord_symbol: str) -> List[int]:
    """Build a voicing for the chord according to the comp profile's voicing_style."""
    style = profile["voicing_style"]
    voice_count = profile["voice_count"]
    use_ext = profile.get("use_extensions", False)
    range_lo, range_hi = profile["voicing_range"]

    chord_pitches_root4 = parse_chord(chord_symbol, 4)
    chord_pcs = [p % 12 for p in chord_pitches_root4]
    root_pc = chord_pcs[0]
    quality = chord_quality(chord_symbol).lower()
    is_minor = quality.startswith("m") and not quality.startswith("maj")

    voicing: List[int] = []

    if style == "rootless":
        # Drop the root, build from 3rd, 5th, 7th, 9th, 13th in the voicing range
        # 3rd: minor or major
        third = root_pc + (3 if is_minor else 4)
        fifth = root_pc + 7
        # 7th: dominant by default unless quality is maj7
        if "maj7" in quality or "M7" == quality.upper():
            seventh = root_pc + 11
        else:
            seventh = root_pc + 10
        ninth = root_pc + 14
        thirteenth = root_pc + 21
        wanted_pcs = [third, seventh]
        if voice_count >= 3:
            if use_ext:
                wanted_pcs.append(ninth)
            else:
                wanted_pcs.append(fifth)
        if voice_count >= 4:
            if use_ext:
                wanted_pcs.append(thirteenth)
            else:
                wanted_pcs.append(fifth + 12)
        # Place pitches in range, lowest near range_lo
        target = range_lo + 4
        for pc in wanted_pcs:
            pc = pc % 12
            # find octave for pitch closest to target
            best = pc
            while best < range_lo:
                best += 12
            while best > range_hi:
                best -= 12
            # bias upward from target
            if target - best > 6:
                best += 12 if best + 12 <= range_hi else 0
            voicing.append(best)
            target = best + 3
    elif style == "quartal":
        # Stack 4ths starting from a chord-tone root in the lower part of the range
        start = root_pc
        # Move start into voicing range
        candidate = start
        while candidate < range_lo:
            candidate += 12
        for i in range(voice_count):
            v = candidate + i * 5  # perfect 4th = 5 semitones
            if v <= range_hi:
                voicing.append(v)
    elif style == "shell":
        # 1, 3, 7 — minimal Bud Powell-style
        third = root_pc + (3 if is_minor else 4)
        seventh = root_pc + (10 if "maj7" not in quality else 11)
        for pc in [root_pc, third, seventh][:voice_count]:
            v = pc
            while v < range_lo:
                v += 12
            voicing.append(v)
    else:  # "block"
        # Closed-position triad/7th in the voicing range
        for off in CHORDS.get(quality, [0, 4, 7])[:voice_count]:
            v = root_pc + off
            while v < range_lo:
                v += 12
            voicing.append(v)

    return sorted(set(voicing))


def generate_personality_comping(
    personality: str,
    chord_progression: List[str],
    bars_per_chord: int = 1,
    tempo: Optional[float] = None,
    octave_offset: int = 0,
    seed: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Generate chord voicings (comping) in the named personality's style."""
    profile = _resolve(personality)
    if profile["role"] != "comp":
        raise ValueError("personality '{0}' has role '{1}', not 'comp'".format(
            personality, profile["role"]))
    return _generate_comping_impl(profile, chord_progression, bars_per_chord, tempo, octave_offset, seed)


def _generate_comping_impl(
    profile: Dict[str, Any],
    chord_progression: List[str],
    bars_per_chord: int,
    tempo: Optional[float],
    octave_offset: int,
    seed: Optional[int],
) -> List[Dict[str, Any]]:
    rng = random.Random(seed)
    bar_beats = 4.0 * bars_per_chord
    swing = _tempo_swing_factor(profile, tempo)
    rhythm = profile["rhythm_pattern"]
    velocity_lo, velocity_hi = profile["velocity_range"]
    notes: List[Dict[str, Any]] = []

    for bar_idx, chord_sym in enumerate(chord_progression):
        bar_start = bar_idx * bar_beats
        voicing = _voicing_for_chord(profile, chord_sym)
        voicing = [p + octave_offset * 12 for p in voicing]
        for offset, length in rhythm:
            # swing off-beat 8ths
            t = bar_start + offset
            if (offset * 2) % 1.0 > 0.001 and offset % 1.0 != 0.0:
                t += (swing - 0.5) * 0.5
            # voice the chord with slight humanization
            base_v = velocity_lo + int((velocity_hi - velocity_lo) * (0.55 + rng.random() * 0.4))
            for i, pitch in enumerate(voicing):
                # tiny offset across the voicing for natural roll
                roll_offset = 0.005 * i
                vel = max(1, min(127, base_v + rng.randint(-8, 8)))
                notes.append({
                    "pitch": int(pitch),
                    "start_time": float(t + roll_offset),
                    "duration": float(length * 0.95),
                    "velocity": int(vel),
                    "mute": False,
                })
    return notes


# ===================== Bass generator =====================

def generate_personality_bass(
    personality: str,
    chord_progression: List[str],
    bars_per_chord: int = 1,
    tempo: Optional[float] = None,
    octave_offset: int = 0,
    seed: Optional[int] = None,
) -> List[Dict[str, Any]]:
    profile = _resolve(personality)
    if profile["role"] != "bass":
        raise ValueError("personality '{0}' has role '{1}', not 'bass'".format(
            personality, profile["role"]))
    return _generate_bass_impl(profile, chord_progression, bars_per_chord, tempo, octave_offset, seed)


def _bias_pitches_by_register(pitches: List[int], range_lo: int, range_hi: int, preference: str) -> List[int]:
    """Restrict the candidate pitch list to a portion of the range based on
    the personality's register_preference. ``low`` = bottom third,
    ``mid`` = middle third, ``high`` = top half, ``wide`` = use everything."""
    if not pitches or preference == "wide":
        return pitches
    span = range_hi - range_lo
    if preference == "low":
        cutoff = range_lo + span * 0.4
        biased = [p for p in pitches if p <= cutoff]
    elif preference == "mid":
        lo_cut = range_lo + span * 0.25
        hi_cut = range_lo + span * 0.7
        biased = [p for p in pitches if lo_cut <= p <= hi_cut]
    elif preference == "high":
        cutoff = range_lo + span * 0.5
        biased = [p for p in pitches if p >= cutoff]
    else:
        biased = pitches
    return biased or pitches


def _generate_bass_impl(
    profile: Dict[str, Any],
    chord_progression: List[str],
    bars_per_chord: int,
    tempo: Optional[float],
    octave_offset: int,
    seed: Optional[int],
) -> List[Dict[str, Any]]:
    rng = random.Random(seed)
    bar_beats = 4.0 * bars_per_chord
    swing = _tempo_swing_factor(profile, tempo)
    range_lo, range_hi = profile["range"]
    range_lo += octave_offset * 12
    range_hi += octave_offset * 12
    velocity_lo, velocity_hi = profile["velocity_range"]
    density = profile["walking_density"]
    syncopation = profile["syncopation"]
    ghost_chance = profile["ghost_note_chance"]
    chord_tone_pri = profile["chord_tone_priority"]
    register_pref = profile.get("register_preference", "wide")

    # Walking step depends on density
    if density == "low":
        step = 1.0      # mostly quarter notes, sparse
        rest_chance = 0.4
    elif density == "medium":
        step = 0.5
        rest_chance = 0.15
    else:
        step = 0.5      # 8ths
        rest_chance = 0.05

    notes: List[Dict[str, Any]] = []
    prev_pitch: Optional[int] = None

    for bar_idx, chord_sym in enumerate(chord_progression):
        bar_start = bar_idx * bar_beats
        try:
            quality = chord_quality(chord_sym).lower()
            is_minor = quality.startswith("m") and not quality.startswith("maj")
            if len(chord_sym) >= 2 and chord_sym[1] in ("#", "b"):
                root_name = chord_sym[:2]
            else:
                root_name = chord_sym[:1]
            root_sem, intervals = parse_scale("{0} {1}".format(
                root_name, "minor" if is_minor else "major"))
        except Exception:
            continue
        valid_pitches_full = scale_pitches_in_range(root_sem, intervals, range_lo, range_hi)
        if not valid_pitches_full:
            continue
        # Apply the personality's register preference to bias note selection
        valid_pitches = _bias_pitches_by_register(valid_pitches_full, range_lo, range_hi, register_pref)
        chord_pitches_all = [p for p in scale_pitches_in_range(root_sem, [0, 4 if not is_minor else 3, 7], range_lo, range_hi)]
        chord_pitches = _bias_pitches_by_register(chord_pitches_all, range_lo, range_hi, register_pref)
        if not chord_pitches:
            chord_pitches = chord_pitches_all or valid_pitches_full[:3]
        # Root pitch — for high-register preference, use the higher root octave
        roots = [p for p in valid_pitches_full if p % 12 == root_sem]
        if register_pref == "low":
            root_pitch = min(roots) if roots else min(valid_pitches_full)
        elif register_pref == "high":
            roots_in_pref = [p for p in roots if p in valid_pitches] or roots
            root_pitch = max(roots_in_pref) if roots_in_pref else max(valid_pitches)
        else:
            roots_in_pref = [p for p in roots if p in valid_pitches] or roots
            root_pitch = min(roots_in_pref) if roots_in_pref else min(valid_pitches)

        n_steps = max(1, int(bar_beats / step))
        for step_idx in range(n_steps):
            beat_in_chord = step_idx * step
            t = bar_start + beat_in_chord
            # swing
            if step == 0.5 and step_idx % 2 == 1:
                t += (swing - 0.5) * step
            # syncopation: shift ON-beats slightly
            if syncopation > 0 and step_idx % 2 == 0 and rng.random() < syncopation * 0.3:
                t += step * 0.25

            # rest
            if rng.random() < rest_chance:
                continue

            on_one = beat_in_chord < 0.01
            on_strong = on_one or (abs(beat_in_chord - 2.0) < 0.01)

            # Pick the pitch
            if on_one:
                pitch = root_pitch
            elif on_strong and rng.random() < chord_tone_pri:
                pitch = rng.choice(chord_pitches)
            elif rng.random() < chord_tone_pri:
                pitch = rng.choice(chord_pitches)
            else:
                # Walking: pick a scale tone close to previous
                if prev_pitch is not None:
                    near = sorted(valid_pitches, key=lambda p: abs(p - prev_pitch))[:3]
                    pitch = rng.choice(near)
                else:
                    pitch = rng.choice(valid_pitches)

            # Ghost note?
            is_ghost = rng.random() < ghost_chance
            vel_pos = 0.85 if on_strong else (0.15 if is_ghost else 0.55)
            velocity = velocity_lo + int((velocity_hi - velocity_lo) * (vel_pos + (rng.random() - 0.5) * 0.1))

            notes.append({
                "pitch": int(pitch),
                "start_time": float(t),
                "duration": float(step * 0.92),
                "velocity": int(max(1, min(127, velocity))),
                "mute": False,
            })
            prev_pitch = int(pitch)

    return notes


# ===================== Drums generator =====================

GM_DRUMS = {
    "kick":     36,
    "snare":    38,
    "hat":      42,
    "open_hat": 46,
    "ride":     51,
    "clap":     39,
    "tom_low":  45,
    "tom_mid":  48,
    "tom_hi":   50,
    "crash":    49,
}


def generate_personality_drums(
    personality: str,
    bar_count: int = 4,
    tempo: Optional[float] = None,
    seed: Optional[int] = None,
) -> List[Dict[str, Any]]:
    profile = _resolve(personality)
    if profile["role"] != "drums":
        raise ValueError("personality '{0}' has role '{1}', not 'drums'".format(
            personality, profile["role"]))
    return _generate_drums_impl(profile, bar_count, tempo, seed)


def _generate_drums_impl(
    profile: Dict[str, Any],
    bar_count: int,
    tempo: Optional[float],
    seed: Optional[int],
) -> List[Dict[str, Any]]:
    rng = random.Random(seed)
    swing = _tempo_swing_factor(profile, tempo)
    pocket_offset = profile.get("pocket_offset_beats", 0.0)
    velocity_lo, velocity_hi = profile["velocity_range"]
    kick = GM_DRUMS["kick"]
    snare = GM_DRUMS["snare"]
    hat = GM_DRUMS["ride"] if profile.get("ride_instead_of_hat") else GM_DRUMS["hat"]
    open_hat = GM_DRUMS["open_hat"]
    fill_chance = profile.get("fill_chance", 0.0)
    ghost_chance = profile.get("ghost_snare_chance", 0.0)
    open_hat_chance = profile.get("open_hat_chance", 0.0)

    notes: List[Dict[str, Any]] = []

    def add(pitch: int, t: float, vel: int) -> None:
        notes.append({
            "pitch": int(pitch),
            "start_time": float(t + pocket_offset),
            "duration": 0.125,
            "velocity": int(max(1, min(127, vel))),
            "mute": False,
        })

    for bar in range(bar_count):
        b = bar * 4.0
        is_last_bar = (bar == bar_count - 1)
        do_fill = is_last_bar and rng.random() < fill_chance

        # Kicks
        for k in profile["kick_pattern"]:
            add(kick, b + k, velocity_lo + int((velocity_hi - velocity_lo) * (0.7 + rng.random() * 0.3)))

        # Snares (backbeat)
        for s in profile["snare_pattern"]:
            add(snare, b + s, velocity_lo + int((velocity_hi - velocity_lo) * (0.75 + rng.random() * 0.25)))

        # Hats / ride
        for h in profile["hat_pattern"]:
            t = b + h
            # swing
            if h % 1.0 != 0.0:
                t += (swing - 0.5) * 0.5
            v = velocity_lo + int((velocity_hi - velocity_lo) * (0.45 + rng.random() * 0.25))
            # accent on the downbeats
            if h % 1.0 < 0.001:
                v += 10
            # open hat substitution near beat 4 'and'
            if open_hat_chance > 0 and abs(h - 3.5) < 0.01 and rng.random() < open_hat_chance:
                add(open_hat, t, v)
            else:
                add(hat, t, v)

        # Ghost snares scattered between backbeats
        if ghost_chance > 0:
            for ghost_t in [0.5, 1.5, 2.5, 3.25, 3.75]:
                if rng.random() < ghost_chance:
                    add(snare, b + ghost_t, velocity_lo + int((velocity_hi - velocity_lo) * 0.15))

        # Fill on the last bar
        if do_fill:
            for ft in [3.0, 3.25, 3.5, 3.75]:
                add(GM_DRUMS["tom_mid"] if rng.random() < 0.5 else snare, b + ft,
                    velocity_lo + int((velocity_hi - velocity_lo) * (0.7 + rng.random() * 0.3)))

    return notes


# ===================== Unified dispatcher + blending =====================

def generate_personality_part(
    personality: str,
    chord_progression: List[str],
    bars_per_chord: int = 1,
    tempo: Optional[float] = None,
    octave_offset: int = 0,
    seed: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Dispatch to the right generator based on personality role.

    Returns (notes, warning_or_none). Warnings are emitted when the tempo
    is outside the personality's comfortable range.
    """
    profile = _resolve(personality)
    warning = _tempo_warning(profile, tempo)
    role = profile["role"]
    if role == "solo":
        notes = _generate_solo_impl(profile, chord_progression, bars_per_chord, tempo, octave_offset, seed)
    elif role == "comp":
        notes = _generate_comping_impl(profile, chord_progression, bars_per_chord, tempo, octave_offset, seed)
    elif role == "bass":
        notes = _generate_bass_impl(profile, chord_progression, bars_per_chord, tempo, octave_offset, seed)
    elif role == "drums":
        bar_count = max(1, len(chord_progression) * bars_per_chord)
        notes = _generate_drums_impl(profile, bar_count, tempo, seed)
    else:
        raise ValueError("Unknown role: " + role)
    return notes, warning


def blend_personalities(personality_a: str, personality_b: str, ratio: float = 0.5) -> Dict[str, Any]:
    """Blend two personalities with the given ratio (0.0=all A, 1.0=all B).

    Numeric fields are interpolated; range tuples are interpolated bound-by-
    bound; categorical pools (scale_pool etc) are unioned with A entries first.
    Both personalities must share the same role.
    """
    a = _resolve(personality_a)
    b = _resolve(personality_b)
    if a["role"] != b["role"]:
        raise ValueError("Cannot blend personalities of different roles ({0} vs {1})".format(
            a["role"], b["role"]))
    ratio = max(0.0, min(1.0, ratio))
    blended: Dict[str, Any] = {"role": a["role"]}
    blended["name"] = "{0} × {1} ({2:.0%})".format(a["name"], b["name"], 1 - ratio)
    blended["instrument_hint"] = a.get("instrument_hint")
    blended["description"] = "Blend of {0} and {1}".format(a["name"], b["name"])

    keys = set(a.keys()) | set(b.keys())
    for k in keys:
        if k in ("name", "role", "description", "instrument_hint"):
            continue
        va, vb = a.get(k), b.get(k)
        if va is None:
            blended[k] = vb
            continue
        if vb is None:
            blended[k] = va
            continue
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            blended[k] = va * (1 - ratio) + vb * ratio
            if isinstance(va, int) and isinstance(vb, int):
                blended[k] = int(round(blended[k]))
        elif isinstance(va, tuple) and isinstance(vb, tuple) and len(va) == len(vb) == 2:
            blended[k] = (
                va[0] * (1 - ratio) + vb[0] * ratio,
                va[1] * (1 - ratio) + vb[1] * ratio,
            )
            if isinstance(va[0], int):
                blended[k] = (int(round(blended[k][0])), int(round(blended[k][1])))
        elif isinstance(va, list) and isinstance(vb, list):
            # Union, A entries first
            seen = set()
            merged = []
            for x in va + vb:
                marker = tuple(x) if isinstance(x, list) else x
                if marker not in seen:
                    seen.add(marker)
                    merged.append(x)
            blended[k] = merged
        elif isinstance(va, bool) and isinstance(vb, bool):
            blended[k] = va if ratio < 0.5 else vb
        elif isinstance(va, str) and isinstance(vb, str):
            blended[k] = va if ratio < 0.5 else vb
        else:
            blended[k] = va if ratio < 0.5 else vb
    return blended


def generate_blended_solo(
    personality_a: str,
    personality_b: str,
    ratio: float,
    chord_progression: List[str],
    bars_per_chord: int = 1,
    tempo: Optional[float] = None,
    octave_offset: int = 0,
    seed: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Generate a solo from a blended profile (currently solo-only)."""
    profile = blend_personalities(personality_a, personality_b, ratio)
    if profile["role"] != "solo":
        raise ValueError("Blended profile is role '{0}', expected 'solo'".format(profile["role"]))
    return _generate_solo_impl(profile, chord_progression, bars_per_chord, tempo, octave_offset, seed)
