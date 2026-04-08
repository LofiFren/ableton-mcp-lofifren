"""Build a 'pop classic with trap bass' song in Ableton via the AbletonMCP socket.

Section structure (each scene = 1 row of clips, each clip = 4 bars = 8 sec @ 120 BPM):
    Scene 0  Intro          chords + sparse hat
    Scene 1  Verse          chords + drums + 808 bass
    Scene 2  Pre-chorus     chords + drums + 808 bass (busier)
    Scene 3  Chorus         chords + drums + 808 bass + lead
    Scene 4  Verse 2        same as Verse
    Scene 5  Final chorus   same as Chorus

Key: C minor.
Progression: Cm — Ab — Eb — Bb  (i — VI — III — VII)

After building, the script tries `bounce_session_to_arrangement` to render the
sequence [0,1,1,2,3,3,4,5,5] onto the arrangement timeline (~72 sec). If the
Live API doesn't expose duplicate_clip_to_arrangement, we just leave the
session-view scenes for the user to fire manually.
"""
from __future__ import annotations
import json
import sys
from typing import Dict, List, Tuple

sys.path.insert(0, "scripts")
from ableton_client import AbletonClient


# ===================== inline music theory =====================

NOTE_TO_SEMITONE = {
    "C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3,
    "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8,
    "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11,
}

CHORDS = {
    "":   [0, 4, 7],   "m":  [0, 3, 7],
    "7":  [0, 4, 7, 10], "maj7": [0, 4, 7, 11], "m7": [0, 3, 7, 10],
}


def parse_chord(symbol: str, octave: int = 4) -> List[int]:
    if len(symbol) >= 2 and symbol[1] in ("#", "b"):
        root, quality = symbol[:2], symbol[2:]
    else:
        root, quality = symbol[:1], symbol[1:]
    base = (octave + 1) * 12 + NOTE_TO_SEMITONE[root]
    return [base + iv for iv in CHORDS[quality]]


def chord_root_pitch(symbol: str, octave: int = 2) -> int:
    """Root note in a low octave for the 808 bass."""
    if len(symbol) >= 2 and symbol[1] in ("#", "b"):
        root = symbol[:2]
    else:
        root = symbol[:1]
    return (octave + 1) * 12 + NOTE_TO_SEMITONE[root]


# ===================== song shape =====================

PROGRESSION = ["Cm", "Ab", "Eb", "Bb"]   # 4 bars, 1 bar per chord
BAR_BEATS = 4.0
CLIP_LENGTH_BEATS = BAR_BEATS * 4  # each clip is 4 bars

# Scenes we will populate. Each entry: scene index → which "section type"
SCENES = [
    ("Intro",        "intro"),
    ("Verse",        "verse"),
    ("Pre-Chorus",   "pre"),
    ("Chorus",       "chorus"),
    ("Verse 2",      "verse"),
    ("Final Chorus", "chorus"),
]
# Bounce order on the timeline: indices into SCENES, repeated for length.
# 9 scenes * 4 bars = 36 bars * 2 sec = 72 seconds at 120 BPM.
BOUNCE_ORDER = [0, 1, 1, 2, 3, 3, 4, 5, 5]


# ===================== note builders =====================

def chord_clip_notes(progression: List[str], octave: int = 4, velocity: int = 80) -> List[Dict]:
    """Whole-bar chord stabs across the progression."""
    notes = []
    for i, sym in enumerate(progression):
        for pitch in parse_chord(sym, octave):
            notes.append({
                "pitch": pitch,
                "start_time": i * BAR_BEATS,
                "duration": BAR_BEATS * 0.95,  # leave a tiny gap
                "velocity": velocity,
                "mute": False,
            })
    return notes


def trap_bass_notes(progression: List[str], octave: int = 1, velocity: int = 110) -> List[Dict]:
    """Trap-style 808 bass: long root on beat 1, short rhythmic hit on the
    'and of 3' for each bar."""
    notes = []
    for i, sym in enumerate(progression):
        root = chord_root_pitch(sym, octave)
        bar = i * BAR_BEATS
        notes.append({"pitch": root, "start_time": bar + 0.0, "duration": 2.0, "velocity": velocity, "mute": False})
        notes.append({"pitch": root, "start_time": bar + 2.5, "duration": 0.5, "velocity": velocity - 10, "mute": False})
    return notes


# Drum kit: GM mapping (works for most Ableton drum racks)
KICK, SNARE, CHAT, OHAT = 36, 38, 42, 46


def drum_pattern_intro_hat() -> List[Dict]:
    """Just sparse closed hats on every beat for the intro."""
    notes = []
    for bar in range(4):
        for beat in (0.5, 1.5, 2.5, 3.5):
            notes.append({
                "pitch": CHAT, "start_time": bar * 4 + beat, "duration": 0.125,
                "velocity": 70, "mute": False,
            })
    return notes


def drum_pattern_verse() -> List[Dict]:
    """Pop verse: kick on 1+3, snare on 2+4, closed hats on the 8ths."""
    notes = []
    for bar in range(4):
        b = bar * 4
        # kick
        for t in (0.0, 2.0):
            notes.append({"pitch": KICK, "start_time": b + t, "duration": 0.25, "velocity": 110, "mute": False})
        # snare
        for t in (1.0, 3.0):
            notes.append({"pitch": SNARE, "start_time": b + t, "duration": 0.25, "velocity": 105, "mute": False})
        # closed hats every 8th
        for t in (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5):
            notes.append({"pitch": CHAT, "start_time": b + t, "duration": 0.125, "velocity": 75, "mute": False})
    return notes


def drum_pattern_pre() -> List[Dict]:
    """Pre-chorus build: same as verse + extra snare hits ramping toward end."""
    notes = drum_pattern_verse()
    # Add extra snare rolls in the last bar (bar index 3) to build tension
    last_bar = 3 * 4
    for t in (3.0, 3.25, 3.5, 3.75):
        notes.append({"pitch": SNARE, "start_time": last_bar + t, "duration": 0.125, "velocity": 95, "mute": False})
    return notes


def drum_pattern_chorus() -> List[Dict]:
    """Chorus: four-on-the-floor kick, snare on 2+4, busier hats with open hat accents."""
    notes = []
    for bar in range(4):
        b = bar * 4
        # four-on-the-floor kick
        for t in (0.0, 1.0, 2.0, 3.0):
            notes.append({"pitch": KICK, "start_time": b + t, "duration": 0.25, "velocity": 115, "mute": False})
        # snare
        for t in (1.0, 3.0):
            notes.append({"pitch": SNARE, "start_time": b + t, "duration": 0.25, "velocity": 110, "mute": False})
        # 16th hats
        for i in range(16):
            t = i * 0.25
            notes.append({"pitch": CHAT, "start_time": b + t, "duration": 0.1, "velocity": 70 + (15 if i % 4 == 0 else 0), "mute": False})
        # open hat on the 'and' of 4
        notes.append({"pitch": OHAT, "start_time": b + 3.5, "duration": 0.5, "velocity": 90, "mute": False})
    return notes


def lead_chorus_notes(progression: List[str], velocity: int = 100) -> List[Dict]:
    """A simple memorable lead phrase that follows the chord changes.
    Built around C minor pentatonic but anchored on each chord's root/3rd/5th."""
    # Each bar: a 4-note motif using chord tones from the current chord
    notes = []
    for i, sym in enumerate(progression):
        chord = parse_chord(sym, octave=5)  # one octave above the chord track
        bar = i * BAR_BEATS
        # Simple call-and-response: 5 - 3 - 1 - 5 (root motif)
        if len(chord) >= 3:
            phrase = [chord[2], chord[1], chord[0], chord[2]]
        else:
            phrase = [chord[0]] * 4
        for j, pitch in enumerate(phrase):
            notes.append({
                "pitch": pitch,
                "start_time": bar + j * 1.0,
                "duration": 0.9,
                "velocity": velocity,
                "mute": False,
            })
    return notes


SECTION_BUILDERS = {
    # (drums?, bass?, chords?, lead?) → which content goes in which track
    "intro":  {"drums": drum_pattern_intro_hat,  "bass": None,                "chords": lambda: chord_clip_notes(PROGRESSION, octave=4, velocity=70), "lead": None},
    "verse":  {"drums": drum_pattern_verse,      "bass": lambda: trap_bass_notes(PROGRESSION),       "chords": lambda: chord_clip_notes(PROGRESSION, octave=4, velocity=80), "lead": None},
    "pre":    {"drums": drum_pattern_pre,        "bass": lambda: trap_bass_notes(PROGRESSION),       "chords": lambda: chord_clip_notes(PROGRESSION, octave=4, velocity=85), "lead": None},
    "chorus": {"drums": drum_pattern_chorus,     "bass": lambda: trap_bass_notes(PROGRESSION),       "chords": lambda: chord_clip_notes(PROGRESSION, octave=4, velocity=95), "lead": lambda: lead_chorus_notes(PROGRESSION)},
}


# ===================== main =====================

def main() -> int:
    print("Connecting to Ableton on localhost:9877…")
    with AbletonClient(timeout=30.0) as ab:
        info = ab.send("get_session_info")
        starting_tracks = info["track_count"]
        starting_scenes = info["scene_count"]
        print(f"Session: {starting_tracks} tracks, {starting_scenes} scenes, tempo={info['tempo']}, sig={info['signature_numerator']}/{info['signature_denominator']}")

        # ----- Phase 1: create 4 MIDI tracks at the end -----
        print("\nPhase 1: creating 4 MIDI tracks (Drums, 808 Bass, Chords, Lead)…")
        create_result = ab.batch([
            {"type": "create_midi_track", "params": {"index": -1}},
            {"type": "create_midi_track", "params": {"index": -1}},
            {"type": "create_midi_track", "params": {"index": -1}},
            {"type": "create_midi_track", "params": {"index": -1}},
        ])
        if create_result.get("failed_at") is not None:
            print("FAILED creating tracks:", json.dumps(create_result, indent=2))
            return 1

        drums_idx  = starting_tracks + 0
        bass_idx   = starting_tracks + 1
        chords_idx = starting_tracks + 2
        lead_idx   = starting_tracks + 3
        track_indexes = {"drums": drums_idx, "bass": bass_idx, "chords": chords_idx, "lead": lead_idx}
        print(f"  Created at indices {drums_idx}, {bass_idx}, {chords_idx}, {lead_idx}")

        # Name them + initial mix
        ab.batch([
            {"type": "set_track_name",   "params": {"track_index": drums_idx,  "name": "Drums"}},
            {"type": "set_track_name",   "params": {"track_index": bass_idx,   "name": "808 Bass"}},
            {"type": "set_track_name",   "params": {"track_index": chords_idx, "name": "Chords"}},
            {"type": "set_track_name",   "params": {"track_index": lead_idx,   "name": "Lead"}},
            {"type": "set_track_volume", "params": {"track_index": drums_idx,  "volume": 0.85}},
            {"type": "set_track_volume", "params": {"track_index": bass_idx,   "volume": 0.85}},
            {"type": "set_track_volume", "params": {"track_index": chords_idx, "volume": 0.70}},
            {"type": "set_track_volume", "params": {"track_index": lead_idx,   "volume": 0.78}},
        ])

        # ----- Phase 2: try to load default instruments -----
        print("\nPhase 2: loading instruments via search_browser…")
        try_loads: List[Tuple[int, str, str]] = [
            (drums_idx, "drums", "808"),       # any 808 / drum kit
            (bass_idx, "instruments", "Operator"),
            (chords_idx, "instruments", "Operator"),
            (lead_idx, "instruments", "Operator"),
        ]
        for ti, cat, query in try_loads:
            try:
                res = ab.send("search_browser", {"query": query, "category": cat})
                matches = [m for m in res.get("matches", []) if m.get("is_loadable") and m.get("uri")]
                if matches:
                    chosen = matches[0]
                    ab.send("load_browser_item", {"track_index": ti, "item_uri": chosen["uri"]})
                    print(f"  Track {ti}: loaded '{chosen['name']}' (path={chosen.get('path','?')})")
                else:
                    print(f"  Track {ti}: no '{query}' found in '{cat}', leaving empty")
            except Exception as e:
                print(f"  Track {ti}: load failed ({e}), leaving empty")

        # ----- Phase 3: ensure we have enough scenes -----
        print(f"\nPhase 3: ensuring at least {len(SCENES)} scenes (currently {starting_scenes})…")
        scenes_needed = len(SCENES) - starting_scenes
        scene_cmds = []
        for _ in range(max(0, scenes_needed)):
            scene_cmds.append({"type": "create_scene", "params": {"index": -1}})
        # Name the first len(SCENES) scenes
        for i, (label, _) in enumerate(SCENES):
            scene_cmds.append({"type": "set_scene_name", "params": {"scene_index": i, "name": label}})
        if scene_cmds:
            ab.batch(scene_cmds)

        # ----- Phase 4: build clips for every (scene, track) cell -----
        print("\nPhase 4: building clips with notes…")
        clip_cmds: List[Dict] = []
        for scene_idx, (label, kind) in enumerate(SCENES):
            builders = SECTION_BUILDERS[kind]
            for track_key, builder in builders.items():
                if builder is None:
                    continue
                ti = track_indexes[track_key]
                notes = builder()
                clip_cmds.append({"type": "create_clip", "params": {
                    "track_index": ti, "clip_index": scene_idx, "length": CLIP_LENGTH_BEATS}})
                clip_cmds.append({"type": "set_clip_name", "params": {
                    "track_index": ti, "clip_index": scene_idx, "name": f"{label}"}})
                clip_cmds.append({"type": "add_notes_to_clip", "params": {
                    "track_index": ti, "clip_index": scene_idx, "notes": notes}})
        print(f"  Submitting {len(clip_cmds)} commands as one batch…")
        clip_result = ab.batch(clip_cmds)
        if clip_result.get("failed_at") is not None:
            print("Clip batch failed at index", clip_result["failed_at"], "→", clip_result["error"])
            print(json.dumps(clip_result, indent=2))
            return 1
        print(f"  All {clip_result['executed']}/{clip_result['total']} commands succeeded.")

        # ----- Phase 5: try to bounce to arrangement (BETA) -----
        print("\nPhase 5: trying to bounce session to arrangement (BETA)…")
        try:
            arr_info = ab.send("get_arrangement_info")
            caps = arr_info.get("capabilities", {})
            if not caps.get("can_duplicate_to_arrangement"):
                print(f"  Arrangement bounce unsupported on this Live version: caps={caps}")
                print("  Leaving as session-view scenes; fire scene 0 to start.")
            else:
                bounce_cmds: List[Dict] = []
                cursor = 0.0
                for scene_idx in BOUNCE_ORDER:
                    for track_key, ti in track_indexes.items():
                        # only emit if there's actually a clip in this slot
                        if SECTION_BUILDERS[SCENES[scene_idx][1]].get(track_key) is None:
                            continue
                        bounce_cmds.append({"type": "add_clip_to_arrangement", "params": {
                            "track_index": ti, "clip_slot_index": scene_idx, "arrangement_time": cursor}})
                    cursor += CLIP_LENGTH_BEATS
                bounce_res = ab.batch(bounce_cmds)
                if bounce_res.get("failed_at") is None:
                    total_beats = cursor
                    total_secs = total_beats * 60.0 / info["tempo"]
                    print(f"  Bounced {len(BOUNCE_ORDER)} scenes onto arrangement: {total_beats} beats = {total_secs:.1f}s")
                else:
                    print("  Bounce failed at", bounce_res["failed_at"], "→", bounce_res["error"])
        except Exception as e:
            print("  Arrangement bounce skipped:", e)

        # ----- Phase 6: add a couple of locators if supported -----
        try:
            ab.send("add_arrangement_locator", {"time": 0.0, "name": "Intro"})
            ab.send("add_arrangement_locator", {"time": CLIP_LENGTH_BEATS * 1, "name": "Verse"})
            ab.send("add_arrangement_locator", {"time": CLIP_LENGTH_BEATS * 3, "name": "Pre-Chorus"})
            ab.send("add_arrangement_locator", {"time": CLIP_LENGTH_BEATS * 4, "name": "Chorus"})
            ab.send("add_arrangement_locator", {"time": CLIP_LENGTH_BEATS * 6, "name": "Verse 2"})
            ab.send("add_arrangement_locator", {"time": CLIP_LENGTH_BEATS * 7, "name": "Final Chorus"})
            print("  Added arrangement locators (Intro/Verse/Pre/Chorus/Verse 2/Final Chorus)")
        except Exception as e:
            print("  Locator add skipped:", e)

        # ----- Final session info -----
        final = ab.send("get_session_info")
        print(f"\nDone. Session now has {final['track_count']} tracks and {final['scene_count']} scenes.")
        print("Total session-view clips built:", sum(1 for _ in clip_cmds if _["type"] == "create_clip"))
        return 0


if __name__ == "__main__":
    sys.exit(main())
