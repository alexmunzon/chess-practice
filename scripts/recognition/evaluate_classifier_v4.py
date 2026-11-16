#!/usr/bin/env python3
"""Harness for the v4 square reader (experiment, simulated images only).

Scores occupancy_classifier_v3 (v3.1, frozen) and occupancy_classifier_v4 square by square with TRUE corners
(from the answer key) and with DETECTED corners, on DEVELOPMENT data only: smoke, dev (scenes), smoke2, dev2
(scenes-v2) and stressdev (scenes-stress). Any split whose name contains 'heldout' or 'stressheld' is refused
by name; those games are skipped without opening a picture.

  prepare   run the corner detector and cache rectified panels for every development picture that has none
            (scenes / scenes-v2 panels are reused read-only from the v3 harness cache when present)
  games     start acceptance per game + per-square scoring of every later picture; one JSON per classifier/split
  summary   v3 vs v4 tables per split and, for stressdev, per stress variant

The stress variant name is read from the answer key ONLY to group results; the readers never see it.
Rectification and geometry helpers are imported from evaluate_classifier_v3.py (a verbatim copy of the
pipeline's rectify), so both harnesses produce identical panels.
"""
import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/recognition'))
import evaluate_classifier_v3 as h3  # noqa: E402  (geometry, detector call, start check: read-only reuse)
import occupancy_classifier_v3 as v3  # noqa: E402

BASE = Path('/Users/alexmunzon/chess-builds/pipeline-2026-11-15')
ROOTS = {'scenes': BASE / 'scenes', 'scenes-v2': BASE / 'scenes-v2', 'scenes-stress': BASE / 'scenes-stress'}
SPLITS = {'smoke': 'scenes', 'dev': 'scenes', 'smoke2': 'scenes-v2', 'dev2': 'scenes-v2', 'stressdev': 'scenes-stress'}
FORBIDDEN = ('heldout', 'stressheld')
OUT = BASE / 'classifier-v4'
V3_CACHE = BASE / 'classifier-v3'
RUNS = OUT / 'round5' / 'runs'  # round 5 (v4.3); round 4 (v4.2) in OUT / 'round4' / 'runs'; round 3 (v4.1) in OUT / 'round3' / 'runs', round 2 (v4.0) in OUT / 'round2' / 'runs'
SQ = v3.SQUARES
VARIANTS = ('true', 'det')


def _allowed(split):
    if any(f in split for f in FORBIDDEN) or split not in SPLITS:
        raise SystemExit(f'refusing split {split!r}')
    return split


def classifier(name):
    if name == 'v3':
        return v3
    if name == 'v4':
        import occupancy_classifier_v4 as v4
        return v4
    raise SystemExit(f'unknown classifier {name}')


# ------------------------------------------------------------ dataset ----
def items_for(split):
    _allowed(split)
    root_name = SPLITS[split]
    root = ROOTS[root_name]
    games = []
    for g in json.loads((root / 'truth/games.json').read_text())['games']:
        if g['split'] != split:
            continue  # other splits (including held-out ones) are skipped without opening any picture
        group = g['stress']['name'] if g.get('stress') else split
        frames, prev_fen = [], None
        for f in g['frames']:
            st = (f.get('scene') or {}).get('stress') or {}
            frames.append({'root': root_name, 'split': split, 'game': g['id'], 'group': group,
                           'index': f['index'], 'kind': f['kind'], 'file': str(root / f['file']), 'fen': f['fen'],
                           'corners': f['corners'], 'transition': bool(f.get('transition')),
                           'transitionMove': f.get('transitionMove'), 'prevFen': prev_fen,
                           'highlight': st.get('highlight') or [],
                           'disturbance': [k for k, v in f['disturbance'].items() if v and k != 'sticky'] or ['none'],
                           'key': f"{root_name}/{g['id']}/{f['index']:03d}"})
            if not f.get('transition'):
                prev_fen = f['fen']
        games.append({'id': g['id'], 'split': split, 'group': group, 'frames': frames})
    return games


def panel_path(key, variant):
    name = f"{key.replace('/', '__')}.{variant}.png"
    cached = V3_CACHE / 'panels' / name
    return cached if cached.exists() else OUT / 'panels' / name


def load_meta():
    meta = json.loads((V3_CACHE / 'panel-meta.json').read_text())
    mine = OUT / 'panel-meta.json'
    if mine.exists():
        meta.update(json.loads(mine.read_text()))
    return meta


def prepare(splits):
    items = [f for s in splits for g in items_for(s) for f in g['frames']]
    meta_all = load_meta()
    detf = OUT / 'detections.json'
    dets = json.loads(detf.read_text()) if detf.exists() else {}
    todo = [it for it in items if it['key'] not in meta_all or not panel_path(it['key'], 'true').exists()]
    need_det = [it['file'] for it in todo if it['file'] not in dets]
    if need_det:
        print(f'detector on {len(need_det)} images', flush=True)
        dets.update(h3.run_detector(need_det))
        OUT.mkdir(parents=True, exist_ok=True)
        detf.write_text(json.dumps(dets))
    mine = OUT / 'panel-meta.json'
    meta = json.loads(mine.read_text()) if mine.exists() else {}
    (OUT / 'panels').mkdir(parents=True, exist_ok=True)
    for n, it in enumerate(todo, 1):
        screen_true = h3.order_like_detector(it['corners'])
        m = {'rTrue': h3.nearest_rotation(screen_true, it['corners'])[0]}
        det = dets.get(it['file'], {})
        if det.get('found'):
            r_det, shift = h3.nearest_rotation(det['corners'], it['corners'])
            m.update(rDet=r_det, cornerErrPx=round(shift, 2))
        meta[it['key']] = m
        img = np.asarray(Image.open(it['file']).convert('RGB'), np.float32)
        for v, c in [('true', screen_true)] + ([('det', det['corners'])] if det.get('found') else []):
            h3.rectify(img, c).save(OUT / 'panels' / f"{it['key'].replace('/', '__')}.{v}.png", compress_level=1)
        if n % 100 == 0:
            print(f'  rectified {n}/{len(todo)}', flush=True)
            mine.write_text(json.dumps(meta))
    mine.write_text(json.dumps(meta))
    print(f'prepared {len(todo)} new pictures of {len(items)}')


# ------------------------------------------------------------ scoring ----
def drawn_occupancy(it):
    """Transition picture: what is actually DRAWN per square (a8..h1 names). The generator draws the position
    before the move with the origin emptied and the moving piece at the halfway point of the two square centres.
    Squares the moving piece straddles map to None (no single right answer); a square it is drawn exactly
    centred on carries the mover's colour."""
    mv = it['transitionMove']
    before = dict(zip(SQ, h3.occ_a8h1(it['prevFen'])))
    mover = before[mv[:2]]
    before[mv[:2]] = 'empty'
    f0, r0, f1, r1 = 'abcdefgh'.index(mv[0]), int(mv[1]), 'abcdefgh'.index(mv[2]), int(mv[3])
    files = {(f0 + f1) // 2, (f0 + f1 + 1) // 2}
    ranks = {(r0 + r1) // 2, (r0 + r1 + 1) // 2}
    covered = ['abcdefgh'[f] + str(r) for f in files for r in ranks]
    for s in covered:
        before[s] = mover if len(covered) == 1 else None
    return before


def score(res, r, it):
    labels = h3.a8_from_screen([res[s]['label'] for s in SQ], r)
    cells = dict(zip(SQ, h3.a8_from_screen([res[s] for s in SQ], r)))
    truth = h3.occ_a8h1(it['fen'])
    wrong, reasons, hl = [], {}, {'squares': 0, 'correct': 0, 'unknown': 0, 'wrong': 0}
    drawn = drawn_occupancy(it) if it['transition'] else {}
    for s, got, want in zip(SQ, labels, truth):
        c = cells[s]
        for x in c['reasons']:
            reasons[x.split(':')[0]] = reasons.get(x.split(':')[0], 0) + 1
        if got not in (want, 'unknown'):
            wrong.append({'square': s, 'truth': want, 'got': got, 'fg': c.get('fgFrac'), 'edge': c.get('edgeFrac'),
                          'share': c.get('colourShare'), 'dist': c.get('colourDist'), 'local': c.get('local'),
                          'drawnHere': drawn.get(s) == got})
        if s in it['highlight']:
            hl['squares'] += 1
            hl['correct' if got == want else 'unknown' if got == 'unknown' else 'wrong'] += 1
    return {'key': it['key'], 'game': it['game'], 'group': it['group'], 'kind': it['kind'], 'transition': it['transition'],
            'correct': sum(a == b for a, b in zip(labels, truth)), 'wrong': len(wrong), 'unknown': labels.count('unknown'),
            'wrongSquares': wrong, 'reasons': reasons, 'highlight': hl,
            'labels': ''.join({'empty': 'e', 'white': 'w', 'black': 'b', 'unknown': '?'}[x] for x in labels)}


def eval_split(name, split, games_filter=None):
    mod = classifier(name)
    meta = load_meta()
    out = {'classifier': name, 'split': split, 'starts': [], 'frames': []}
    for g in items_for(split):
        if games_filter and g['id'] not in games_filter:
            continue
        f0 = g['frames'][0]
        for var in VARIANTS:
            rec = {'game': g['id'], 'group': g['group'], 'variant': var}
            p = panel_path(f0['key'], var)
            if not p.exists():
                rec.update(accepted=False, cause='detector'); out['starts'].append(rec); continue
            panel = Image.open(p).convert('RGB')
            r_ok = meta[f0['key']]['rTrue' if var == 'true' else 'rDet']
            r, cal, okl, errs = h3.try_start(mod, panel, f0['fen'])
            rec.update(accepted=r is not None, rotations=okl, correctRotation=r_ok, acceptedCorrect=r == r_ok,
                       errors={k: v[:300] for k, v in errs.items()})
            out['starts'].append(rec)
            if r is None:
                continue
            for it in g['frames'][1:]:
                p = panel_path(it['key'], var)
                if not p.exists() or it['key'] not in meta:
                    continue
                rr = meta[it['key']]['rTrue' if var == 'true' else 'rDet']
                res = mod.classify(Image.open(p).convert('RGB'), cal)
                out['frames'].append({'variant': var, **score(res, rr, it)})
    return out


def run_games(names, splits):
    RUNS.mkdir(parents=True, exist_ok=True)
    for split in splits:
        for name in names:
            t = time.time()
            rep = eval_split(name, split)
            (RUNS / f'{name}-{split}.json').write_text(json.dumps(rep))
            fr = rep['frames']
            print(f"{name} {split}: starts true {sum(s['accepted'] for s in rep['starts'] if s['variant'] == 'true')}"
                  f"/{sum(s['variant'] == 'true' for s in rep['starts'])} det "
                  f"{sum(s['accepted'] for s in rep['starts'] if s['variant'] == 'det')}; "
                  f"wrong {sum(f['wrong'] for f in fr)} unknown {sum(f['unknown'] for f in fr)} "
                  f"correct {sum(f['correct'] for f in fr)} ({time.time() - t:.0f} s)", flush=True)
            for f in fr:
                for w in f['wrongSquares']:
                    print(f"   WRONG {name} {f['variant']} {f['key']} {w['square']} {w['truth']}->{w['got']} "
                          f"fg {w['fg']} edge {w['edge']} share {w['share']} dist {w['dist']} drawnHere {w['drawnHere']}")


# ------------------------------------------------------------ summary ----
def _tot(frames):
    return tuple(sum(f[k] for f in frames) for k in ('wrong', 'unknown', 'correct'))


def summary(names, splits):
    lines = ['| split / group | corners | ' + ' | '.join(f'{n} starts | {n} wrong / unknown / correct' for n in names)
             + ' |', '|' + '---|' * (2 + 2 * len(names))]
    hl_lines = []
    for split in splits:
        reps = {}
        for n in names:
            p = RUNS / f'{n}-{split}.json'
            if p.exists():
                reps[n] = json.loads(p.read_text())
        if not reps:
            continue
        groups = [split] + (sorted({s['group'] for r in reps.values() for s in r['starts']}) if split == 'stressdev' else [])
        for grp in groups:
            for var in VARIANTS:
                cells = []
                for n in names:
                    r = reps.get(n)
                    if r is None:
                        cells += ['-', '-']; continue
                    st = [s for s in r['starts'] if s['variant'] == var and (grp == split or s['group'] == grp)]
                    fr = [f for f in r['frames'] if f['variant'] == var and (grp == split or f['group'] == grp)]
                    bad = sum(s['accepted'] and not s['acceptedCorrect'] for s in st)
                    cells += [f"{sum(s['accepted'] for s in st)}/{len(st)}" + (f' ({bad} WRONG ORIENT)' if bad else ''),
                              '{} / {} / {}'.format(*_tot(fr))]
                lines.append(f'| {grp if grp == split else "  " + grp} | {var} | ' + ' | '.join(cells) + ' |')
        if split == 'stressdev':
            for n, r in reps.items():
                for var in VARIANTS:
                    hs = [f['highlight'] for f in r['frames'] if f['variant'] == var and f['highlight']['squares']]
                    t = {k: sum(h[k] for h in hs) for k in ('squares', 'correct', 'unknown', 'wrong')}
                    hl_lines.append(f'highlighted squares {n} {var}: {t}')
                    tr = [f for f in r['frames'] if f['variant'] == var and f['transition']]
                    hl_lines.append(f'transition pictures {n} {var}: {len(tr)} pictures, wrong / unknown / correct '
                                    f'{_tot(tr)}; of the wrong, matching what is DRAWN (key shows the after-move position): '
                                    f"{sum(w['drawnHere'] for f in tr for w in f['wrongSquares'])}")
    print('\n'.join(lines))
    print('\n'.join(hl_lines))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('mode', choices=['prepare', 'games', 'summary'])
    ap.add_argument('--classifiers', default='v3,v4')
    ap.add_argument('--splits', default='smoke,dev,smoke2,dev2,stressdev')
    a = ap.parse_args()
    splits = [_allowed(s) for s in a.splits.split(',')]
    names = a.classifiers.split(',')
    if a.mode == 'prepare':
        prepare(splits)
    elif a.mode == 'games':
        run_games(names, splits)
    else:
        summary(names, splits)


if __name__ == '__main__':
    main()
