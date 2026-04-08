"""Music theory helpers used by the MCP server's Tier 4 tools.

Pure-Python, zero MCP dependencies, so it can be imported by both
``server.py`` and standalone test scripts (e.g. ``scripts/make_pop_trap_song.py``).
"""
from __future__ import annotations
from typing import Dict, List, Tuple


# ===================== Notes / scales / chords =====================

NOTE_TO_SEMITONE: Dict[str, int] = {
    "C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3,
    "E": 4, "Fb": 4, "E#": 5, "F": 5, "F#": 6, "Gb": 6,
    "G": 7, "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10,
    "B": 11, "Cb": 11, "B#": 0,
}

SCALES: Dict[str, List[int]] = {
    "major":            [0, 2, 4, 5, 7, 9, 11],
    "minor":            [0, 2, 3, 5, 7, 8, 10],   # natural minor
    "harmonic_minor":   [0, 2, 3, 5, 7, 8, 11],
    "melodic_minor":    [0, 2, 3, 5, 7, 9, 11],
    "dorian":           [0, 2, 3, 5, 7, 9, 10],
    "phrygian":         [0, 1, 3, 5, 7, 8, 10],
    "lydian":           [0, 2, 4, 6, 7, 9, 11],
    "mixolydian":       [0, 2, 4, 5, 7, 9, 10],
    "locrian":          [0, 1, 3, 5, 6, 8, 10],
    "pentatonic":       [0, 2, 4, 7, 9],           # major pentatonic
    "minor_pentatonic": [0, 3, 5, 7, 10],
    "blues":            [0, 3, 5, 6, 7, 10],
    "bebop":            [0, 2, 4, 5, 7, 8, 9, 11], # major bebop (added b6)
    "altered":          [0, 1, 3, 4, 6, 8, 10],    # Coltrane-friendly
    "chromatic":        [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
}

# Chord intervals relative to the root, keyed by quality suffix.
CHORDS: Dict[str, List[int]] = {
    "":      [0, 4, 7],          # major triad
    "maj":   [0, 4, 7],
    "M":     [0, 4, 7],
    "m":     [0, 3, 7],          # minor triad
    "min":   [0, 3, 7],
    "dim":   [0, 3, 6],
    "aug":   [0, 4, 8],
    "+":     [0, 4, 8],
    "sus2":  [0, 2, 7],
    "sus4":  [0, 5, 7],
    "5":     [0, 7],              # power chord
    "6":     [0, 4, 7, 9],
    "m6":    [0, 3, 7, 9],
    "7":     [0, 4, 7, 10],       # dominant 7
    "maj7":  [0, 4, 7, 11],
    "M7":    [0, 4, 7, 11],
    "m7":    [0, 3, 7, 10],
    "min7":  [0, 3, 7, 10],
    "dim7":  [0, 3, 6, 9],
    "m7b5":  [0, 3, 6, 10],       # half-diminished
    "9":     [0, 4, 7, 10, 14],
    "maj9":  [0, 4, 7, 11, 14],
    "m9":    [0, 3, 7, 10, 14],
    "11":    [0, 4, 7, 10, 14, 17],
    "13":    [0, 4, 7, 10, 14, 17, 21],
    "add9":  [0, 4, 7, 14],
    "add2":  [0, 2, 4, 7],
}


def parse_chord(symbol: str, octave: int = 4) -> List[int]:
    """Parse a chord symbol (e.g. 'Cm7', 'F#maj7', 'Bb13') into MIDI pitches.

    Octave 4 = C4 = MIDI 60 (middle C).
    """
    if not symbol:
        raise ValueError("empty chord symbol")
    s = symbol.strip()
    if len(s) >= 2 and s[1] in ("#", "b"):
        root_name = s[:2]
        rest = s[2:]
    else:
        root_name = s[:1]
        rest = s[1:]
    if root_name not in NOTE_TO_SEMITONE:
        raise ValueError("Unknown chord root: " + root_name)
    if rest not in CHORDS:
        raise ValueError("Unknown chord quality: '{0}' in '{1}'".format(rest, symbol))
    base_pitch = (octave + 1) * 12 + NOTE_TO_SEMITONE[root_name]
    return [base_pitch + iv for iv in CHORDS[rest]]


def chord_root_pitch(symbol: str, octave: int = 2) -> int:
    """Return just the root MIDI pitch of a chord symbol at the given octave."""
    s = symbol.strip()
    if len(s) >= 2 and s[1] in ("#", "b"):
        root_name = s[:2]
    else:
        root_name = s[:1]
    if root_name not in NOTE_TO_SEMITONE:
        raise ValueError("Unknown chord root: " + root_name)
    return (octave + 1) * 12 + NOTE_TO_SEMITONE[root_name]


def chord_quality(symbol: str) -> str:
    """Extract just the quality suffix from a chord symbol (the part after the root)."""
    s = symbol.strip()
    if len(s) >= 2 and s[1] in ("#", "b"):
        return s[2:]
    return s[1:]


def parse_scale(name: str) -> Tuple[int, List[int]]:
    """Parse a scale spec like 'C minor' or 'F# dorian' into (root_semitone, intervals)."""
    parts = name.strip().split()
    if len(parts) < 2:
        raise ValueError("scale must be 'ROOT QUALITY', e.g. 'C minor'")
    root_name = parts[0]
    quality = "_".join(parts[1:]).lower()
    if root_name not in NOTE_TO_SEMITONE:
        raise ValueError("Unknown scale root: " + root_name)
    if quality not in SCALES:
        raise ValueError("Unknown scale: " + quality)
    return NOTE_TO_SEMITONE[root_name], SCALES[quality]


def scale_pitches_in_range(root_semitone: int, intervals: List[int],
                           min_pitch: int, max_pitch: int) -> List[int]:
    """All pitches in the given scale that fall inside [min_pitch, max_pitch]."""
    out: List[int] = []
    # Walk every octave that could possibly contain notes in range
    start_octave = (min_pitch // 12) - 1
    end_octave = (max_pitch // 12) + 1
    for octave in range(start_octave, end_octave + 1):
        base = octave * 12 + root_semitone
        for iv in intervals:
            p = base + iv
            if min_pitch <= p <= max_pitch:
                out.append(p)
    return sorted(set(out))


# ===================== Rhythm / drum primitives =====================

RHYTHM_BEATS: Dict[str, float] = {
    "whole":     4.0,
    "half":      2.0,
    "quarter":   1.0,
    "eighth":    0.5,
    "sixteenth": 0.25,
}

GRID_BEATS: Dict[str, float] = {
    "1/4":  1.0,
    "1/8":  0.5,
    "1/16": 0.25,
    "1/32": 0.125,
}

# Drum patterns: list of (drum_key, [start_beats]) entries. drum_key is a
# logical name resolved against the kit_map (kick/snare/hat/open_hat/clap/tom).
DRUM_PATTERNS: Dict[str, List[Tuple[str, List[float]]]] = {
    "four_on_floor": [
        ("kick",  [0.0, 1.0, 2.0, 3.0]),
        ("snare", [1.0, 3.0]),
        ("hat",   [0.5, 1.5, 2.5, 3.5]),
    ],
    "trap": [
        ("kick",  [0.0, 1.5, 2.0, 3.5]),
        ("snare", [2.0]),
        ("hat",   [0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.625, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.25, 3.5, 3.75]),
    ],
    "breakbeat": [
        ("kick",  [0.0, 0.75, 2.5]),
        ("snare", [1.0, 3.0, 3.5]),
        ("hat",   [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5]),
    ],
    "boom_bap": [
        ("kick",  [0.0, 2.5]),
        ("snare", [1.0, 3.0]),
        ("hat",   [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5]),
    ],
}

DEFAULT_KIT_MAP: Dict[str, int] = {
    "kick":     36,  # C1
    "snare":    38,  # D1
    "hat":      42,  # F#1 (closed hat)
    "open_hat": 46,  # A#1
    "clap":     39,  # D#1
    "tom":      45,  # A1
}
