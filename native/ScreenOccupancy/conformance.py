#!/usr/bin/env python3
"""Conformance: Swift screen-occupancy (rectify + square reader v3) versus the frozen Python reference.

Uses TRUE corners from truth/games.json (so the corner finder is not a variable), development splits only
(smoke, dev in scenes/; smoke2, dev2 in scenes-v2/). Held-out splits are refused and their images never opened.
Per game: Python rectifies every picture (screen_pipeline.rectify), runs the 4-rotation start test on every
start picture (occupancy_classifier_v3.calibrate), classifies every other picture with the first accepted
calibration; the Swift CLI does the same in ONE batch process per game. A cross-check batch feeds Python's
panels and Python's calibration to Swift, to tell rectification differences from classifier differences.

Run (from the repo root, outside any sandbox):
  python3 -B native/ScreenOccupancy/conformance.py --binary BIN --out DIR [--splits smoke,dev,smoke2,dev2]
  python3 -B native/ScreenOccupancy/conformance.py --binary BIN --out DIR --determinism   # dev twice + speed
  python3 -B native/ScreenOccupancy/conformance.py --binary BIN --out DIR --controls      # negative controls
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import time

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/recognition'))
import occupancy_classifier_v3 as v3  # noqa: E402  (frozen reference)
import screen_pipeline as sp  # noqa: E402  (rectify, corner order, rotation helpers)

FROZEN_SHA = 'c634a76de4b423996b9f847d99ce9c802b6c03ac18de60cb8558b485247926ee'  # v3.1 (sharpness-reference fix); v3.0 was 16c14a0a...685c3
DATA = Path('/Users/alexmunzon/chess-builds/pipeline-2026-11-15')
SPLITS = {'smoke': 'scenes', 'dev': 'scenes', 'smoke2': 'scenes-v2', 'dev2': 'scenes-v2'}
FORBIDDEN = ('heldout', 'heldout2', 'stressheld')
SHORT = {'empty': '.', 'white': 'w', 'black': 'b', 'unknown': '?'}
LONG = {v: k for k, v in SHORT.items()}
SQ = v3.SQUARES


def screen_setup(true_corners):
    """True a8,h8,h1,a1 corners -> (detector-order corners, rotation r with rotate(screen, r) == a8,h8,h1,a1)."""
    screen = sp.order_like_detector(true_corners)
    ref = np.asarray(true_corners, float)
    shifts = [float(np.mean(np.linalg.norm(np.asarray(sp.rotate(screen, r)) - ref, axis=1))) for r in range(4)]
    return screen, int(np.argmin(shifts))


def occ_a8(fen):
    o = v3.occupancy_from_fen(fen)
    return [o[s] for s in SQ]


def py_start(panel, fen):
    """4-rotation start test exactly as the pipeline. Returns (accepted r or None, cal, rotations that calibrated)."""
    ok = []
    for r in range(4):
        try:
            ok.append((r, v3.calibrate(panel, dict(zip(SQ, sp.screen_from_a8(occ_a8(fen), r))))))
        except v3.CalibrationError:
            pass
    return (ok[0][0], ok[0][1], [r for r, _ in ok]) if len(ok) == 1 else (None, None, [r for r, _ in ok])


def run_swift(binary, jobs, path):
    path.write_text(''.join(json.dumps(j) + '\n' for j in jobs))
    proc = subprocess.run([str(binary), 'batch', '--jobs', str(path)], capture_output=True, text=True)
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    lines = proc.stdout.splitlines()
    if len(lines) != len(jobs):
        raise RuntimeError(f'swift returned {len(lines)} results for {len(jobs)} jobs')
    return [json.loads(x) for x in lines], lines


def strip_timings(line):
    return line.split(', "timingsMs"')[0]


def games_of(split):
    if split in FORBIDDEN or split not in SPLITS:
        raise SystemExit(f'split {split!r} is not a development split')
    doc = json.loads((DATA / SPLITS[split] / 'truth/games.json').read_text())
    return [g for g in doc['games'] if g['split'] == split], DATA / SPLITS[split]


def compare_game(binary, game, root, work):
    """Returns per-game record with calibration decisions, per-frame comparisons and panel differences."""
    frames = sorted(game['frames'], key=lambda f: f['index'])
    tmp = work / 'tmp' / game['id']
    tmp.mkdir(parents=True, exist_ok=True)
    py_panels, setup, py_ms = {}, {}, {}
    for f in frames:
        screen, r = screen_setup(f['corners'])
        setup[f['index']] = (screen, r)
        t = time.perf_counter()
        img = np.asarray(Image.open(root / f['file']).convert('RGB'), np.float32)
        t1 = time.perf_counter()
        py_panels[f['index']] = sp.rectify(img, screen)
        py_ms[f['index']] = {'rectify': (time.perf_counter() - t1) * 1000}
        py_panels[f['index']].save(tmp / f"py-{f['index']:03d}.png", compress_level=1)
    starts = [f for f in frames if f.get('positionIndex', f['index']) == 0]  # start pictures (pipeline rule)
    py_dec, cal_py, cal_frame = {}, None, None
    for f in starts:
        r, cal, okl = py_start(py_panels[f['index']], game['startFen'])
        py_dec[f['index']] = {'accepted': r, 'calibrated': okl}
        if cal_py is None and r is not None:
            cal_py, cal_frame, cal_r = cal, f['index'], r
    jobs, xjobs = [], []
    for f in starts:
        screen, _ = setup[f['index']]
        base = {'op': 'calibrate', 'rotation': 'auto', 'fen': game['startFen']}
        jobs.append({**base, 'id': f'cal-{f["index"]}', 'image': str(root / f['file']), 'corners': screen,
                     'panelOut': str(tmp / f"sw-{f['index']:03d}.png")})
        xjobs.append({**base, 'id': f'xcal-{f["index"]}', 'panel': str(tmp / f"py-{f['index']:03d}.png")})
    todo = [f for f in frames if f['index'] != cal_frame] if cal_py is not None else []
    if cal_py is not None:
        (tmp / 'py-cal.json').write_text(json.dumps(cal_py))
    for f in todo:
        screen, r = setup[f['index']]
        jobs.append({'op': 'classify', 'id': f'f{f["index"]}', 'image': str(root / f['file']), 'corners': screen,
                     'rotation': r, 'calibrationRef': f'cal-{cal_frame}',
                     'panelOut': str(tmp / f"sw-{f['index']:03d}.png")})
        xjobs.append({'op': 'classify', 'id': f'x{f["index"]}', 'panel': str(tmp / f"py-{f['index']:03d}.png"),
                      'rotation': r, 'calibration': str(tmp / 'py-cal.json')})
    sw, _ = run_swift(binary, jobs, tmp / 'jobs.jsonl')
    xs, _ = run_swift(binary, xjobs, tmp / 'xjobs.jsonl')
    swd = {o['id']: o for o in sw}
    xsd = {o['id']: o for o in xs}
    rec = {'game': game['id'], 'split': game['split'], 'difficulty': game.get('difficulty'), 'starts': [],
           'frames': [], 'calFrame': cal_frame}
    # panels: every picture (Swift panel written by the main batch)
    pdiff = []
    for f in frames:
        a = np.asarray(py_panels[f['index']], np.int16)
        p = tmp / f"sw-{f['index']:03d}.png"
        if p.exists():
            b = np.asarray(Image.open(p).convert('RGB'), np.int16)
            d = np.abs(a - b)
            pdiff.append({'index': f['index'], 'mad': float(d.mean()), 'max': int(d.max()),
                          'fracDiff': float((d.max(axis=2) > 0).mean())})
    rec['panels'] = pdiff
    for f in starts:
        s = swd[f'cal-{f["index"]}']
        x = xsd[f'xcal-{f["index"]}']
        sw_ok = [t['rotation'] for t in s.get('rotationsTried', []) if t['calibrated']]
        x_ok = [t['rotation'] for t in x.get('rotationsTried', []) if t['calibrated']]
        rec['starts'].append({'index': f['index'], 'python': py_dec[f['index']], 'swift': {'accepted': s.get('rotation'), 'calibrated': sw_ok},
                              'swiftOnPythonPanel': {'accepted': x.get('rotation'), 'calibrated': x_ok},
                              'same': py_dec[f['index']]['accepted'] == s.get('rotation') and py_dec[f['index']]['calibrated'] == sw_ok,
                              'swiftErrors': {t['rotation']: t.get('error', '')[:160] for t in s.get('rotationsTried', []) if not t['calibrated']}})
        if f['index'] == cal_frame and s.get('ok'):
            c = s['calibration']
            rec['calibrationDelta'] = {
                'emptyRef': float(np.max(np.abs(np.asarray(c['emptyRef']) - np.asarray(cal_py['emptyRef'])))),
                'contrast': abs(c['contrast'] - cal_py['contrast']),
                'boundarySharpness': abs(c['boundarySharpness'] - cal_py['boundarySharpness']),
                'fillRef': float(max(np.max(np.abs(np.asarray(c['fillRef'][k]) - np.asarray(cal_py['fillRef'][k]))) for k in ('white', 'black')))}
    for f in todo:
        screen, r = setup[f['index']]
        t = time.perf_counter()
        res = v3.classify(py_panels[f['index']], cal_py)
        py_ms[f['index']]['classify'] = (time.perf_counter() - t) * 1000
        py_cells = [res[s] for s in SQ]
        py_a8 = sp.a8_from_screen([c['label'] for c in py_cells], r)
        py_conf_a8 = sp.a8_from_screen([c['confidence'] for c in py_cells], r)
        py_cells_a8 = sp.a8_from_screen(py_cells, r)
        s = swd[f'f{f["index"]}']
        x = xsd[f'x{f["index"]}']
        truth = occ_a8(f['fen'])
        fr = {'index': f['index'], 'file': f['file'], 'pyMs': py_ms[f['index']],
              'swMs': s.get('timingsMs'), 'swiftOk': s.get('ok', False)}
        if not s.get('ok'):
            fr['error'] = s.get('error')
            rec['frames'].append(fr)
            continue
        sw_a8 = [LONG[c] for c in s['labels']]
        sw_cells_a8 = sp.a8_from_screen(s['cells'], r)
        x_a8 = [LONG[c] for c in x['labels']] if x.get('ok') else ['?'] * 64
        diffs, conf_delta = [], 0.0
        for j in range(64):
            pl, sl = py_a8[j], sw_a8[j]
            if pl == sl:
                conf_delta = max(conf_delta, abs(py_conf_a8[j] - sw_cells_a8[j]['confidence']))
                continue
            kind = ('swift-unknown' if sl == 'unknown' else 'python-unknown' if pl == 'unknown' else 'confident-different')
            pc, sc = py_cells_a8[j], sw_cells_a8[j]
            diffs.append({'square': SQ[j], 'kind': kind, 'python': pl, 'swift': sl, 'truth': truth[j],
                          'pyConf': pc['confidence'], 'swConf': sc['confidence'],
                          'pyReasons': pc['reasons'], 'swReasons': sc['reasons'],
                          'swiftOnPythonPanel': x_a8[j],
                          'py': {k: pc.get(k) for k in ('fgFrac', 'edgeFrac', 'borderFrac', 'local', 'colourShare', 'colourDist')},
                          'sw': {k: sc.get(k) for k in ('fgFrac', 'edgeFrac', 'borderFrac', 'local', 'colourShare', 'colourDist')}})
        detail = {}
        for j in range(64):  # intermediate values, all squares: largest |Python - Swift| per measurement
            pc, sc = py_cells_a8[j], sw_cells_a8[j]
            for k in ('fgFrac', 'edgeFrac', 'borderFrac', 'saturatedFrac', 'colourShare', 'colourDist'):
                if k in pc and k in sc:
                    detail[k] = max(detail.get(k, 0.0), abs(pc[k] - sc[k]))
                elif (k in pc) != (k in sc):
                    detail[k + 'PresenceDiffers'] = detail.get(k + 'PresenceDiffers', 0) + 1
            for k in ('shift', 'step', 'side', 'unexplained'):
                if 'local' in pc and 'local' in sc:
                    detail['local.' + k] = max(detail.get('local.' + k, 0.0), abs(pc['local'][k] - sc['local'][k]))
        fr.update(diffs=diffs, maxConfDeltaAgreeing=conf_delta, maxDetailDelta=detail,
                  swiftWrong=[f'{SQ[j]}:{truth[j]}->{sw_a8[j]}' for j in range(64) if sw_a8[j] not in ('unknown', truth[j])],
                  pythonWrong=[f'{SQ[j]}:{truth[j]}->{py_a8[j]}' for j in range(64) if py_a8[j] not in ('unknown', truth[j])],
                  swUnknown=sw_a8.count('unknown'), pyUnknown=py_a8.count('unknown'),
                  crossDiffs=sum(a != b for a, b in zip(py_a8, x_a8)), crossOk=x.get('ok', False))
        rec['frames'].append(fr)
    shutil.rmtree(tmp)
    return rec


def summarise(recs):
    out = {}
    for split in sorted({r['split'] for r in recs}, key=list(SPLITS).index):
        rs = [r for r in recs if r['split'] == split]
        fr = [f for r in rs for f in r['frames']]
        ok = [f for f in fr if f['swiftOk']]
        sq = 64 * len(fr)
        nd = sum(len(f['diffs']) for f in ok) + 64 * (len(fr) - len(ok))
        kinds = {}
        for f in ok:
            for d in f['diffs']:
                kinds[d['kind']] = kinds.get(d['kind'], 0) + 1
        starts = [s for r in rs for s in r['starts']]
        panels = [p for r in rs for p in r['panels']]
        out[split] = {
            'games': len(rs), 'gamesPythonAccepted': sum(r['calFrame'] is not None for r in rs),
            'startPictures': len(starts), 'startDecisionsIdentical': sum(s['same'] for s in starts),
            'pictures': len(fr), 'squares': sq, 'swiftFailedPictures': len(fr) - len(ok),
            'identicalLabelsPct': round(100 * (sq - nd) / sq, 4) if sq else None,
            'swiftUnknownPythonConfident': kinds.get('swift-unknown', 0),
            'pythonUnknownSwiftConfident': kinds.get('python-unknown', 0),
            'confidentDifferent': kinds.get('confident-different', 0),
            'swiftWrongVsTruth': sum(len(f.get('swiftWrong', [])) for f in fr),
            'pythonWrongVsTruth': sum(len(f.get('pythonWrong', [])) for f in fr),
            'swiftUnknown': sum(f.get('swUnknown', 0) for f in ok), 'pythonUnknown': sum(f.get('pyUnknown', 0) for f in ok),
            'crossCheckDiffs(swift on python panel+cal)': sum(f.get('crossDiffs', 0) for f in ok),
            'maxConfidenceDeltaWhereLabelsAgree': max([f['maxConfDeltaAgreeing'] for f in ok], default=0),
            'maxDetailDelta': {k: max(f.get('maxDetailDelta', {}).get(k, 0) for f in ok)
                               for k in sorted({k for f in ok for k in f.get('maxDetailDelta', {})})},
            'panelMeanAbsDiff': round(statistics.mean(p['mad'] for p in panels), 9) if panels else None,
            'panelMaxAbsDiff': max((p['max'] for p in panels), default=None),
            'panelPixelsDifferingPct': round(100 * statistics.mean(p['fracDiff'] for p in panels), 7) if panels else None,
            'calibrationMaxDelta': {k: max((r.get('calibrationDelta', {}).get(k, 0) for r in rs), default=0)
                                    for k in ('emptyRef', 'contrast', 'boundarySharpness', 'fillRef')}}
    return out


def check_policy(binary):
    sw = json.loads(subprocess.run([str(binary), 'policy'], capture_output=True, text=True, check=True).stdout)
    py = json.loads(json.dumps(v3.policy()))
    bad = [k for k in set(py) | set(sw) if k not in py or k not in sw or py[k] != sw[k]
           or type(py[k]) is not type(sw[k])]
    return {'pythonCount': len(py), 'swiftCount': len(sw), 'mismatches': bad, 'equal': not bad}


def determinism(binary, out):
    """All dev games in ONE batch process, twice; byte-identical output with timings removed; speed figures."""
    games, root = games_of('dev')
    jobs = []
    for g in games:
        frames = sorted(g['frames'], key=lambda f: f['index'])
        screen, _ = screen_setup(frames[0]['corners'])
        jobs.append({'op': 'calibrate', 'id': g['id'], 'image': str(root / frames[0]['file']), 'corners': screen,
                     'rotation': 'auto', 'fen': g['startFen']})
        for f in frames[1:]:
            screen, r = screen_setup(f['corners'])
            jobs.append({'op': 'classify', 'id': f"{g['id']}/{f['index']}", 'image': str(root / f['file']),
                         'corners': screen, 'rotation': r, 'calibrationRef': g['id']})
    runs = []
    for k in range(2):
        up = subprocess.run(['uptime'], capture_output=True, text=True).stdout.strip()
        t = time.perf_counter()
        res, lines = run_swift(binary, jobs, out / f'det-jobs.jsonl')
        runs.append({'uptimeBefore': up, 'wallS': round(time.perf_counter() - t, 1), 'lines': lines, 'res': res})
        (out / f'determinism-run{k + 1}.jsonl').write_text('\n'.join(lines) + '\n')
    a = [strip_timings(x) for x in runs[0]['lines']]
    b = [strip_timings(x) for x in runs[1]['lines']]
    timing = {}
    for name in ('decode', 'rectify', 'blur', 'classify', 'rectifyPlusClassify'):
        vals = sorted(o['timingsMs'][name] for run in runs for o in run['res'] if o['op'] == 'classify' and o.get('ok'))
        timing[name] = {'median': round(statistics.median(vals), 2), 'p95': round(vals[int(0.95 * (len(vals) - 1))], 2), 'n': len(vals)}
    return {'jobs': len(jobs), 'identical': a == b, 'differingLines': sum(x != y for x, y in zip(a, b)),
            'sha256': [hashlib.sha256('\n'.join(x).encode()).hexdigest() for x in (a, b)],
            'runs': [{k: v for k, v in r.items() if k in ('uptimeBefore', 'wallS')} for r in runs],
            'uptimeAfter': subprocess.run(['uptime'], capture_output=True, text=True).stdout.strip(),
            'timingMsPerPicture': timing, 'okClassify': sum(o['op'] == 'classify' and o.get('ok', False) for o in runs[0]['res'])}


def controls(binary, out):
    """Negative controls through the Swift CLI next to Python on dev start pictures (true corners)."""
    games, root = games_of('dev')
    tmp = out / 'controls'
    tmp.mkdir(parents=True, exist_ok=True)
    rows = []
    for g in games[:4]:
        f = sorted(g['frames'], key=lambda f: f['index'])[0]
        screen, r = screen_setup(f['corners'])
        img = np.asarray(Image.open(root / f['file']).convert('RGB'), np.float32)
        panel = sp.rectify(img, screen)
        start = occ_a8(g['startFen'])
        cases = []
        for sqn, other in (('e2', 'empty'), ('e4', 'white'), ('d8', 'white'), ('a5', 'black')):
            o = list(start); o[SQ.index(sqn)] = other
            cases.append((f'one-square-off {sqn}={other}', panel, o, r))
        cases.append(('swapped colours', panel, [{'white': 'black', 'black': 'white'}.get(x, x) for x in start], r))
        for wrong in (1, 2, 3):
            cases.append((f'wrong rotation r+{wrong}', panel, start, (r + wrong) % 4))
        cases.append(('board turned 90 (panel rotated)', panel.rotate(90), start, r))
        hand = panel.copy()
        sq_screen = sp.screen_from_a8(SQ, r).index('c2')  # tile that shows c2 on the screen panel
        x0, y0 = 64 + (sq_screen % 8) * 64, 64 + (sq_screen // 8) * 64
        ImageDraw.Draw(hand).ellipse((x0 - 10, y0 + 10, x0 + 120, y0 + 140), fill=(196, 150, 120))
        cases.append(('hand over pieces', hand, start, r))
        d7 = sp.screen_from_a8(SQ, r).index('d7')
        a = np.asarray(panel, float)
        yy, xx = np.mgrid[0:640, 0:640]
        cx, cy = 64 + (d7 % 8) * 64 + 32, 64 + (d7 // 8) * 64 + 32
        glare = Image.fromarray(np.clip(a + 200 * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * 30 ** 2))[..., None], 0, 255).astype(np.uint8))
        cases.append(('glare over pieces', glare, start, r))
        cases.append(('correct claim (positive control)', panel, start, r))
        jobs = []
        for k, (name, p, occ, rot) in enumerate(cases):
            path = tmp / f"{g['id']}-{k}.png"
            p.save(path)
            jobs.append({'op': 'calibrate', 'id': name, 'panel': str(path), 'rotation': rot,
                         'occupancy': ''.join({'empty': 'e', 'white': 'w', 'black': 'b'}[x] for x in occ)})
        sw, _ = run_swift(binary, jobs, tmp / 'jobs.jsonl')
        for (name, p, occ, rot), s in zip(cases, sw):
            try:
                v3.calibrate(p, dict(zip(SQ, sp.screen_from_a8(occ, rot))))
                py_ok, py_err = True, ''
            except v3.CalibrationError as e:
                py_ok, py_err = False, str(e)[:100]
            rows.append({'game': g['id'], 'case': name, 'pythonAccepted': py_ok, 'swiftAccepted': bool(s.get('ok')),
                         'same': py_ok == bool(s.get('ok')), 'pythonError': py_err,
                         'swiftError': (s.get('rotationsTried') or [{}])[0].get('error', s.get('error', ''))[:100]})
    shutil.rmtree(tmp)
    return {'rows': rows, 'allSame': all(r['same'] for r in rows),
            'negativesRejectedBySwift': all(not r['swiftAccepted'] for r in rows if not r['case'].startswith('correct'))}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--binary', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--splits', default='smoke,dev,smoke2,dev2')
    ap.add_argument('--games', default='', help='comma-separated game ids (default all in the splits)')
    ap.add_argument('--determinism', action='store_true')
    ap.add_argument('--controls', action='store_true')
    a = ap.parse_args()
    sha = hashlib.sha256((ROOT / 'scripts/recognition/occupancy_classifier_v3.py').read_bytes()).hexdigest()
    if sha != FROZEN_SHA:
        raise SystemExit(f'occupancy_classifier_v3.py sha256 {sha} differs from the frozen {FROZEN_SHA}')
    a.out.mkdir(parents=True, exist_ok=True)
    if a.determinism:
        rep = determinism(a.binary, a.out)
        (a.out / 'determinism.json').write_text(json.dumps(rep, indent=1))
        print(json.dumps({k: v for k, v in rep.items()}, indent=1))
        return
    if a.controls:
        rep = controls(a.binary, a.out)
        (a.out / 'controls.json').write_text(json.dumps(rep, indent=1))
        for r in rep['rows']:
            print(f"{r['game']:10s} {r['case']:34s} python={'accept' if r['pythonAccepted'] else 'reject'} "
                  f"swift={'accept' if r['swiftAccepted'] else 'reject'} {'' if r['same'] else 'DIFFERENT'}")
        print(json.dumps({k: v for k, v in rep.items() if k != 'rows'}))
        return
    pol = check_policy(a.binary)
    print('policy', json.dumps(pol), flush=True)
    recs = []
    want = set(filter(None, a.games.split(',')))
    for split in a.splits.split(','):
        games, root = games_of(split)
        for g in games:
            if want and g['id'] not in want:
                continue
            t = time.perf_counter()
            rec = compare_game(a.binary, g, root, a.out)
            recs.append(rec)
            nd = sum(len(f.get('diffs', [])) for f in rec['frames'])
            print(f"{g['id']}: {len(rec['frames'])} frames, starts same {sum(s['same'] for s in rec['starts'])}/{len(rec['starts'])}, "
                  f"label diffs {nd}, swift wrong {sum(len(f.get('swiftWrong', [])) for f in rec['frames'])}, "
                  f"{time.perf_counter() - t:.0f} s", flush=True)
            (a.out / 'conformance-games.json').write_text(json.dumps(recs))
    summary = summarise(recs)
    disagreements = [{'game': r['game'], 'index': f['index'], **d} for r in recs for f in r['frames'] for d in f.get('diffs', [])]
    report = {'schema': 'screen-occupancy-conformance-v1', 'frozenSha256': sha, 'policy': pol,
              'screenPipelineSha256': hashlib.sha256((ROOT / 'scripts/recognition/screen_pipeline.py').read_bytes()).hexdigest(),
              'uptime': subprocess.run(['uptime'], capture_output=True, text=True).stdout.strip(),
              'summary': summary, 'disagreements': disagreements,
              'startDecisionMismatches': [{'game': r['game'], **s} for r in recs for s in r['starts'] if not s['same']],
              'note': 'simulated pictures, true corners, development splits only; held-out never read'}
    (a.out / 'conformance.json').write_text(json.dumps(report, indent=1))
    print(json.dumps(summary, indent=1))
    print(f'{len(disagreements)} label disagreements; details in {a.out / "conformance.json"}')


if __name__ == '__main__':
    main()
