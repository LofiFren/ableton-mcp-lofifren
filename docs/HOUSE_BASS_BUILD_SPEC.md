# House Bass — Build Spec (ableton-mcp LofiFren fork)

**Status:** spec / pre-build · **Repo:** the `ableton-mcp` LofiFren fork · **Files:** `MCP_Server/personalities.py`, `MCP_Server/music.py` (reference only)
**For:** Claude Code, in the repo. This is a build plan, not a chat task.

---

## Why this build exists (the finding)
The bass engine (`_generate_bass_impl`) generates note start-times on a **hardcoded even grid** and **forces the root onto beat 1**. Bass personalities can only tune scalars (`walking_density`, `swing`, `syncopation`) + pitch choice — they **cannot specify where notes land**. House bass is defined by **off-beat placement** and **avoiding the downbeat**, so the current engine can't express it (it does the opposite).

Meanwhile, the **comp and drums roles already carry explicit placement lists** (`rhythm_pattern` for comp; `kick_pattern` etc. for drums) that their generators play back. So the mechanism we need already exists in the codebase — for other roles. This build **extends that proven pattern to the bass role**, additively.

Redundancy check (done): no house/off-beat bass anywhere; nothing to duplicate. The `four_on_floor` preset is drums-only, a separate subsystem.

---

## Design decision: ADDITIVE path (low-risk)
**Do not rewrite `_generate_bass_impl`.** Add an optional branch:

- If a bass profile has a new optional `rhythm_pattern` field → use a **new placement path** that honors it.
- If it does **not** → fall through to the **existing grid engine, untouched**.

This guarantees the six existing personalities (Jamerson, Jaco, Pino, Marcus Miller, Ray Brown, Mingus) are **byte-for-byte unaffected**. House rides the new path only.

Rationale: the existing engine is depended on by six working personalities; an additive branch makes regression impossible-by-construction for them and makes the new path testable in isolation.

---

## Build steps (in order)

### Step 1 — Confirm comp's `rhythm_pattern` shape (read, don't write)
Read how `_generate_comping_impl` consumes `rhythm_pattern` (the Herbie Hancock entry: `[(0.5, 0.4), (1.5, 0.4), (2.5, 0.4), (3.75, 0.25)]` — each tuple is `(beat_position, duration)`). **Mirror this shape for bass** so the codebase stays consistent. Confirm: is position measured per-bar or per-chord? Match whatever comp does.

### Step 2 — Add the optional `rhythm_pattern` branch to `_generate_bass_impl`
At the top of the timing section, before the hardcoded `n_steps` grid loop:
- If `profile.get("rhythm_pattern")` exists: iterate that list instead of the even grid. For each `(beat_pos, dur)`, compute `t = bar_start + beat_pos`, assign pitch by the profile's pitch logic (root-dominant for house — see Step 4), append the note.
- Else: run the **existing** loop exactly as-is.
- The `on_one`/`root-on-beat-1` forcing must live **only** in the else branch. The new branch must NOT force root onto beat 1 (that's the whole point).

Keep the new branch small and readable; it's an alternate placement source, not a redesign.

### Step 3 — Regression test (the safety net)
Before and after the change, generate bass for all six existing personalities over a fixed test progression and confirm output is **identical** (same note list). This is the verify-against-known-good check — the same discipline that caught the timing bug earlier. If any existing personality's output changes, the additive branch leaked into the shared path — fix before proceeding.

### Step 4 — Add the "House" genre profile
A new bass profile, genre-named (not a person). Seed values from this session's hand-tested candidates:
- `role`: "bass"
- `name`: "House" (genre profile, deliberately not a real player)
- `range`: low, e.g. `(28, 48)` — house bass lives ~C1–C2, cap ≤ C3
- `register_preference`: "low"
- `chord_tone_priority`: high (root-dominant — house bass is mostly the root)
- `rhythm_pattern`: off-beat placement. Start from the candidate that read best this session; a classic off-beat is notes on the "and" of each beat: `[(0.5, 0.25), (1.5, 0.25), (2.5, 0.25), (3.5, 0.25)]` (per-bar; adjust to comp's convention from Step 1).
- Velocity: moderate, not hot (this session's candidates sat well ~66–74, not 95–110).
- **Monophonic** (one note at a time). Optional later: a declared octave-jump or octave-dyad accent — out of v1.

### Step 5 — Validate the House output (the five checks)
Generate House bass over a **new** progression (not one used while building), into an **empty** Ableton project (not the house song). Confirm:
1. Notes land on the off-beats, not beat 1.
2. Predominantly the chord root.
3. All notes ≤ C3 / in the low register.
4. Monophonic — no overlapping notes (one sounds at any instant).
5. 16 notes inside 16 beats for a 4-bar test, no auto-extend (the timing-math check).

---

## Definition of done
Hand the tool a **new** house progression you didn't use while building, pick the "House" personality, and get a correct off-beat, root-dominant, low-register bass line written into Ableton — **without composing a single note by hand.** The six existing personalities produce identical output to before the change.

That — a new progression in, correct house bass out, repeatable — is the line that means the tool exists. (Not before.)

---

## Scope discipline
**In v1:** additive `rhythm_pattern` branch for bass; one House genre profile (root-dominant, off-beat, low, monophonic); regression test for the six existing personalities; five-point validation.

**Out (v2+):** octave-jump / octave-dyad accents in the House profile; rewriting the shared bass engine; solo-role rhythm parameterization; multiple house sub-styles; chord qualities beyond what `parse_chord` already handles.

**PR note:** the bass `rhythm_pattern` extension is a real capability upgrade to the fork and a legitimate upstream-PR candidate — it brings bass to parity with comp/drums. Run it past the `commit-review` sub-agent before committing, per the usual ritual.
