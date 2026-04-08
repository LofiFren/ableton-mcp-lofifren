"""Audition all three personality solos on the existing song's Lead track.

Strategy: replace the lead clip in scenes 3 (Chorus), 4 (Verse 2), and 5
(Final Chorus) with three different personalities so the user can A/B them
by firing each scene in Session view. Each fill goes through the new tools:
- delete_clip + create_clip + add_notes_to_clip (in one batch per personality)
- notes are generated locally via MCP_Server.personalities

After running, fire scenes 3, 4, 5 to compare:
    Scene 3 (Chorus)        → Coltrane
    Scene 4 (Verse 2)       → Kenny G
    Scene 5 (Final Chorus)  → Oscar Peterson
"""
from __future__ import annotations
import json
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

from ableton_client import AbletonClient
from MCP_Server.personalities import generate_personality_solo, PERSONALITIES


PROGRESSION = ["Cm", "Ab", "Eb", "Bb"]
LEAD_TRACK = 7        # the track named "Lead" in our song
CLIP_LENGTH = 16.0    # 4 bars = 16 beats

ASSIGNMENTS = [
    (3, "coltrane",        "Chorus (Coltrane)"),
    (4, "kenny_g",         "Verse 2 (Kenny G)"),
    (5, "oscar_peterson",  "Final Chorus (Oscar Peterson)"),
]


def main() -> int:
    print("Connecting to Ableton…")
    with AbletonClient() as ab:
        info = ab.send("get_session_info")
        if info["track_count"] <= LEAD_TRACK:
            print(f"ERROR: expected lead track at index {LEAD_TRACK}, but session has only {info['track_count']} tracks")
            return 1

        print(f"\nReplacing Lead clips on track {LEAD_TRACK} with personality solos…")
        for clip_idx, personality, label in ASSIGNMENTS:
            profile = PERSONALITIES[personality]
            notes = generate_personality_solo(personality, PROGRESSION, bars_per_chord=1, seed=42)
            density = len(notes) / 16.0
            pitches = [n["pitch"] for n in notes] or [60]
            print(f"\n  {label}: {len(notes):3d} notes, {density:.1f}/beat, range {min(pitches)}-{max(pitches)}")
            print(f"    profile: {profile['description']}")

            # Delete-then-create needs the slot to currently have a clip; if it doesn't, just create.
            ti = ab.send("get_track_info", {"track_index": LEAD_TRACK})
            slot = ti["clip_slots"][clip_idx]
            cmds = []
            if slot.get("has_clip"):
                cmds.append({"type": "delete_clip", "params": {
                    "track_index": LEAD_TRACK, "clip_index": clip_idx}})
            cmds.append({"type": "create_clip", "params": {
                "track_index": LEAD_TRACK, "clip_index": clip_idx, "length": CLIP_LENGTH}})
            cmds.append({"type": "set_clip_name", "params": {
                "track_index": LEAD_TRACK, "clip_index": clip_idx, "name": label}})
            cmds.append({"type": "add_notes_to_clip", "params": {
                "track_index": LEAD_TRACK, "clip_index": clip_idx, "notes": notes}})
            res = ab.batch(cmds)
            if res.get("failed_at") is not None:
                print(f"    BATCH FAILED at index {res['failed_at']}: {res['error']}")
                print(json.dumps(res, indent=2))
                return 1
            print(f"    Wrote {len(notes)} notes via {len(cmds)}-command batch (auto_extended={res['results'][-1]['result'].get('auto_extended', False)})")

        print("\nDone. To audition, fire each scene in Session view:")
        for clip_idx, personality, label in ASSIGNMENTS:
            print(f"  Scene {clip_idx}: {label}")
        print("\nThe Verse 2 slot (Kenny G) won't have its usual no-lead vibe — that's intentional for the A/B test.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
