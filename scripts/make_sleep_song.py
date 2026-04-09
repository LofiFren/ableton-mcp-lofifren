"""Build a 2:08 simple piano + drone sleep song in the existing session.

Adds 2 new MIDI tracks (Sleep Piano + Sleep Drone) at the end of the track
list, creates a new scene named 'Sleep' with per-scene tempo 60 BPM, and
fills both tracks with a 128-beat clip that plays for 2:08.

Musical content:
    Tempo:       60 BPM (set per-scene so the rest of the session keeps its tempo)
    Time sig:    4/4
    Length:      128 beats = 32 bars at 4/4 = 2:08 at 60 BPM
    Progression: Cmaj7 - Fmaj7 - Am7 - Em7 (I-IV-vi-iii in C — soft, no V tension)
                 Cycles 8 times across the clip.

Piano: gentle quarter-note arpeggios up the chord tones, voice-leading
       smoothly from one chord to the next. Soft velocities (40-65).

Drone: a tonic open-fifth pedal point — C2 + G2 sustained for the WHOLE
       128 beats (one note each, no movement). Very low velocity (45)
       so the pad sits underneath the piano.

To listen: Tab → Session View → fire the new 'Sleep' scene. The session
tempo will drop to 60 BPM automatically.
"""
from __future__ import annotations
import json
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

from ableton_client import AbletonClient
from MCP_Server.personalities import BROWSER_HINTS, PERSONALITIES


# ===================== song parameters =====================

PROGRESSION_CHORDS = [
    # (root_pitch_for_arpeggio, chord_tones_in_pitch)
    ("Cmaj7", [60, 64, 67, 71]),  # C E G B
    ("Fmaj7", [65, 69, 72, 76]),  # F A C E (above middle C)
    ("Am7",   [57, 60, 64, 67]),  # A C E G (below middle C — voice-leads down)
    ("Em7",   [52, 55, 59, 62]),  # E G B D (lower still)
]

CYCLES = 8                           # 8 progression repeats
BEATS_PER_CHORD = 4                  # 1 bar of 4/4 per chord
BEATS_PER_CYCLE = 4 * BEATS_PER_CHORD  # 16
TOTAL_BEATS = CYCLES * BEATS_PER_CYCLE  # 128 beats = 32 bars = 2:08 at 60 BPM


# ===================== note builders =====================

def piano_arpeggio_notes() -> list:
    """Gentle quarter-note arpeggios up each chord, repeated CYCLES times.
    Each note is ~0.9 beats so there's a tiny gap between them — feels
    breathy and unhurried."""
    notes = []
    for cycle in range(CYCLES):
        cycle_offset = cycle * BEATS_PER_CYCLE
        for chord_idx, (sym, pitches) in enumerate(PROGRESSION_CHORDS):
            chord_start = cycle_offset + chord_idx * BEATS_PER_CHORD
            for beat, pitch in enumerate(pitches):
                # Soft velocity with subtle dynamics on the downbeat of each chord
                vel = 60 if beat == 0 else 48 + (beat * 2)
                notes.append({
                    "pitch": pitch,
                    "start_time": float(chord_start + beat),
                    "duration": 0.92,
                    "velocity": vel,
                    "mute": False,
                })
    return notes


def drone_pedal_notes() -> list:
    """Tonic open fifth (C + G) sustained for the entire 128-beat clip.
    Very soft — sits beneath the piano as a hum."""
    return [
        {
            "pitch": 36,  # C2
            "start_time": 0.0,
            "duration": float(TOTAL_BEATS),
            "velocity": 50,
            "mute": False,
        },
        {
            "pitch": 43,  # G2 (a perfect fifth above C2)
            "start_time": 0.0,
            "duration": float(TOTAL_BEATS),
            "velocity": 42,
            "mute": False,
        },
    ]


# ===================== smart instrument loader (replicated from server.py) =====================

def load_best_instrument(ab, track_index, hints):
    """Pick the best Ableton instrument for the given hint list and load it.
    Same logic as MCP_Server.server.load_instrument_for_personality but
    inlined here so the test script can run without the mcp package."""
    candidates = []
    for hint_index, hint in enumerate(hints):
        try:
            res = ab.send("search_browser", {
                "query": hint,
                "category": "all",
                "prefer_preset": True,
                "max_results": 5,
            })
            for m in res.get("matches", []):
                if m.get("is_loadable") and m.get("uri"):
                    candidates.append({
                        "score": m.get("score", 0),
                        "hint_index": hint_index,
                        "name": m["name"],
                        "uri": m["uri"],
                        "hint": hint,
                    })
        except Exception:
            pass
    if not candidates:
        return None
    candidates.sort(key=lambda c: (-c["score"], c["hint_index"], c["name"]))
    chosen = candidates[0]
    ab.send("load_browser_item", {"track_index": track_index, "item_uri": chosen["uri"]})
    return chosen


# ===================== main =====================

def main() -> int:
    print("Connecting to Ableton…", flush=True)
    with AbletonClient(timeout=120.0) as ab:
        info = ab.send("get_session_info")
        starting_tracks = info["track_count"]
        starting_scenes = info["scene_count"]
        print(f"  Existing session: {starting_tracks} tracks, {starting_scenes} scenes, tempo {info['tempo']} BPM", flush=True)

        # ----- Phase 1: create 2 new MIDI tracks at the end -----
        print("\nPhase 1: creating 'Sleep Piano' and 'Sleep Drone' tracks…", flush=True)
        ab.batch([
            {"type": "create_midi_track", "params": {"index": -1}},
            {"type": "create_midi_track", "params": {"index": -1}},
        ])
        piano_idx = starting_tracks
        drone_idx = starting_tracks + 1
        ab.batch([
            {"type": "set_track_name",   "params": {"track_index": piano_idx, "name": "Sleep Piano"}},
            {"type": "set_track_name",   "params": {"track_index": drone_idx, "name": "Sleep Drone"}},
            {"type": "set_track_volume", "params": {"track_index": piano_idx, "volume": 0.72}},
            {"type": "set_track_volume", "params": {"track_index": drone_idx, "volume": 0.55}},
        ])
        print(f"  Created tracks {piano_idx} (piano) and {drone_idx} (drone)", flush=True)

        # ----- Phase 2: load instruments -----
        print("\nPhase 2: loading real piano + a soft pad via the smart loader…", flush=True)
        # Piano: try grand piano / acoustic piano / piano in priority order
        piano_pick = load_best_instrument(ab, piano_idx, [
            "grand piano", "acoustic piano", "piano daze", "piano",
        ])
        if piano_pick:
            print(f"  Piano: {piano_pick['name']} (score {piano_pick['score']:.2f}, hint='{piano_pick['hint']}')", flush=True)
        else:
            print("  Piano: no match, leaving empty", flush=True)
        # Drone: prefer slow ambient pads
        drone_pick = load_best_instrument(ab, drone_idx, [
            "ambient pad", "deep pad", "slow pad", "warm pad", "pad",
        ])
        if drone_pick:
            print(f"  Drone: {drone_pick['name']} (score {drone_pick['score']:.2f}, hint='{drone_pick['hint']}')", flush=True)
        else:
            print("  Drone: no match, leaving empty", flush=True)

        # ----- Phase 3: create a new scene named 'Sleep' with per-scene tempo 60 -----
        print("\nPhase 3: creating 'Sleep' scene with per-scene tempo 60 BPM…", flush=True)
        new_scene = starting_scenes  # next free scene index
        ab.batch([
            {"type": "create_scene",     "params": {"index": -1}},
            {"type": "set_scene_name",   "params": {"scene_index": new_scene, "name": "Sleep"}},
            {"type": "set_scene_tempo",  "params": {"scene_index": new_scene, "tempo": 60.0}},
        ])
        print(f"  Created scene {new_scene} (Sleep, 60 BPM)", flush=True)

        # ----- Phase 4: build the clips -----
        print("\nPhase 4: building piano + drone clips ({0} beats each = 2:08 at 60 BPM)…".format(TOTAL_BEATS), flush=True)
        piano_notes = piano_arpeggio_notes()
        drone_notes = drone_pedal_notes()
        print(f"  Piano: {len(piano_notes)} notes ({CYCLES} cycles × {len(PROGRESSION_CHORDS)} chords × 4 arpeggio notes)", flush=True)
        print(f"  Drone: {len(drone_notes)} notes (open-fifth pedal — C2 + G2 sustained)", flush=True)

        result = ab.batch([
            {"type": "create_clip", "params": {
                "track_index": piano_idx, "clip_index": new_scene, "length": float(TOTAL_BEATS)}},
            {"type": "set_clip_name", "params": {
                "track_index": piano_idx, "clip_index": new_scene, "name": "Sleep Piano"}},
            {"type": "add_notes_to_clip", "params": {
                "track_index": piano_idx, "clip_index": new_scene, "notes": piano_notes}},
            {"type": "create_clip", "params": {
                "track_index": drone_idx, "clip_index": new_scene, "length": float(TOTAL_BEATS)}},
            {"type": "set_clip_name", "params": {
                "track_index": drone_idx, "clip_index": new_scene, "name": "Sleep Drone"}},
            {"type": "add_notes_to_clip", "params": {
                "track_index": drone_idx, "clip_index": new_scene, "notes": drone_notes}},
        ])
        if result.get("failed_at") is not None:
            print(f"  BATCH FAILED at index {result['failed_at']}: {result['error']}", flush=True)
            return 1
        print(f"  All {result['executed']}/{result['total']} batch commands succeeded.", flush=True)

        # ----- Phase 5: report -----
        print("\nDone. To listen:", flush=True)
        print(f"  1. Switch to Session View (Tab)", flush=True)
        print(f"  2. Fire scene {new_scene} ('Sleep') — the tempo will drop to 60 BPM automatically", flush=True)
        print(f"  3. The clip plays once through (2:08) and stops", flush=True)
        print(f"  4. To restore your previous song's tempo, fire any earlier scene that doesn't have a per-scene tempo set", flush=True)
        return 0


if __name__ == "__main__":
    sys.exit(main())
