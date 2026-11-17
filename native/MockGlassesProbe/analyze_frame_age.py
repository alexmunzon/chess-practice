#!/usr/bin/env python3
"""Summarise one frame-age harness run (Documents/frame-age-report.json) into per-method counts.

usage: analyze_frame_age.py REPORT.json [--json OUT.json]

Ground truth: a frame's hold = time it was judged - time of its SDK callback. A frame is STALE for a method when
the harness injected a delay and the actual hold exceeded that method's age limit (method 1: nonceMaxAge;
method 2: offsetMaxExcess; method 3: limit). Fresh = no injected delay. Polls judge the latest delivered frame
every 100 ms; a poll is stale when that frame's age exceeds the limit. Method 1 is scored only on frames from the
first 30 s of a stream: the test video has 15 codes that repeat every 30 s, and the rule bounds a repeated code by
its first display, so every later frame is rejected by design (reported separately).
"""
import argparse
import json
import math
from collections import defaultdict

METHODS = [("m1", "Method 1 nonce"), ("m2", "Method 2 offset (10 s window)"), ("m2whole", "Method 2 offset (whole-stream min)"),
           ("m3", "Method 3 budget+liveness"), ("all", "All three (m1, m2 whole, m3)"),
           ("m1readback", "Method 1 nonce re-judged offline with the readback display log")]


def limit_for(method, cfg):
    return {"m1": cfg["nonceMaxAge"], "m1readback": cfg["nonceMaxAge"], "m2": cfg["offsetMaxExcess"], "m2whole": cfg["offsetMaxExcess"],
            "m3": cfg["limit"], "all": min(cfg["nonceMaxAge"], cfg["offsetMaxExcess"], cfg["limit"])}[method]


def accepted(rec, method):
    if method == "all":
        return rec["m1"]["accept"] and rec["m2whole"]["accept"] and rec["m3"]["accept"]
    return rec[method]["accept"]


def frac(n, m):
    return f"{n} of {m}"


def nonce_evaluate(first_display, code, frame_epoch, gate_epoch, now, max_age, margin):
    """Python port of NonceAgeGate.evaluate (FrameAgeRules.swift). `first_display(code, now)` returns the earliest
    logged display time of `code` that is <= now, or None. Returns (accept, reason, bound)."""
    if frame_epoch != gate_epoch or gate_epoch <= 0:
        return False, "other-stream", None
    if code is None:
        return False, "unreadable-code", None
    first = first_display(code, now)
    if first is None:
        return False, "code-never-displayed", None
    bound = now - first + margin
    return (True, "ok", bound) if bound <= max_age else (False, "too-old", bound)


def display_logs(frames, cfg):
    """Two display logs per stream (epoch), each a function (epoch) -> (code, now) -> earliest display <= now.
    modelled: what the harness logged, "code N shown at anchor + slotSeconds * N" (anchor = first callback - PTS).
    readback: the earliest SDK callback whose picture showed code N (any frame, delivered or not). A correct log is
    never later than a picture that already shows the code, so readback is the latest a correct log may be."""
    anchors, seen = {}, {}
    for f in sorted(frames, key=lambda x: x["id"]):
        if f["pts"] is not None and f["epoch"] not in anchors:
            anchors[f["epoch"]] = f["sdkTime"] - f["pts"]
        if f["code"] is not None:
            k = (f["epoch"], f["code"])
            seen[k] = min(seen.get(k, math.inf), f["sdkTime"])

    def modelled(e):
        def first(code, now):
            if e not in anchors or not 0 <= code < cfg["codes"]:
                return None
            t = anchors[e] + cfg["slotSeconds"] * code
            return t if t <= now else None
        return first

    def readback(e):
        def first(code, now):
            t = seen.get((e, code))
            return t if t is not None and t <= now else None
        return first
    return anchors, seen, modelled, readback


def display_log_lateness(frames, cfg):
    """Harness timing error of method 1: for each stream and code, modelled display time minus the earliest callback
    whose picture already showed that code. Positive = the log says the code appeared after a picture showed it."""
    anchors, seen, modelled, _ = display_logs(frames, cfg)
    rows = []
    for (e, code), t in seen.items():
        m = modelled(e)(code, math.inf)
        if m is not None:
            rows.append(m - t)
    rows.sort()
    return {"codesCompared": len(rows), "maxLateMs": round(1000 * rows[-1], 1) if rows else None,
            "minLateMs": round(1000 * rows[0], 1) if rows else None,
            "codesLaterThanMargin": frac(sum(x > cfg["nonceMargin"] for x in rows), len(rows))}


def rescore_nonce(r, cfg, log):
    """Re-judges every delivered frame and poll with method 1 against display log `log` (modelled or readback)."""
    frames = r["frames"]
    by_id = {f["id"]: f for f in frames}
    _, _, modelled, readback = display_logs(frames, cfg)
    pick = modelled if log == "modelled" else readback

    def judge(code, epoch, current, now):
        return nonce_evaluate(pick(current), code, epoch, current, now, cfg["nonceMaxAge"], cfg["nonceMargin"])
    out = {}
    for f in frames:
        if f.get("delivered"):
            out[("f", f["id"])] = judge(f["code"], f["epoch"], f["currentEpoch"], f["evalTime"])
    for i, p in enumerate(r["polls"]):
        f = by_id[p["frameID"]]
        out[("p", i)] = judge(f["code"], p["epoch"], p["currentEpoch"], p["t"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("report")
    ap.add_argument("--json")
    a = ap.parse_args()
    r = json.load(open(a.report))
    cfg = r["config"]
    frames = r["frames"]
    delivered = [f for f in frames if f.get("delivered")]
    anchors = {}
    for f in sorted(frames, key=lambda x: x["id"]):
        if f["pts"] is not None and f["epoch"] not in anchors:
            anchors[f["epoch"]] = f["sdkTime"] - f["pts"]
    out = {"complete": r.get("complete"), "steps": [s["name"] + (":ok" if s["ok"] else ":FAIL " + s.get("error", "")) for s in r["steps"]],
           "framesTotal": len(frames), "framesDelivered": len(delivered), "config": cfg, "methods": {}}

    # Harness timing self-check for method 1 and an offline re-judgement with the readback display log.
    timing = display_log_lateness(frames, cfg)
    modelled = rescore_nonce(r, cfg, "modelled")
    readback = rescore_nonce(r, cfg, "readback")
    recorded = {("f", f["id"]): f["m1"]["accept"] for f in delivered}
    recorded.update({("p", i): p["m1"]["accept"] for i, p in enumerate(r["polls"])})
    timing["pythonPortAgreesWithRecordedSwiftVerdicts"] = frac(sum(modelled[k][0] == v for k, v in recorded.items()), len(recorded))
    timing["refuseMethod1"] = timing["maxLateMs"] is not None and timing["maxLateMs"] > 1000 * cfg["nonceMargin"]
    out["harnessTiming"] = timing
    for f in delivered:
        ok, why, v = readback[("f", f["id"])]
        f["m1readback"] = {"accept": ok, "reason": why, "value": v}
    for i, p in enumerate(r["polls"]):
        ok, why, v = readback[("p", i)]
        p["m1readback"] = {"accept": ok, "reason": why, "value": v}

    def in_scope(f, method):
        return method not in ("m1", "all", "m1readback") or (f["pts"] is not None and f["pts"] < 30.0)

    for method, title in METHODS:
        lim = limit_for(method, cfg)
        m = {"title": title, "ageLimit": lim}
        stale = [f for f in delivered if f["mode"] != "fresh" and f["hold"] > lim and in_scope(f, method)]
        within = [f for f in delivered if f["mode"] != "fresh" and f["hold"] <= lim and in_scope(f, method)]
        fresh = [f for f in delivered if f["mode"] == "fresh" and in_scope(f, method)]
        m["staleRejected"] = frac(sum(not accepted(f, method) for f in stale), len(stale))
        m["staleAccepted"] = [{"id": f["id"], "scenario": f["scenario"], "mode": f["mode"], "hold": round(f["hold"], 3),
                               "nominal": f["nominalDelay"]} for f in stale if accepted(f, method)][:40]
        m["staleAcceptedByScenario"] = {}
        by = defaultdict(lambda: [0, 0])
        for f in stale:
            key = f["scenario"] if f["scenario"] != "isolated" else f"isolated-{f['mode']}"
            by[key][1] += 1
            by[key][0] += accepted(f, method)
        m["staleAcceptedByScenario"] = {k: frac(*v) for k, v in sorted(by.items())}
        m["delayedWithinLimitAccepted"] = frac(sum(accepted(f, method) for f in within), len(within))
        m["freshWronglyRejected"] = frac(sum(not accepted(f, method) for f in fresh), len(fresh))
        reasons = defaultdict(int)
        for f in fresh:
            if not accepted(f, method) and method != "all":
                reasons[f[method]["reason"]] += 1
        m["freshRejectReasons"] = dict(reasons)
        # Fresh frames in steady state: not the first 2 s of a stream, not after a gap scenario.
        steady = [f for f in fresh if f["sdkTime"] - anchors.get(f["epoch"], -1e9) > 2.0 and not f["scenario"].startswith(("fresh-after", "after-", "end"))]
        m["freshSteadyWronglyRejected"] = frac(sum(not accepted(f, method) for f in steady), len(steady))
        if method in ("m1", "all", "m1readback"):
            late = [f for f in delivered if f["mode"] == "fresh" and not in_scope(f, method)]
            m["freshAfterCodeWrapRejected"] = frac(sum(not accepted(f, method) for f in late), len(late)) if method != "all" else "n/a"
        # Per nominal delay and mode (isolated scenario): how many accepted.
        table = defaultdict(lambda: [0, 0, 0])  # accepted, total, stale
        for f in delivered:
            if f["scenario"] == "isolated" and f["mode"] != "fresh" and in_scope(f, method):
                k = f"{f['mode']}-{f['nominalDelay']}"
                table[k][0] += accepted(f, method); table[k][1] += 1; table[k][2] += f["hold"] > lim
        m["isolatedByDelay"] = {k: {"accepted": v[0], "frames": v[1], "staleByActualHold": v[2]}
                                for k, v in sorted(table.items(), key=lambda kv: (kv[0].split("-")[0], float(kv[0].split("-")[1])))}
        # Polls.
        polls = [p for p in r["polls"] if method not in ("m1", "all") or True]
        pst = [p for p in polls if p["age"] > lim]
        pf = [p for p in polls if p["age"] <= lim]
        pacc = (lambda p: p["m1"]["accept"] and p["m2whole"]["accept"] and p["m3"]["accept"]) if method == "all" else (lambda p: p[method]["accept"])
        m["pollStaleRejected"] = frac(sum(not pacc(p) for p in pst), len(pst))
        m["pollStaleAcceptedByScenario"] = {}
        pb = defaultdict(lambda: [0, 0])
        for p in pst:
            pb[p["scenario"]][1] += 1; pb[p["scenario"]][0] += pacc(p)
        m["pollStaleAcceptedByScenario"] = {k: frac(*v) for k, v in sorted(pb.items()) if v[0]}
        m["pollWithinLimitRejected"] = frac(sum(not pacc(p) for p in pf), len(pf))
        if method in ("m1", "all") and timing["refuseMethod1"]:
            # The harness's own display-log error exceeds the margin under test: these counts measure the harness.
            m = {"title": title, "scored": False, "recordedNotScored": m,
                 "refused": f"display log up to {timing['maxLateMs']} ms late, more than the {1000 * cfg['nonceMargin']:.0f} ms margin"}
        out["methods"][method] = m

    # Gap watchdog: polls during drop scenarios and during fold / power-off.
    wd = {}
    for p in r["polls"]:
        s = p["scenario"]
        if s.startswith("drop-") or s in ("fold", "power-off", "doff"):
            d = wd.setdefault(s, {"polls": 0, "m3Accepted": 0, "maxAgeSeen": 0.0, "acceptedAges": []})
            d["polls"] += 1; d["maxAgeSeen"] = max(d["maxAgeSeen"], round(p["age"], 3))
            if p["m3"]["accept"]:
                d["m3Accepted"] += 1; d["acceptedAges"].append(round(p["age"], 3))
    for d in wd.values():
        d["acceptedAgeMax"] = max(d["acceptedAges"]) if d["acceptedAges"] else None
        d["acceptedAges"] = d["acceptedAges"][:10]
    # Gap polls: no frame arrived (drops, fold, power-off) and the latest frame is older than maxGap.
    over = [p for p in r["polls"] if p["age"] > cfg["maxGap"] and (p["scenario"].startswith("drop-") or p["scenario"] in ("fold", "power-off"))]
    out["watchdogGapPollsOlderThanMaxGapAcceptedByM3"] = frac(sum(p["m3"]["accept"] for p in over), len(over))
    out["watchdog"] = wd

    # Timestamp behaviour per stream and across mock events.
    streams = {}
    for e in sorted({f["epoch"] for f in frames}):
        fs = sorted([f for f in frames if f["epoch"] == e], key=lambda x: x["sdkTime"])
        pts = [f["pts"] for f in fs if f["pts"] is not None]
        t = [f["sdkTime"] for f in fs if f["pts"] is not None]
        gaps = [b - a for a, b in zip(t, t[1:])]
        offs = [ti - pi for ti, pi in zip(t, pts)]
        streams[e] = {"frames": len(fs), "firstPts": pts[0] if pts else None, "lastPts": pts[-1] if pts else None,
                      "strictlyIncreasingInCallbackOrder": all(b > a for a, b in zip(pts, pts[1:])),
                      "ptsSecondsPerCallbackSecond": round((pts[-1] - pts[0]) / (t[-1] - t[0]), 5) if len(pts) > 1 and t[-1] > t[0] else None,
                      "maxCallbackGap": round(max(gaps), 3) if gaps else None,
                      "callbackMinusPtsSpread": round(max(offs) - min(offs), 4) if offs else None,
                      "callbackMinusPtsP99MinusMin": round(sorted(offs)[int(0.99 * (len(offs) - 1))] - min(offs), 4) if offs else None}
    out["streams"] = streams
    events = sorted(r["events"], key=lambda x: x["uptime"])
    actions = [ev for ev in events if ev["kind"] == "action"]
    around = []
    allf = sorted(frames, key=lambda x: x["sdkTime"])
    for i, ev in enumerate(actions):
        nxt = actions[i + 1]["uptime"] if i + 1 < len(actions) else math.inf
        before = [f for f in allf if f["sdkTime"] < ev["uptime"]]
        after = [f for f in allf if ev["uptime"] <= f["sdkTime"] < nxt]
        b = before[-1] if before else None
        a0 = after[0] if after else None
        around.append({"action": ev["value"], "framesUntilNextAction": len(after),
                       "lastBefore": b and {"epoch": b["epoch"], "pts": b["pts"]},
                       "firstAfter": a0 and {"epoch": a0["epoch"], "pts": a0["pts"], "secondsAfterAction": round(a0["sdkTime"] - ev["uptime"], 3)},
                       "ptsAdvanceEqualsTimeAdvance": (a0 and b and a0["epoch"] == b["epoch"] and a0["pts"] is not None and b["pts"] is not None
                                                       and abs((a0["pts"] - b["pts"]) - (a0["sdkTime"] - b["sdkTime"])) < 0.1)})
    out["eventsTimestamps"] = around
    out["streamStateEvents"] = [f"{ev['kind']}={ev['value']}" for ev in events if ev["kind"].startswith(("stream-", "first-frame"))]

    # Method 1 readback.
    coded = [f for f in frames if f["pts"] is not None]
    readable = [f for f in coded if f["code"] is not None]
    exp = lambda f: int((f["pts"] % 30.0) // cfg["slotSeconds"]) % cfg["codes"]
    match = [f for f in readable if f["code"] == exp(f)]
    near = lambda f: min((f["pts"] % cfg["slotSeconds"]), cfg["slotSeconds"] - (f["pts"] % cfg["slotSeconds"])) <= 0.07
    mism = [f for f in readable if f["code"] != exp(f)]
    out["readback"] = {"decoded": frac(len(readable), len(coded)), "equalsSlotFromPts": frac(len(match), len(readable)),
                       "mismatchesWithin70msOfSlotBoundary": frac(sum(near(f) for f in mism), len(mism)),
                       "abstainReasons": dict(defaultdict(int, {k: sum(1 for f in coded if f["code"] is None and f["codeReason"] == k) for k in {f["codeReason"] for f in coded if f["code"] is None}}))}
    cor = defaultdict(lambda: {"correct": 0, "abstained": 0, "misread": 0})
    for c in r["corruption"]:
        for variant, result in c["results"].items():
            key = "correct" if result == "correct" else "misread" if result.startswith("MISREAD") else "abstained"
            cor[variant][key] += 1
    out["corruption"] = dict(cor)
    text = json.dumps(out, indent=1)
    if a.json:
        open(a.json, "w").write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
