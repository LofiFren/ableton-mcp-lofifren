"""Regression baseline / diff for the six existing bass personalities.

Step 3 of HOUSE_BASS_BUILD_SPEC.md — the safety net. Generates bass for every
existing bass personality over a FIXED progression with a FIXED seed and tempo
so the output is fully deterministic, and dumps it to a JSON snapshot.

Usage:
    python scripts/regression_bass_baseline.py            # write/refresh baseline
    python scripts/regression_bass_baseline.py --check     # diff current vs baseline

The House profile (which rides the new rhythm_pattern path) is intentionally
EXCLUDED here — this snapshot only guards the personalities that must stay
byte-for-byte identical across the additive change.
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from MCP_Server.personalities import generate_personality_bass  # noqa: E402

# Deterministic inputs — do NOT change these between baseline and check runs.
EXISTING_BASS = [
    "james_jamerson",
    "jaco_pastorius",
    "pino_palladino",
    "marcus_miller",
    "ray_brown",
    "charles_mingus",
]
PROGRESSION = ["Cm", "Ab", "Eb", "Bb"]
BARS_PER_CHORD = 1
TEMPO = 120.0
SEED = 42

SNAPSHOT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bass_baseline.json")


def generate_all():
    out = {}
    for key in EXISTING_BASS:
        notes = generate_personality_bass(
            key, PROGRESSION, bars_per_chord=BARS_PER_CHORD,
            tempo=TEMPO, octave_offset=0, seed=SEED,
        )
        out[key] = notes
    return out


def main():
    check = "--check" in sys.argv
    current = generate_all()

    if check:
        if not os.path.exists(SNAPSHOT_PATH):
            print("NO BASELINE on disk — run without --check first.")
            sys.exit(2)
        with open(SNAPSHOT_PATH) as f:
            baseline = json.load(f)
        # Compare via canonical JSON so float formatting is identical.
        cur_json = json.dumps(current, sort_keys=True, indent=2)
        base_json = json.dumps(baseline, sort_keys=True, indent=2)
        if cur_json == base_json:
            print("IDENTICAL - all six existing personalities match baseline. PASS")
            for key in EXISTING_BASS:
                print("  {0}: {1} notes".format(key, len(current[key])))
            sys.exit(0)
        else:
            print("MISMATCH - output changed vs baseline. FAIL")
            for key in EXISTING_BASS:
                b = json.dumps(baseline.get(key), sort_keys=True)
                c = json.dumps(current.get(key), sort_keys=True)
                flag = "OK" if b == c else "CHANGED"
                print("  {0}: baseline={1} notes, current={2} notes  [{3}]".format(
                    key, len(baseline.get(key, [])), len(current.get(key, [])), flag))
            sys.exit(1)
    else:
        with open(SNAPSHOT_PATH, "w") as f:
            json.dump(current, f, sort_keys=True, indent=2)
        print("WROTE baseline -> {0}".format(SNAPSHOT_PATH))
        for key in EXISTING_BASS:
            print("  {0}: {1} notes".format(key, len(current[key])))


if __name__ == "__main__":
    main()
