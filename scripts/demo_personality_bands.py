"""End-to-end demo of the full personality system on the existing song.

Builds two new "personality bands" in scenes 6 and 7 of the live Ableton
session — all four tracks (Drums/Bass/Chords/Lead) get filled with rule-based
output from the personality system. Each scene is a different combination
so you can A/B them by firing scene 6 vs scene 7.

Scene 6 — "Pop Classic Band":
    Drums    Questlove        (deep pocket, slightly behind)
    Bass     James Jamerson   (Motown syncopated 8ths + ghost notes)
    Chords   Bill Evans       (rootless 4-note voicings, sustained)
    Lead     Coltrane × Wayne Shorter blend (50/50)

Scene 7 — "Modern Jazz Band":
    Drums    Tony Williams    (forward-momentum swing, ride cymbal)
    Bass     Jaco Pastorius   (melodic fretless, chord-tone heavy)
    Chords   Herbie Hancock   (rootless w/ off-beat polyrhythms)
    Lead     Charlie Parker   (bebop dense, chromatic approach)

Run from the repo root: ``PYTHONPATH=. python3 scripts/demo_personality_bands.py``
"""
from __future__ import annotations
import json
import sys
from typing import Dict, List

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

from ableton_client import AbletonClient
from MCP_Server.personalities import (
    generate_personality_part,
    generate_blended_solo,
    list_personalities,
    PERSONALITIES,
)


PROGRESSION = ["Cm", "Ab", "Eb", "Bb"]
DRUMS_TRACK, BASS_TRACK, CHORDS_TRACK, LEAD_TRACK = 4, 5, 6, 7
CLIP_LENGTH = 16.0  # 4 bars

SHOWCASES = [
    {
        "scene_index": 6,
        "scene_name": "Pop Classic Band",
        "drums":  ("questlove",       None),
        "bass":   ("james_jamerson",  None),
        "chords": ("bill_evans",      None),
        # lead is a blend → handled separately
        "lead_blend": ("coltrane", "wayne_shorter", 0.5),
    },
    {
        "scene_index": 7,
        "scene_name": "Modern Jazz Band",
        "drums":  ("tony_williams",   None),
        "bass":   ("jaco_pastorius",  None),
        "chords": ("herbie_hancock",  None),
        "lead":   ("charlie_parker",  None),
    },
]


def section_header(title: str) -> None:
    print("\n" + "=" * 64)
    print(title)
    print("=" * 64)


def main() -> int:
    print("Connecting to Ableton on localhost:9877…")
    with AbletonClient(timeout=60.0) as ab:
        info = ab.send("get_session_info")
        tempo = float(info["tempo"])
        print(f"Session tempo: {tempo} BPM, {info['scene_count']} scenes, {info['track_count']} tracks")

        if info["track_count"] <= LEAD_TRACK:
            print(f"ERROR: expected lead track at index {LEAD_TRACK}; only {info['track_count']} tracks present.")
            return 1

        # Show what we have available
        section_header("Personalities available")
        by_role: Dict[str, List[str]] = {}
        for entry in list_personalities():
            by_role.setdefault(entry["role"], []).append(
                f"{entry['name']:18} (sweet spot {entry['tempo_sweet_spot']} BPM)")
        for role in ("solo", "comp", "bass", "drums"):
            print(f"\n  {role}:")
            for line in by_role.get(role, []):
                print(f"    {line}")

        # Make sure we have enough scenes (we expect 8 already based on earlier session)
        if info["scene_count"] < 8:
            print(f"\nCreating scenes up to index 7 ({8 - info['scene_count']} new)…")
            create_cmds = []
            for _ in range(8 - info["scene_count"]):
                create_cmds.append({"type": "create_scene", "params": {"index": -1}})
            ab.batch(create_cmds)

        # Build each showcase
        for show in SHOWCASES:
            scene = show["scene_index"]
            section_header(f"Building Scene {scene}: {show['scene_name']}")
            ab.send("set_scene_name", {"scene_index": scene, "name": show["scene_name"]})

            # Helper to generate, then create+fill a clip in one batch
            def fill_track(track_index: int, personality: str, label: str, role_label: str, blend: bool = False, blend_args=None) -> None:
                if blend:
                    a, b, ratio = blend_args
                    notes = generate_blended_solo(a, b, ratio, PROGRESSION, bars_per_chord=1, tempo=tempo, seed=None)
                    profile_name = f"{PERSONALITIES[a]['name']} × {PERSONALITIES[b]['name']} ({int((1-ratio)*100)}/{int(ratio*100)})"
                    warning = None
                else:
                    notes, warning = generate_personality_part(
                        personality, PROGRESSION, bars_per_chord=1, tempo=tempo, seed=None,
                    )
                    profile_name = PERSONALITIES[personality]["name"]
                pitches = [n["pitch"] for n in notes] or [60]
                density = len(notes) / 16.0
                marker = " (⚠ tempo)" if warning else ""
                print(f"  {role_label:7} track {track_index}: {profile_name:35} {len(notes):3d} notes  {density:.1f}/beat  range {min(pitches)}-{max(pitches)}{marker}")
                if warning:
                    print(f"           ⚠ {warning}")

                # Check if slot has a clip first; if so delete then recreate
                ti = ab.send("get_track_info", {"track_index": track_index})
                slot = ti["clip_slots"][scene]
                cmds = []
                if slot.get("has_clip"):
                    cmds.append({"type": "delete_clip", "params": {
                        "track_index": track_index, "clip_index": scene}})
                cmds.append({"type": "create_clip", "params": {
                    "track_index": track_index, "clip_index": scene, "length": CLIP_LENGTH}})
                cmds.append({"type": "set_clip_name", "params": {
                    "track_index": track_index, "clip_index": scene, "name": label}})
                cmds.append({"type": "add_notes_to_clip", "params": {
                    "track_index": track_index, "clip_index": scene, "notes": notes}})
                res = ab.batch(cmds)
                if res.get("failed_at") is not None:
                    print(f"           BATCH FAILED at index {res['failed_at']}: {res['error']}")

            # Drums
            personality_key = show["drums"][0]
            fill_track(DRUMS_TRACK, personality_key, f"{show['scene_name']} drums", "drums")

            # Bass
            personality_key = show["bass"][0]
            fill_track(BASS_TRACK, personality_key, f"{show['scene_name']} bass", "bass")

            # Chords
            personality_key = show["chords"][0]
            fill_track(CHORDS_TRACK, personality_key, f"{show['scene_name']} chords", "chords")

            # Lead — either single personality or blend
            if "lead_blend" in show:
                a, b, ratio = show["lead_blend"]
                fill_track(LEAD_TRACK, "", f"{show['scene_name']} lead", "lead", blend=True, blend_args=(a, b, ratio))
            else:
                personality_key = show["lead"][0]
                fill_track(LEAD_TRACK, personality_key, f"{show['scene_name']} lead", "lead")

        section_header("Done — fire the new scenes in Ableton")
        print()
        print("Switch to Session View (Tab) and click the Scene Launch button for:")
        for show in SHOWCASES:
            print(f"  Scene {show['scene_index']}: {show['scene_name']}")
        print()
        print("Each scene plays the same Cm-Ab-Eb-Bb progression with a completely")
        print("different personality 'band' on every track. Compare the two to hear")
        print("how the rule-based generators capture each player's surface style.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
