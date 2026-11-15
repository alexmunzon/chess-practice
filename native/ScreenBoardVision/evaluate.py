#!/usr/bin/env python3
"""Scores screen-board-detect against make_screen_scenes.py truth.

Corner error is matched over the 4 cyclic rotations (orientation is out of scope).
'Within X%' and 'false accept' use the WORST of the 4 corners, as a percent of the mean
board side length of the truth quad. A false accept is found=true with worst error > 5%.
"""
import argparse
import json
import math
import subprocess
from pathlib import Path

import numpy as np


def run(binary, root, rows, chunk=40):
    out = {}
    for i in range(0, len(rows), chunk):
        paths = [str(root / r['file']) for r in rows[i:i+chunk]]
        res = subprocess.run([binary, *paths], capture_output=True, text=True, check=True)
        for line in res.stdout.splitlines():
            obj = json.loads(line)
            out[obj['image']] = obj
    return out


def score(row, det):
    if row['corners'] is None:  # negative control: any 'found' is a false accept
        return {'id': row['id'], 'split': row['split'], 'difficulty': row['difficulty'], 'negative': row['negative'],
                'found': det['found'], 'confidence': det['confidence'], 'reason': det['reason'],
                'ms': det['detectMs'], 'decodeMs': det['decodeMs']}
    truth = np.asarray(row['corners'], float)
    side = np.mean([np.linalg.norm(truth[i] - truth[(i+1) % 4]) for i in range(4)])
    entry = {'id': row['id'], 'split': row['split'], 'difficulty': row['difficulty'], 'found': det['found'],
             'confidence': det['confidence'], 'reason': det['reason'], 'ms': det['detectMs'],
             'decodeMs': det['decodeMs'], 'sidePx': round(float(side), 1),
             'hand': row.get('hand') is not None, 'glare': row.get('glare') is not None,
             'banding': row.get('banding') is not None, 'boardWidthFraction': row.get('boardWidthFraction'),
             'yaw': row.get('yawDeg'), 'pitch': row.get('pitchDeg'), 'blur': row.get('blurSigma')}
    quad = det.get('corners') or det.get('rejectedCorners')
    if quad:
        q = np.asarray(quad, float)
        best = None
        for k in range(4):
            e = np.linalg.norm(np.roll(q, k, 0) - truth, axis=1)
            if best is None or e.mean() < best.mean():
                best = e
        entry.update({'meanErrPx': float(best.mean()), 'maxErrPx': float(best.max()),
                      'maxErrPct': float(100 * best.max() / side), 'meanErrPct': float(100 * best.mean() / side)})
    return entry


def summarize(rows):
    n = len(rows)
    found = [r for r in rows if r['found']]
    good = [r for r in found if r['maxErrPct'] <= 5]
    fa = [r for r in found if r['maxErrPct'] > 5]
    def pct(x): return round(100 * x / n, 1) if n else None
    s = {'n': n, 'foundPct': pct(len(found)), 'abstainPct': pct(n - len(found)),
         'within1PctOfSide': pct(sum(r['maxErrPct'] <= 1 for r in found)),
         'within2PctOfSide': pct(sum(r['maxErrPct'] <= 2 for r in found)),
         'falseAccepts': len(fa)}
    if good:
        e = np.array([r['meanErrPx'] for r in good]); ep = np.array([r['meanErrPct'] for r in good])
        mx = np.array([r['maxErrPx'] for r in good])
        s.update({'meanCornerErrPx': round(float(e.mean()), 2), 'p95CornerErrPx': round(float(np.percentile(mx, 95)), 2),
                  'meanCornerErrPctSide': round(float(ep.mean()), 3),
                  'p95CornerErrPctSide': round(float(np.percentile([r['maxErrPct'] for r in good], 95)), 3)})
    ms = np.array([r['ms'] for r in rows])
    s.update({'meanDetectMs': round(float(ms.mean()), 1), 'p95DetectMs': round(float(np.percentile(ms, 95)), 1),
              'meanDecodeMs': round(float(np.mean([r['decodeMs'] for r in rows])), 1)})
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--binary', required=True)
    ap.add_argument('--root', default='/Users/alexmunzon/chess-builds/screen-board-2026-11-15')
    ap.add_argument('--split', choices=['dev', 'heldout', 'sanity'], required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    root = Path(args.root)
    truth = json.loads((root / 'truth' / 'truth.json').read_text())
    rows = truth['sanity'] if args.split == 'sanity' else [r for r in truth['scenes'] if r['split'] == args.split]
    dets = run(args.binary, root, rows)
    allscored = [score(r, dets[str(root / r['file'])]) for r in rows]
    scored = [r for r in allscored if 'negative' not in r]
    neg = [r for r in allscored if 'negative' in r]
    negatives = {'n': len(neg), 'falseAccepts': sum(r['found'] for r in neg),
                 'byKind': {k: {'n': sum(r['negative'] == k for r in neg),
                                'falseAccepts': sum(r['found'] for r in neg if r['negative'] == k),
                                'reasons': sorted({r['reason'] for r in neg if r['negative'] == k})}
                            for k in sorted({r['negative'] for r in neg})}}
    report = {'split': args.split, 'overall': summarize(scored), 'negatives': negatives,
              'byDifficulty': {d: summarize([r for r in scored if r['difficulty'] == d])
                               for d in sorted({r['difficulty'] for r in scored})},
              'withHand': summarize([r for r in scored if r['hand']]) if any(r['hand'] for r in scored) else None,
              'abstainReasons': {k: sum(1 for r in scored if not r['found'] and r['reason'] == k)
                                 for k in sorted({r['reason'] for r in scored if not r['found']})},
              'failures': [r for r in scored if not r['found'] or r['maxErrPct'] > 2],
              'perScene': allscored}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=1))
    print(json.dumps({k: report[k] for k in ('split', 'overall', 'negatives', 'byDifficulty', 'withHand', 'abstainReasons')}, indent=1))


if __name__ == '__main__':
    main()
