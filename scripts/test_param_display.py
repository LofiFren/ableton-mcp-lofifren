"""Offline unit tests for the parameter display-value helpers.

These import the REAL helper functions out of AbletonMCP_Remote_Script/__init__.py
(no logic copies, so they can't drift) by stubbing the Live ``_Framework`` module
that the Remote Script imports at module load. They never touch Ableton, so they
run in any plain Python 3 process:

    python scripts/test_param_display.py

Exit code 0 = all passed, 1 = a failure (prints which).

What they cover: display-string parsing (dB/Hz/kHz/ms/us/s/ratio/-inf/%),
Unicode-minus + no-space normalisation, the exact str_to_value path, the
binary-search fallback (increasing AND decreasing curves), the 12-iteration
cap, and the -inf volume floor as a binary-search endpoint.
"""
from __future__ import annotations

import importlib.util
import math
import os
import sys
import types


# --- Load the real helpers, stubbing the Live framework import -------------
def _load_remote_script_module():
    fw = types.ModuleType("_Framework")
    cs = types.ModuleType("_Framework.ControlSurface")

    class _ControlSurface(object):  # minimal stand-in; methods never called here
        def __init__(self, *a, **k):
            pass

    cs.ControlSurface = _ControlSurface
    fw.ControlSurface = cs
    sys.modules["_Framework"] = fw
    sys.modules["_Framework.ControlSurface"] = cs

    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "..", "AbletonMCP_Remote_Script", "__init__.py")
    spec = importlib.util.spec_from_file_location("ableton_rs_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M = _load_remote_script_module()


# --- Fake Live parameters with realistic non-linear display curves ----------
class FakeParam(object):
    """Mimics a Live DeviceParameter: raw value in [min, max], a forward
    display function (str_for_value), and optionally an exact inverse
    (str_to_value). Omit ``inverse`` to force the binary-search path."""

    def __init__(self, name, vmin, vmax, fmt, inverse=None):
        self.name = name
        self.min = vmin
        self.max = vmax
        self._fmt = fmt
        self._inverse = inverse
        self.value = vmin

    def str_for_value(self, value):
        return self._fmt(value)

    # Only present when an inverse is supplied (lets us test both paths).
    def __getattr__(self, item):
        if item == "str_to_value":
            inv = self.__dict__.get("_inverse")
            if inv is None:
                raise AttributeError("str_to_value")
            return lambda s: inv(s)
        raise AttributeError(item)


def _db_fmt(raw):
    if raw <= 0.0:
        return "-inf dB"
    return "%.1f dB" % (20.0 * math.log10(raw))


def _db_inverse(s):
    s = s.lower().replace("db", "").strip()
    return 10.0 ** (float(s) / 20.0)


def _hz_fmt(raw):
    hz = 20.0 * (1000.0 ** raw)  # 20 Hz .. 20000 Hz log sweep
    if hz >= 1000.0:
        return "%.2f kHz" % (hz / 1000.0)
    return "%.0f Hz" % hz


def _ratio_fmt(raw):
    return "%.2f:1" % (1.0 + 19.0 * raw)  # 1:1 .. 20:1


def _ms_fmt(raw):
    ms = 0.01 * (100000.0 ** raw)  # 0.01 ms .. 1000 ms log sweep
    if ms >= 1000.0:
        return "%.2f s" % (ms / 1000.0)
    return "%.2f ms" % ms


def _inverted_fmt(raw):
    return "%.1f" % (100.0 - 100.0 * raw)  # DECREASING: raw 0 -> 100, raw 1 -> 0


# --- Tiny test runner -------------------------------------------------------
_FAILURES = []


def check(label, cond):
    status = "PASS" if cond else "FAIL"
    print("  [%s] %s" % (status, label))
    if not cond:
        _FAILURES.append(label)


def approx(a, b, tol):
    return abs(a - b) <= tol


def main():
    print("Parsing:")
    p = M._parse_display_number
    check("'-9.0 dB' -> -9.0", approx(p("-9.0 dB"), -9.0, 1e-9))
    check("'-9dB' (no space) -> -9.0", approx(p("-9dB"), -9.0, 1e-9))
    check("'120 Hz' -> 120", approx(p("120 Hz"), 120.0, 1e-9))
    check("'1.20 kHz' -> 1200", approx(p("1.20 kHz"), 1200.0, 1e-9))
    check("'4.00:1' -> 4.0", approx(p("4.00:1"), 4.0, 1e-9))
    check("'4:1' -> 4.0", approx(p("4:1"), 4.0, 1e-9))
    check("'0.03 ms' -> 0.03", approx(p("0.03 ms"), 0.03, 1e-9))
    check("'1.5 s' -> 1500 ms", approx(p("1.5 s"), 1500.0, 1e-9))
    check("'30 us' -> 0.03 ms", approx(p("30 us"), 0.03, 1e-9))
    check("'-inf dB' -> very negative", p("-inf dB") < -1e20)
    check("'50 %' -> 50", approx(p("50 %"), 50.0, 1e-9))
    check("'no number' -> None", p("hello") is None)

    print("Normalisation (Unicode minus / dashes):")
    n = M._normalize_display_target
    check("U+2212 minus -> ASCII", n(u"−9 dB") == "-9 dB")
    check("en-dash -> ASCII", n(u"–9 dB") == "-9 dB")
    check("strips whitespace", n("  4:1  ") == "4:1")
    check("U+2212 then parses", approx(p(u"−9 dB"), -9.0, 1e-9))

    print("Resolve via str_to_value (exact inverse path):")
    db = FakeParam("Volume", 0.0, 1.0, _db_fmt, inverse=_db_inverse)
    raw, method = M._resolve_param_raw(db, "-9 dB")
    check("method is str_to_value", method == "str_to_value")
    check("raw ~ 10**(-9/20)=0.3548", approx(raw, 10 ** (-9.0 / 20.0), 1e-6))
    raw, method = M._resolve_param_raw(db, u"−9dB")  # unicode + no space
    check("unicode-minus no-space resolves", approx(raw, 10 ** (-9.0 / 20.0), 1e-6))

    print("Resolve via binary search (no inverse available):")
    db_bs = FakeParam("Volume", 0.0, 1.0, _db_fmt)  # no inverse
    raw, method = M._resolve_param_raw(db_bs, "-9 dB", max_iter=12)
    check("method is binary_search", method == "binary_search")
    check("binary search lands within 0.1 dB of -9",
          approx(20.0 * math.log10(raw), -9.0, 0.1))

    hz = FakeParam("Cutoff", 0.0, 1.0, _hz_fmt)
    raw, _ = M._resolve_param_raw(hz, "120 Hz", max_iter=12)
    got_hz = 20.0 * (1000.0 ** raw)
    check("120 Hz binary search within 3 Hz", approx(got_hz, 120.0, 3.0))

    raw, _ = M._resolve_param_raw(hz, "1.2 kHz", max_iter=12)
    got_hz = 20.0 * (1000.0 ** raw)
    check("1.2 kHz binary search within 30 Hz", approx(got_hz, 1200.0, 30.0))

    ratio = FakeParam("Ratio", 0.0, 1.0, _ratio_fmt)
    raw, _ = M._resolve_param_raw(ratio, "4:1", max_iter=12)
    got_ratio = 1.0 + 19.0 * raw
    check("4:1 binary search within 0.1", approx(got_ratio, 4.0, 0.1))

    ms = FakeParam("Attack", 0.0, 1.0, _ms_fmt)
    raw, _ = M._resolve_param_raw(ms, "0.03 ms", max_iter=12)
    got_ms = 0.01 * (100000.0 ** raw)
    check("0.03 ms binary search within 0.01 ms", approx(got_ms, 0.03, 0.01))

    print("Binary search on a DECREASING curve:")
    inv = FakeParam("Inverted", 0.0, 1.0, _inverted_fmt)
    raw, _ = M._resolve_param_raw(inv, "30", max_iter=12)
    got = 100.0 - 100.0 * raw
    check("decreasing curve target 30 within 0.5", approx(got, 30.0, 0.5))

    print("Edge cases:")
    # -inf endpoint must not break direction detection.
    raw, _ = M._resolve_param_raw(db_bs, "-40 dB", max_iter=12)
    check("-40 dB resolves despite -inf floor at min",
          approx(20.0 * math.log10(raw), -40.0, 0.2))
    # Iteration cap honoured (cannot converge past 2**-max_iter resolution).
    calls = {"n": 0}

    class Counting(FakeParam):
        def str_for_value(self, value):
            calls["n"] += 1
            return FakeParam.str_for_value(self, value)

    c = Counting("Cutoff", 0.0, 1.0, _hz_fmt)
    M._resolve_param_raw(c, "500 Hz", max_iter=12)
    check("str_for_value called <= 12 (loop) + 2 (endpoints)", calls["n"] <= 14)
    # Degenerate range.
    flat = FakeParam("Flat", 0.5, 0.5, lambda v: "x")
    check("min==max returns the value", M._binary_search_raw(flat, 1.0) == 0.5)

    print("")
    if _FAILURES:
        print("FAILED (%d): %s" % (len(_FAILURES), ", ".join(_FAILURES)))
        return 1
    print("ALL PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
