#!/usr/bin/env python3
"""Deterministic Descent demo benchmark: wall time to reach the same demo frames.

  python demo_bench.py LOG [LOG ...] [--from 100] [--to 1100] [--step 200] [--name NAME ...]

The demo plays the same frames in every run, so runs are compared at the same
demo POSITION (game frame N), not over the same wall-clock window (a faster run
is further into the demo at any given time, i.e. in different scenes).

Frame position: the sum of the [bb-v93-game] changed-fields counts (new guest
screens). Time: each report interval, from the [bb-v28-lcd] line before it
(LCD frames / LCD fps). Frames before --from are skipped, because loading time
differs between runs.
"""
import argparse, re, sys


def timeline(path):
    t, fr, pts, last = 0.0, 0, [(0.0, 0)], None
    for l in open(path, errors="replace"):
        m = re.search(r"\[bb-v28-lcd\] fps_x10=(\d+) frames=(\d+)", l)
        if m and int(m.group(1)):
            last = int(m.group(2)) / (int(m.group(1)) / 10.0)
        m = re.search(r"\[bb-v93-game\] fps_x10=(\d+) changed-fields=(\d+)/", l)
        if m and last:
            t += last; fr += int(m.group(2)); pts.append((t, fr)); last = None
    return pts


def when(pts, f):
    for (t0, f0), (t1, f1) in zip(pts, pts[1:]):
        if f1 >= f:
            return t0 + (t1 - t0) * (f - f0) / max(1, f1 - f0)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="+")
    ap.add_argument("--from", dest="f0", type=int, default=100)
    ap.add_argument("--to", dest="f1", type=int, default=1100)
    ap.add_argument("--step", type=int, default=200)
    ap.add_argument("--name", action="append", default=[])
    a = ap.parse_args()
    runs = []
    for i, path in enumerate(a.logs):
        name = a.name[i] if i < len(a.name) else path.replace("\\", "/").split("/")[-1].replace("-console.txt", "")
        pts = timeline(path)
        runs.append((name, pts, when(pts, a.f0), pts[-1][1] if pts else 0))
    ok = [r for r in runs if r[2] is not None]
    # v2: every run is compared over the SAME frames - up to the furthest frame all of them reached
    end = min([a.f1] + [r[3] for r in ok]) if ok else a.f1
    marks = list(range(a.f0 + a.step, end + 1, a.step))
    if not marks or marks[-1] != end:
        marks.append(end)
    print("seconds from demo frame %d to frame N (lower is faster; same demo frames in every run)" % a.f0)
    if end < a.f1:
        print("note: a run stopped early - all runs compared over frames %d-%d (not %d-%d)" % (a.f0, end, a.f0, a.f1))
    print("%-28s" % "run" + "".join("%8d" % m for m in marks) + "   s/100 frames   frames logged")
    base = None
    rates = {}
    for name, pts, t0, reach in runs:
        if t0 is None:
            print("%-28s did not reach frame %d (%d frames logged)" % (name, a.f0, reach)); continue
        row = []
        for m in marks:
            tm = when(pts, m)
            row.append(None if tm is None else tm - t0)
        rate = 100.0 * row[-1] / (end - a.f0) if row[-1] is not None and end > a.f0 else None
        cmp = ""
        if rate is not None:
            if base is None: base = rate
            else: cmp = "  (%+.1f%% vs first)" % (100.0 * (rate / base - 1.0))
        print("%-28s" % name + "".join(("%8.0f" % v) if v is not None else "       -" for v in row)
              + ("   %8.1f" % rate if rate else "          -") + "     %6d%s" % (reach, cmp))
        if rate is not None:
            rates.setdefault(name, []).append(rate)
    if any(len(v) > 1 for v in rates.values()):
        # v3: repeated names = repeated runs of one build: mean and spread per build
        print("per build (same frames for every run):")
        first = None
        for name, v in rates.items():
            m = sum(v) / len(v)
            if first is None: first = m
            print("  %-12s n=%d  mean %6.1f s/100 frames  (runs %s)%s" % (
                name, len(v), m, ", ".join("%.1f" % x for x in v),
                "" if m == first else "  %+.1f%% vs %s" % (100.0 * (m / first - 1.0), next(iter(rates)))))
    print("noise: the same binary measured 483 s and 465 s to frame 900 (3.8%) - single-run differences")
    print("       below ~4% are not significant; repeat runs or compare profiles for small changes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
