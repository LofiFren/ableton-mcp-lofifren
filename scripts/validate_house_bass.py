"""Step 5 validation for the House bass profile (HOUSE_BASS_BUILD_SPEC.md).

Generates House bass over a NEW progression (not used while building) and runs
the five acceptance checks programmatically. Pure Python — no Ableton needed;
this validates the note list the tool would write into a clip.

    python scripts/validate_house_bass.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from MCP_Server.personalities import generate_personality_bass  # noqa: E402
from MCP_Server.music import chord_root_pitch  # noqa: E402

# A NEW progression — deliberately different from the build/baseline prog
# (["Cm","Ab","Eb","Bb"]). 4 chords x 1 bar = 16 beats.
PROGRESSION = ["Am", "F", "C", "G"]
BARS_PER_CHORD = 1
TEMPO = 124.0
SEED = 7
C3_MIDI = 48          # range cap: pitch must be <= C3
TOTAL_BEATS = 4.0 * BARS_PER_CHORD * len(PROGRESSION)   # 16
EPS = 1e-6

notes = generate_personality_bass(
    "house", PROGRESSION, bars_per_chord=BARS_PER_CHORD,
    tempo=TEMPO, octave_offset=0, seed=SEED,
)
notes_sorted = sorted(notes, key=lambda n: n["start_time"])

results = []

# --- Check 1: notes land on off-beats, never on beat 1 / any downbeat ---
offbeat_ok = all(abs((n["start_time"] % 1.0) - 0.5) < EPS for n in notes)
no_downbeat = all((n["start_time"] % 4.0) > EPS for n in notes)  # nothing on a bar's beat 1
results.append(("1. Off-beats only, never beat 1",
                offbeat_ok and no_downbeat,
                "all start_times have .5 fractional, none on a downbeat"))

# --- Check 2: predominantly the chord root ---
# Notes are emitted per chord in order, 4 per bar.
notes_per_bar = len(PROGRESSION[0:1]) and 4  # rhythm_pattern length = 4
root_hits = 0
for i, n in enumerate(notes):
    chord_idx = i // 4
    sym = PROGRESSION[chord_idx % len(PROGRESSION)]
    root_pc = chord_root_pitch(sym, 2) % 12
    if n["pitch"] % 12 == root_pc:
        root_hits += 1
root_frac = root_hits / len(notes) if notes else 0.0
results.append(("2. Predominantly the chord root",
                root_frac >= 0.6,
                "root fraction = {0:.0%} ({1}/{2})".format(root_frac, root_hits, len(notes))))

# --- Check 3: all notes in the low register (<= C3) ---
max_pitch = max(n["pitch"] for n in notes)
results.append(("3. All notes <= C3 (low register)",
                max_pitch <= C3_MIDI,
                "highest pitch = {0} (cap {1})".format(max_pitch, C3_MIDI)))

# --- Check 4: monophonic — no overlapping notes ---
overlap = False
for a, b in zip(notes_sorted, notes_sorted[1:]):
    if a["start_time"] + a["duration"] > b["start_time"] + EPS:
        overlap = True
        break
results.append(("4. Monophonic (no overlap)",
                not overlap,
                "no note's end crosses the next note's start"))

# --- Check 5: 16 notes inside 16 beats, no auto-extend ---
last_end = max(n["start_time"] + n["duration"] for n in notes)
results.append(("5. 16 notes inside 16 beats, no auto-extend",
                len(notes) == 16 and last_end <= TOTAL_BEATS + EPS,
                "{0} notes, last note ends at {1} (limit {2})".format(
                    len(notes), last_end, TOTAL_BEATS)))

print("House bass validation -- progression {0}, seed {1}, tempo {2}".format(
    PROGRESSION, SEED, TEMPO))
print("-" * 64)
all_pass = True
for label, ok, detail in results:
    flag = "PASS" if ok else "FAIL"
    all_pass = all_pass and ok
    print("[{0}] {1}".format(flag, label))
    print("        {0}".format(detail))
print("-" * 64)
print("RESULT:", "ALL PASS" if all_pass else "FAILURES PRESENT")

# Show the generated line for eyeballing
print("\nGenerated notes (start, pitch, dur, vel):")
for n in notes_sorted:
    print("  t={0:<5} pitch={1:<3} dur={2:<4} vel={3}".format(
        n["start_time"], n["pitch"], n["duration"], n["velocity"]))

sys.exit(0 if all_pass else 1)
