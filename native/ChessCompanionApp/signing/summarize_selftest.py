#!/usr/bin/env python3
"""Summarize a Chess Companion in-app self-test report (selftest-report.json).

Usage:
  summarize_selftest.py REPORT.json [--json] [--brief]
                        [--fresh-after-epoch SECONDS] [--not-start ISO8601]

Verdicts and exit codes (same numbers phone_selftest.sh uses):
  PASS         0  report complete, every check passed
  FAIL         2  report complete (or stopped by the app itself), some check failed
  INTERRUPTED  3  the app was deactivated/backgrounded or the engine closed under it
                  (app.willResignActive / app.didEnterBackground events, backend.closed,
                  "engine not ready" failures or a "Paused" status)
  INCOMPLETE   5  still "in progress" with no sign of interruption (running or stalled)
  STALE        1  --fresh-after-epoch / --not-start given and the report is from an older run
  (unreadable) 1

Read-only: it never changes the report.
"""
import argparse
import datetime as dt
import json
import sys

EXIT = {"PASS": 0, "FAIL": 2, "INTERRUPTED": 3, "INCOMPLETE": 5, "STALE": 1}
PLAIN = {
    "PASS": "all checks passed",
    "FAIL": "report finished but some checks failed",
    "INTERRUPTED": "the app was interrupted (screen sleep, lock or backgrounding); wake and unlock the phone, then re-run",
    "INCOMPLETE": "the self-test is still in progress or stalled",
    "STALE": "this report is from an earlier run, not the one just launched",
}
INTERRUPT_EVENTS = ("app.willResignActive", "app.didEnterBackground", "backend.closed")


def parse_iso(s):
    if not s:
        return None
    try:
        return dt.datetime.strptime(s.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S.%f%z")
    except ValueError:
        try:
            return dt.datetime.strptime(s.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z")
        except ValueError:
            return None


def analyse(r, fresh_after_epoch=None, not_start=None):
    checks = r.get("checks") or []
    events = r.get("eventLog") or []
    in_progress = r.get("incompleteReason") == "in progress"
    incomplete = bool(r.get("incomplete")) or in_progress
    passed = sum(1 for c in checks if c.get("pass") is True)
    run = len(checks)

    reasons = []
    for e in events:
        if e.get("event") in INTERRUPT_EVENTS:
            reasons.append("event %s at %s ms" % (e.get("event"), e.get("tMs")))
    not_ready = [c.get("name") for c in checks
                 if (c.get("details") or {}).get("failure") == "engine not ready"]
    if not_ready:
        reasons.append("%d check(s) failed with 'engine not ready'" % len(not_ready))
    # Only failing checks: background-handler-revokes reaches "Paused" on purpose.
    paused = [c.get("name") for c in checks
              if c.get("pass") is not True and any(isinstance(v, str) and v.startswith("Paused")
                     for v in (c.get("details") or {}).values())]
    if paused:
        reasons.append("status 'Paused' seen in %s" % ", ".join(paused))

    all_ok = (r.get("allPassed") is True and run > 0 and passed == run
              and not incomplete)
    if all_ok:
        verdict = "PASS"
    elif reasons:
        verdict = "INTERRUPTED"
    elif in_progress:
        verdict = "INCOMPLETE"
    else:
        verdict = "FAIL"

    start = parse_iso(r.get("startTime"))
    fresh = True
    stale_why = None
    if fresh_after_epoch is not None:
        if start is None or start.timestamp() <= fresh_after_epoch:
            fresh, stale_why = False, "startTime %s is not after this script's launch" % r.get("startTime")
    if fresh and not_start and r.get("startTime") == not_start:
        fresh, stale_why = False, "startTime equals the report that was on the phone before launch"
    if not fresh:
        verdict = "STALE"

    return {
        "verdict": verdict,
        "exitCode": EXIT[verdict],
        "plain": PLAIN[verdict] + (" (%s)" % stale_why if stale_why else ""),
        "fresh": fresh,
        "inProgress": in_progress,
        "incomplete": incomplete,
        "incompleteReason": r.get("incompleteReason"),
        "interruptionSigns": reasons,
        "checksPassed": passed,
        "checksRun": run,
        "reportedChecksPassed": r.get("checksPassed"),
        "reportedChecksRun": r.get("checksRun"),
        "allPassed": r.get("allPassed"),
        "device": r.get("deviceModel"),
        "os": "%s %s" % (r.get("osName", "?"), r.get("osVersion", "?")),
        "app": "%s %s (%s)" % (r.get("bundleIdentifier"), r.get("appVersion"), r.get("appBuild")),
        "startTime": r.get("startTime"),
        "endTime": r.get("endTime"),
        "speakRequests": r.get("speakRequests"),
        "checks": [{
            "name": c.get("name"), "pass": c.get("pass"),
            "move": (c.get("details") or {}).get("moveUCI"),
            "failure": (c.get("details") or {}).get("failure"),
            "timingsMs": c.get("timingsMs") or {},
        } for c in checks],
        "notableEvents": [e for e in events
                          if str(e.get("event", "")).startswith("app.")
                          or e.get("event") in ("backend.closed", "backend.close")],
    }


def fmt_timings(t):
    order = ["engineStart", "recognition", "validation", "analysis"]
    keys = [k for k in order if k in t] + sorted(k for k in t if k not in order)
    return " ".join("%s=%.0fms" % (k, t[k]) for k in keys if isinstance(t[k], (int, float)))


def main():
    ap = argparse.ArgumentParser(description="Summarize a self-test report.")
    ap.add_argument("report")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--brief", action="store_true", help="one line: VERDICT fresh|stale in_progress|done")
    ap.add_argument("--fresh-after-epoch", type=float, default=None)
    ap.add_argument("--not-start", default=None)
    a = ap.parse_args()
    try:
        with open(a.report, "rb") as f:
            r = json.loads(f.read().decode("utf-8"))
        if not isinstance(r, dict) or r.get("kind") != "chess-companion-in-app-self-test":
            raise ValueError("not a chess-companion-in-app-self-test report")
    except Exception as e:  # unreadable/partial file
        if a.brief:
            print("UNREADABLE stale in_progress")
        elif a.json:
            print(json.dumps({"verdict": "UNREADABLE", "exitCode": 1, "error": str(e)}))
        else:
            print("Could not read report: %s" % e)
        return 1
    s = analyse(r, a.fresh_after_epoch, a.not_start)
    if a.brief:
        print("%s %s %s" % (s["verdict"], "fresh" if s["fresh"] else "stale",
                            "in_progress" if s["inProgress"] else "done"))
        return s["exitCode"]
    if a.json:
        print(json.dumps(s, indent=1, sort_keys=True))
        return s["exitCode"]
    print("Device: %s, %s" % (s["device"], s["os"]))
    print("App:    %s" % s["app"])
    print("Run:    %s -> %s (incomplete=%s, reason=%s, speakRequests=%s)" % (
        s["startTime"], s["endTime"], s["incomplete"], s["incompleteReason"], s["speakRequests"]))
    print("Checks: %d/%d passed" % (s["checksPassed"], s["checksRun"]))
    for c in s["checks"]:
        extra = []
        if c["move"]:
            extra.append("move %s" % c["move"])
        if c["failure"]:
            extra.append("failure: %s" % c["failure"])
        tm = fmt_timings(c["timingsMs"])
        if tm:
            extra.append(tm)
        print("  [%s] %s%s" % ("PASS" if c["pass"] else "FAIL", c["name"],
                               ("  " + "; ".join(extra)) if extra else ""))
    if s["notableEvents"]:
        print("Events:")
        for e in s["notableEvents"]:
            rest = {k: v for k, v in e.items() if k not in ("event", "tMs")}
            print("  %8s ms  %s%s" % (e.get("tMs"), e.get("event"), ("  " + json.dumps(rest)) if rest else ""))
    else:
        print("Events: no app.* or backend.close(d) events")
    if s["interruptionSigns"]:
        print("Interruption signs: " + "; ".join(s["interruptionSigns"]))
    print("VERDICT: %s (exit %d) - %s" % (s["verdict"], s["exitCode"], s["plain"]))
    return s["exitCode"]


if __name__ == "__main__":
    sys.exit(main())
