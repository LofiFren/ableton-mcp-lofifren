"""Live in-Ableton confirmation for the House bass profile.

The 'definition of done' from HOUSE_BASS_BUILD_SPEC.md: hand the tool a NEW
house progression (not used while building) and get a correct off-beat,
root-dominant, low-register bass line written into Ableton -- no notes by hand.

This drives the real AbletonMCP socket (localhost:9877) via the same
AbletonClient the other scripts use. Open an EMPTY Live set with the LofiFren
remote script running, then:

    python scripts/live_test_house_bass.py

It creates a fresh MIDI track + a 4-bar clip and writes the House bass into it.
Drop any bass / sub / synth-bass instrument on the new track to hear it.
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from MCP_Server.personalities import generate_personality_bass  # noqa: E402
from ableton_client import AbletonClient  # noqa: E402

# --- FRESH progression: not used in build (Cm-Ab-Eb-Bb) or validation (Am-F-C-G)
PROGRESSION = ["Fm", "Db", "Ab", "Eb"]   # i-VI-III-VII in F minor
BARS_PER_CHORD = 1
TEMPO = 124.0
SEED = 7                                  # reproducible; set None for variety
CLIP_BEATS = 4.0 * BARS_PER_CHORD * len(PROGRESSION)   # 16
TRACK_NAME = "House Bass"


def main():
    notes = generate_personality_bass(
        "house", PROGRESSION, bars_per_chord=BARS_PER_CHORD,
        tempo=TEMPO, octave_offset=0, seed=SEED,
    )
    print("Generated {0} House bass notes over {1}".format(len(notes), PROGRESSION))

    try:
        with AbletonClient() as ab:
            # New MIDI track at the end of the set.
            track = ab.send("create_midi_track", {"index": -1})
            track_index = track.get("index")
            if track_index is None:
                # Fall back: query session to find the last track index.
                info = ab.send("get_session_info")
                track_index = int(info.get("track_count", 1)) - 1
            ab.send("set_track_name", {"track_index": track_index, "name": TRACK_NAME})

            # Fresh clip in slot 0, 4 bars long.
            ab.send("create_clip", {
                "track_index": track_index, "clip_index": 0, "length": CLIP_BEATS})
            ab.send("add_notes_to_clip", {
                "track_index": track_index, "clip_index": 0, "notes": notes})

        print("OK -- wrote {0} notes into track {1} ('{2}'), clip slot 0.".format(
            len(notes), track_index, TRACK_NAME))
        print("Open that clip in Ableton and confirm: off-beats only, low register,")
        print("one note at a time, mostly the chord root. Drop a bass/sub to hear it.")
    except Exception as e:
        print("COULD NOT REACH ABLETON: {0}".format(e))
        print("Make sure Live is open and the LofiFren remote script is loaded")
        print("(listening on localhost:9877), then re-run.")
        sys.exit(1)


if __name__ == "__main__":
    main()
