#!/usr/bin/env python3
"""Score the screen pipeline (scripts/recognition/screen_pipeline.py). Simulated images only.

Game mode:   --scenes ROOT --split NAME --out DIR [--classifier v2|v3] [--agree 1,2] [--start-fallback v4] [--start-self-check]
             [--corner-finder original|round2]
  Every game runs for each AGREE_FRAMES value (side by side) in two modes. "strict": never reset;
  once the tracker is behind we record what happens. "re-review": a simulated human resets the
  tracked FEN to the truth. One-picture-per-position roots (no `positionIndex`): reset after any
  withheld picture (round-1 rule, so AGREE_FRAMES=1 reproduces round 1 exactly). Multi-picture
  roots: reset at the end of any position whose correct move was not accepted by its last picture.
  Scored per picture AND per position. A position is "tracked" if its last picture leaves the
  tracker on the true FEN with no wrong accept inside it, else "missed".
Single mode: --single-scenes ROOT [--single-split dev] --out DIR
  Per-frame check on the existing single-position screen scenes (screen-board-truth-v1).

Truth is used only to score, to supply startFen, and to play the simulated human on re-review.
Never tune policy on any heldout split.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import occupancy_classifier as oc  # noqa: E402  (static helpers only: FEN occupancy, square names)
import screen_pipeline as sp  # noqa: E402

LABELS = ('empty', 'white', 'black', 'unknown')
WITHHELD_CAUSES = ('detector-not-found', 'detector-error', 'orientation', 'classifier-unknowns', 'ambiguous-promotion', 'ambiguous-other',
                   'no-legal-explanation', 'no-start')
DEBUG_WITHHELD_PER_CAUSE = 3
MODES = ('strict', 're-review', 'self-aware')
CONFIGS = {'1': {'AGREE_FRAMES': 1, 'AGREE_MODE': 'consecutive'},
           '2': {'AGREE_FRAMES': 2, 'AGREE_MODE': 'consecutive'},
           '2of3': {'AGREE_FRAMES': 2, 'AGREE_MODE': 'window', 'AGREE_WINDOW': 3}}


def position_of(frame):
    """Position number of a picture (scorer only): `positionIndex` in multi-picture roots, else the index."""
    return frame.get('positionIndex', frame['index'])


def start_pictures_of(game):
    """How many leading pictures show the reviewed start (the scorer plays the human who says so)."""
    return sum(1 for f in game['frames'] if position_of(f) == 0)


def fen4(fen):
    """Placement, side to move and castling rights. The en passant field is left out on purpose:
    chess.js writes it only when a capture is legal, other generators always write it after a
    double push; where it matters (a legal capture) both conventions agree."""
    return ' '.join(fen.split()[:3]) if fen else None


def truth_occ_a8h1(fen):
    o = oc.occupancy_from_fen(fen)
    return [o[s] for s in sp.SQUARES_A8H1]


def disturbance_keys(frame):
    d = frame.get('disturbance') or {}
    keys = [k for k in ('glare', 'hand', 'banding') if d.get(k)]
    return keys or ['none']


def disturbance_kind(frame):
    d = frame.get('disturbance') or {}
    if not any(d.get(k) for k in ('glare', 'hand', 'banding')):
        return 'none'
    return 'sticky' if d.get('sticky') else 'moving'


def flag_keys(frame):
    if frame['kind'] == 'repeat':
        return ['repeat']
    return list(frame.get('flags') or []) or ['quiet']


# ------------------------------------------------------------------ scoring ----
def score_frame(rec, frame, prev_frame):
    """Verdict for one non-start trace record. `prev_frame` is any picture of the PREVIOUS position.
    Pure function of trace + truth (unit tested)."""
    truth_move = frame.get('moveUci') if frame['kind'] == 'move' else None
    before = fen4(rec.get('trackedFenBefore'))
    in_sync = before in (fen4(prev_frame['fen']), fen4(frame['fen']))
    v = {'kind': frame['kind'], 'truthMove': truth_move, 'inSyncBefore': in_sync}
    if rec['status'] == 'accepted':
        status = rec['inference']['status']
        correct = fen4(rec['trackedFen']) == fen4(frame['fen'])
        v['verdict'] = 'correct-accepted' if correct else 'WRONG-ACCEPTED'
        if not correct:
            if status == 'move' and before == fen4(frame['fen']):
                v['wrongType'] = 'move-on-repeat-frame'  # board shows the tracked position, a move was accepted
            elif status == 'unchanged':
                v['wrongType'] = 'unchanged-but-move-happened'
            elif before == fen4(prev_frame['fen']):
                v['wrongType'] = 'wrong-move'
            else:
                v['wrongType'] = 'accepted-while-tracker-behind'
        v['acceptedMove'] = rec.get('acceptedMove')
        if status == 'unchanged' and not correct:  # "nothing moved" reported while truth had moved
            v['staleUnchanged'] = True
            v['staleConfirmed'] = bool(rec.get('currentConfirmed'))
    elif rec['status'] == 'pending':
        v['verdict'] = 'pending'
        v['pendingCorrect'] = fen4(rec.get('inferredFen')) == fen4(frame['fen'])
    else:
        v['verdict'] = 'withheld'
        v['cause'] = rec.get('cause')
        v['hidesRealMove'] = frame['kind'] == 'move'
    if 'labelsA8H1' in rec:
        truth = truth_occ_a8h1(frame['fen'])
        got = [{'.': 'empty', 'w': 'white', 'b': 'black', '?': 'unknown'}[c] for c in rec['labelsA8H1']]
        v['misread'] = [{'square': s, 'truth': t, 'got': g} for s, t, g in zip(sp.SQUARES_A8H1, truth, got)
                        if g != 'unknown' and g != t]
        v['unknownSquares'] = sum(g == 'unknown' for g in got)
        v['confusion'] = [(t, g) for t, g in zip(truth, got)]
    return v


def guard_blocked_wrong(rec, frame, prev_frame):
    """A single picture inferred a WRONG move from an in-sync tracker, and the guard never accepted it."""
    if (rec.get('inference') or {}).get('status') != 'move' or rec.get('guard') not in ('discarded', 'unresolved'):
        return False
    before = fen4(rec.get('trackedFenBefore'))
    in_sync = before in (fen4(prev_frame['fen']), fen4(frame['fen']))
    return in_sync and fen4(rec.get('inferredFen')) != fen4(frame['fen'])


def _empty_bucket():
    return {'frames': 0, 'correctAccepted': 0, 'wrongAccepted': 0, 'wrongMoveAccepted': 0, 'staleUnchanged': 0,
            'staleConfirmed': 0, 'pending': 0, 'withheld': 0,
            'withheldByCause': {c: 0 for c in WITHHELD_CAUSES}, 'reReviews': 0}


def _add(bucket, v, rereview):
    bucket['frames'] += 1
    if v['verdict'] == 'correct-accepted':
        bucket['correctAccepted'] += 1
    elif v['verdict'] == 'WRONG-ACCEPTED':
        bucket['wrongAccepted'] += 1
        bucket['staleUnchanged'] += bool(v.get('staleUnchanged'))
        bucket['staleConfirmed'] += bool(v.get('staleConfirmed'))
        bucket['wrongMoveAccepted'] += not v.get('staleUnchanged')
    elif v['verdict'] == 'pending':
        bucket['pending'] += 1
    else:
        bucket['withheld'] += 1
        bucket['withheldByCause'][v['cause']] = bucket['withheldByCause'].get(v['cause'], 0) + 1
    bucket['reReviews'] += rereview


def _empty_pos():
    return {'positions': 0, 'tracked': 0, 'missed': 0, 'wrongEvents': 0, 'reReviews': 0}


# ------------------------------------------------------------------ game modes ----
def _first_by_position(frames):
    first = {}
    for f in frames:
        first.setdefault(position_of(f), f)
    return first


def run_mode(mode, scenes, game, dets, bridge, cache, images, start_pictures=None):
    """Returns (trace records with verdicts, game summary, positions). Uses the current sp.POLICY.
    Modes: strict (never reset), re-review (oracle: truth says when the tracker is behind),
    self-aware (a human re-review happens ONLY when the pipeline itself sets reviewRequested)."""
    if start_pictures is None:
        start_pictures = start_pictures_of(game)
    tracker = sp.GameTracker(game['startFen'], bridge, cache)
    frames = game['frames']
    multi = any('positionIndex' in f for f in frames)
    first = _first_by_position(frames)
    out, rereviews, first_start_ok = [], 0, None
    for i, f in enumerate(frames):
        det = dets[str(scenes / f['file'])]
        loader = images(f)
        if i < start_pictures:
            rec = tracker.start(f['index'], loader, det)
            if first_start_ok is None:
                first_start_ok = rec['status'] == 'start-accepted'
            rec['verdict'] = {'kind': 'start', 'verdict': rec['status'], 'startCheck': rec.get('startCheck')}
            out.append(rec)
            continue
        if not tracker.started:
            break
        rec = tracker.step(f['index'], loader, det, cache_key=f['index'])
        v = score_frame(rec, f, first[position_of(f) - 1])
        last_of_position = i + 1 == len(frames) or position_of(frames[i + 1]) != position_of(f)
        rr = 0
        if mode.startswith('self-aware'):
            rr = int(bool(rec.get('reviewRequested')))
        elif mode == 're-review':
            if multi:
                rr = int(last_of_position and fen4(tracker.fen) != fen4(f['fen']))
            else:
                rr = int(v['verdict'] == 'withheld')
        if rr:
            r = rec.get('rotation')
            corners = None
            if det.get('found'):
                if r is None:  # the simulated human points out the orientation
                    r, _ = sp.choose_rotation(det['corners'], f['corners'])
                corners = sp.rotate(det['corners'], r) if r is not None else None
            tracker.human_rereview(f['fen'], corners)
            rereviews += 1
        v['reReview'] = rr
        v['lastOfPosition'] = last_of_position
        rec['verdict'] = v
        out.append(rec)
    tracker.finish()
    started = tracker.started
    # per position (pictures of one position are consecutive)
    positions, lost_at = [], None
    for rec in out:
        if rec['stage'] != 'frame':
            continue
        f = frames[[x['index'] for x in frames].index(rec['index'])]
        p = position_of(f)
        if not positions or positions[-1]['position'] != p:
            positions.append({'position': p, 'wrong': 0, 'reReview': 0, 'frame': f, 'pictures': [], 'recs': []})
        cur = positions[-1]
        cur['pictures'].append(f)
        cur['recs'].append(rec)
        cur['wrong'] += rec['verdict']['verdict'] == 'WRONG-ACCEPTED'
        cur['reReview'] += rec['verdict']['reReview']
        cur['finalFen'] = rec['trackedFen']
    for pos in positions:
        pos['tracked'] = pos['wrong'] == 0 and fen4(pos['finalFen']) == fen4(pos['frame']['fen'])
        if lost_at is None and fen4(pos['finalFen']) != fen4(pos['frame']['fen']):
            lost_at = pos['position']
    n_pos = len(first) - 1
    summary = {'game': game['id'], 'mode': mode, 'startAccepted': started,
               'startAcceptedFirstPictureOnly': bool(first_start_ok), 'frames': len(frames), 'positions': n_pos,
               'reReviews': rereviews,
               'wrongAccepted': sum(r['verdict'].get('verdict') == 'WRONG-ACCEPTED' for r in out),
               'firstLostPosition': lost_at if started else 0,
               'positionsTrackedBeforeLoss': (lost_at - 1 if lost_at else n_pos) if started else 0}
    summary['framesTrackedBeforeLoss'] = summary['positionsTrackedBeforeLoss']  # = pictures in one-picture roots
    summary['trackedEndToEndZeroReReviews'] = started and lost_at is None and rereviews == 0
    if tracker.start_fallback is not None:  # fallback on: which reader accepted the start (and read the game)
        summary['startReader'] = tracker.reader_name if started else None
    return out, summary, positions


def _panel_for(scenes, frame, rec):
    img = np.asarray(Image.open(scenes / frame['file']).convert('RGB'), np.float32)
    if rec['detector'].get('corners'):  # the screen-upright panel the classifier saw
        return sp.rectify(img, rec['detector']['corners'])
    return Image.fromarray(img.astype(np.uint8)).resize((640, 360))


def _apply(config, n_self=None):
    """Set sp.POLICY for one scoring config; returns the previous values to restore."""
    keys = dict(CONFIGS[config])
    if n_self is not None:
        keys['SELF_REVIEW_AFTER_WITHHELD'] = n_self
    old = {k: sp.POLICY[k] for k in keys}
    sp.POLICY.update(keys)
    return old


def mode_names(self_ns):
    """The three modes, plus extra self-aware variants (self-aware@N) used to choose N on dev splits."""
    return list(MODES) + [f'self-aware@{n}' for n in self_ns if n != sp.POLICY['SELF_REVIEW_AFTER_WITHHELD']]


def evaluate_games(scenes, split, out, binary, agrees=('1', '2'), self_ns=(), allow_detector_errors=False):
    scenes, out = Path(scenes), Path(out)
    if split in ('heldout', 'heldout2', 'stressheld') and not __import__('os').environ.get('ORCHESTRATOR_HELDOUT_RUN'):
        raise SystemExit(f'{split} is a held-out split: only the orchestrator runs it (set ORCHESTRATOR_HELDOUT_RUN=1)')
    doc = sp.load_games(scenes)
    games = [g for g in doc['games'] if g['split'] == split]
    if not games:
        raise SystemExit(f'no games with split {split!r} in {scenes}/truth/games.json')
    (out / 'debug').mkdir(parents=True, exist_ok=True)
    (out / 'traces').mkdir(parents=True, exist_ok=True)
    modes = mode_names(self_ns)
    report = {'schema': 'screen-pipeline-eval-v3', 'split': split, 'scenes': str(scenes),
              'classifier': sp._CLASSIFIER['name'], 'policy': sp.policy(),
              'note': ('simulated images only; start pictures = simulated review; re-review = simulated human '
                       '(oracle); self-aware = human only when the pipeline asks; headline = self-aware'),
              'truthUsedByScorer': ['startFen (pipeline input)', 'number of start pictures (positionIndex 0)',
                                    'true FEN for re-review/self-aware resets (the simulated human)',
                                    'true corners: orientation a human points out on re-review when the detector '
                                    'refused it', 'everything in scoring'],
              'configs': {}}
    if sp.START_FALLBACK_CLASSIFIER is not None:  # only when on, so reports with the fallback off are unchanged
        report['startFallback'] = sp.START_FALLBACK_CLASSIFIER
    if sp.START_SELF_CHECK:  # only when on, so reports with the option off are unchanged
        report['startSelfCheck'] = True
    timing = {k: [] for k in ('decode', 'detect', 'rectify', 'classify', 'infer', 'total')}
    events, blocked, debug_saved, detector_errors = [], [], {}, []
    store = {c: {m: {'records': [], 'summaries': [], 'positions': []} for m in modes} for c in agrees}
    with sp.InferBridge() as bridge:
        for g in games:
            paths = [scenes / f['file'] for f in g['frames']]
            dets = sp.run_detector(paths, binary)
            detector_errors += [{'game': g['id'], 'image': k, 'reason': d['reason']} for k, d in dets.items()
                                if d.get('error')]
            cache, decode_ms = {}, {}

            def images(frame):
                def load():
                    arr, ms = sp.load_image(scenes / frame['file'])
                    decode_ms[frame['index']] = ms
                    return arr
                return load
            line = []
            for c in agrees:
                for mode in modes:
                    n_self = int(mode.split('@')[1]) if '@' in mode else None
                    old = _apply(c, n_self)
                    try:
                        recs, summ, pos = run_mode(mode, scenes, g, dets, bridge, cache, images, start_pictures_of(g))
                    finally:
                        sp.POLICY.update(old)
                    st = store[c][mode]
                    st['records'].append((g, recs)); st['summaries'].append(summ); st['positions'].append((g, pos))
                    (out / 'traces' / f"{g['id']}.agree{c}.{mode}.json").write_text(json.dumps(recs, indent=1))
                    if '@' not in mode:
                        line.append(f"A{c} {mode} start={summ['startAccepted']} wrong={summ['wrongAccepted']} "
                                    f"rr={summ['reReviews']}")
            for r in store[agrees[0]]['strict']['records'][-1][1]:  # timings: first pass computes everything
                if r['stage'] == 'start':
                    continue
                t = r['timingsMs']
                row = {'decode': decode_ms.get(r['index'], 0.0), 'detect': t.get('detect', 0.0),
                       'rectify': t.get('rectify', 0.0), 'classify': t.get('classify', 0.0), 'infer': t.get('infer', 0.0)}
                row['total'] = sum(row.values())
                for k, val in row.items():
                    timing[k].append(val)
            print(f"{g['id']}: " + '; '.join(line), flush=True)
    for c in agrees:
        old = _apply(c)
        cfg = {'policy': sp.policy(), 'modes': {}}
        for mode in modes:
            st = store[c][mode]
            cfg['modes'][mode] = summarise(f'agree{c}/{mode}', st['records'], st['summaries'], st['positions'],
                                           scenes, out, events, blocked, debug_saved)
        sp.POLICY.update(old)
        report['configs'][f'agree{c}'] = cfg
    if '1' in agrees and '2' in agrees:
        report['agreeCostBreakdown'] = agree_cost_breakdown(store['1']['re-review']['positions'],
                                                            store['2']['re-review']['positions'])
    report['detectorErrors'] = detector_errors
    report['msPerPicture'] = {k: {'mean': round(float(np.mean(v)), 1), 'p95': round(float(np.percentile(v, 95)), 1)}
                              for k, v in timing.items() if v}
    report['timingNote'] = ('detect = binary decode+detect per image (batched per game); decode = python PNG decode; '
                            'rectify/classify python numpy; infer = node round trip')
    report['wrongAcceptedEvents'] = events
    report['guardBlockedWrongInferences'] = blocked
    report['uptime'] = subprocess.run(['uptime'], capture_output=True, text=True).stdout.strip()
    (out / f'report-{split}.json').write_text(json.dumps(report, indent=1))
    print_headline(report)
    if detector_errors:
        print(f'WARNING: {len(detector_errors)} detector error(s); first: {detector_errors[0]}', file=sys.stderr)
        if not allow_detector_errors:
            raise SystemExit(2)
    return report


def _reading(rec, frame):
    """One letter per picture of a position, read against the tracker FEN at that picture:
    M correct move, W wrong move, U unchanged, N no-legal/ambiguous, ? unusable (detector/orientation/unknowns)."""
    inf = (rec.get('inference') or {}).get('status')
    if inf == 'move':
        return 'M' if fen4(rec.get('inferredFen')) == fen4(frame['fen']) else 'W'
    if inf == 'unchanged':
        return 'U'
    if inf in ('no-legal-explanation', 'ambiguous'):
        return 'N'
    return '?'


def agree_cost_breakdown(pos1, pos2):
    """Positions tracked at agree 1 but missed at agree 2 (re-review mode: both start each position in sync)."""
    a1 = {(g['id'], p['position']): p for g, ps in pos1 for p in ps}
    out = {'positions': 0, 'byCategory': {}, 'byPattern': {}}
    for g, ps in pos2:
        for p in ps:
            q = a1.get((g['id'], p['position']))
            if q is None or not q['tracked'] or p['tracked']:
                continue
            pattern = ''.join(_reading(r, f) for r, f in zip(p['recs'], p['pictures']))
            m = pattern.count('M')
            if m <= 1:
                cat = f'only {m} picture read the move'
            else:
                first, second = pattern.index('M'), pattern.index('M', pattern.index('M') + 1)
                between = pattern[first + 1:second]
                cat = ('2+ read the move, a conflicting reading in between' if any(x in 'UNW' for x in between)
                       else '2+ read the move, more unusable pictures in between than the skip cap')
            out['positions'] += 1
            out['byCategory'][cat] = out['byCategory'].get(cat, 0) + 1
            out['byPattern'][pattern] = out['byPattern'].get(pattern, 0) + 1
    return out


def summarise(tag, game_records, summaries, game_positions, scenes, out, events, blocked, debug_saved):
    overall = _empty_bucket()
    dims = ('difficulty', 'cameraMode', 'disturbance', 'disturbanceKind', 'moveFlag')
    by = {d: {} for d in dims}
    pos_overall, pos_by = _empty_pos(), {d: {} for d in dims if d != 'disturbance'}
    confusion = {t: {g: 0 for g in LABELS} for t in LABELS[:3]}
    sq = {'squares': 0, 'correct': 0, 'wrongConfident': 0, 'unknown': 0}
    for g, recs in game_records:
        frames = {f['index']: f for f in g['frames']}
        first = _first_by_position(g['frames'])
        for r in recs:
            if r['stage'] != 'frame':
                continue
            v, f = r['verdict'], frames[r['index']]
            _add(overall, v, v.get('reReview', 0))
            keys = {'difficulty': [g['difficulty']], 'cameraMode': [g['cameraMode']],
                    'disturbance': disturbance_keys(f), 'disturbanceKind': [disturbance_kind(f)],
                    'moveFlag': flag_keys(f)}
            for dim, ks in keys.items():
                for k in ks:
                    _add(by[dim].setdefault(k, _empty_bucket()), v, v.get('reReview', 0))
            for t, got in v.get('confusion', []):
                confusion[t][got] += 1
                sq['squares'] += 1
                sq['correct'] += got == t
                sq['unknown'] += got == 'unknown'
                sq['wrongConfident'] += got not in (t, 'unknown')
            prev = first[position_of(f) - 1]
            if v['verdict'] == 'WRONG-ACCEPTED':
                ev = {'config': tag, 'game': g['id'], 'frame': r['index'], 'position': position_of(f),
                      'kind': f['kind'], 'truthMove': v['truthMove'], 'acceptedStatus': r['inference']['status'],
                      'acceptedMove': r.get('acceptedMove'), 'wrongType': v.get('wrongType'),
                      'misreadSquares': v.get('misread'), 'disturbance': f.get('disturbance')}
                ev['staleUnchanged'] = bool(v.get('staleUnchanged'))
                ev['currentConfirmed'] = bool(r.get('currentConfirmed'))
                key = 'stale' if ev['staleUnchanged'] else 'wrong'
                if key == 'wrong' or debug_saved.get(('stale', tag), 0) < 3:  # every wrong move; a few stale samples
                    debug_saved[('stale', tag)] = debug_saved.get(('stale', tag), 0) + (key == 'stale')
                    path = out / 'debug' / f"{key}-{tag.replace('/', '-').replace('@', 'N')}-{g['id']}-{r['index']:03d}.png"
                    _panel_for(scenes, f, r).save(path)
                    ev['debugImage'] = str(path)
                events.append(ev)
            elif guard_blocked_wrong(r, f, prev):
                ev = {'config': tag, 'game': g['id'], 'frame': r['index'], 'position': position_of(f),
                      'kind': f['kind'], 'truthMove': v['truthMove'], 'inferredMove': r.get('inferredMove'),
                      'guard': r.get('guard'), 'misreadSquares': v.get('misread'), 'disturbance': f.get('disturbance')}
                path = out / 'debug' / f"blocked-{tag.replace('/', '-').replace('@', 'N')}-{g['id']}-{r['index']:03d}.png"
                _panel_for(scenes, f, r).save(path)
                ev['debugImage'] = str(path)
                blocked.append(ev)
            elif v['verdict'] == 'withheld' and tag.endswith('re-review'):
                key = v['cause']
                if debug_saved.get(key, 0) < DEBUG_WITHHELD_PER_CAUSE:
                    debug_saved[key] = debug_saved.get(key, 0) + 1
                    _panel_for(scenes, f, r).save(out / 'debug' / f"withheld-{key}-{g['id']}-{r['index']:03d}.png")
    for g, positions in game_positions:
        for pos in positions:
            kinds = {disturbance_kind(f) for f in pos['pictures']}
            dk = 'sticky' if 'sticky' in kinds else ('moving' if 'moving' in kinds else 'none')
            keys = {'difficulty': [g['difficulty']], 'cameraMode': [g['cameraMode']], 'disturbanceKind': [dk],
                    'moveFlag': flag_keys(pos['frame'])}
            for b in [pos_overall] + [pos_by[d].setdefault(k, _empty_pos()) for d, ks in keys.items() for k in ks]:
                b['positions'] += 1
                b['tracked'] += pos['tracked']
                b['missed'] += not pos['tracked']
                b['wrongEvents'] += pos['wrong']
                b['reReviews'] += pos['reReview']
    started = [s for s in summaries if s['startAccepted']]
    head = {'games': len(summaries), 'startRejected': len(summaries) - len(started),
            'startAcceptedFirstPictureOnly': sum(s['startAcceptedFirstPictureOnly'] for s in summaries),
            'startAccepted': len(started),
            'gamesTrackedEndToEndZeroReReviews': sum(s['trackedEndToEndZeroReReviews'] for s in summaries),
            'reReviewsPer100Frames': round(100 * overall['reReviews'] / max(1, overall['frames']), 2),
            'reReviewsPer100Positions': round(100 * pos_overall['reReviews'] / max(1, pos_overall['positions']), 2),
            'overall': overall, 'by': by, 'positions': pos_overall, 'positionsBy': pos_by, 'squares': sq,
            'confusionTruthByLabel': confusion, 'games_': summaries}
    if any('startReader' in s for s in summaries):  # fallback on
        readers = [s['startReader'] for s in started]
        head['startsByReader'] = {r: readers.count(r) for r in sorted(set(readers))}
        head['startsViaFallback'] = sum(r != sp._CLASSIFIER['name'] for r in readers)
    if tag.endswith('strict'):
        head['meanPositionsTrackedBeforeLoss'] = round(float(np.mean(
            [s['positionsTrackedBeforeLoss'] for s in started])), 1) if started else 0
        head['meanFramesTrackedBeforeLoss'] = head['meanPositionsTrackedBeforeLoss']
    return head


def print_headline(report):
    cfgs = list(report['configs'])
    print(f"\npolicy sha256 (default config) {report['policy']['sha256']}; classifier {report['classifier']}; "
          + ', '.join(f"{c} sha256 {report['configs'][c]['policy']['sha256'][:12]}" for c in cfgs))
    for mode in ('self-aware', 're-review', 'strict'):  # headline first: the only mode a real app can achieve
        hs = {c: report['configs'][c]['modes'][mode] for c in cfgs}
        print(f"\n### {report['split']} / {mode} (simulated images only), side by side " + ' | '.join(cfgs))
        for c, h in hs.items():
            print(f"{c}: games {h['games']}, starts accepted {h['startAccepted']} (first picture only "
                  f"{h['startAcceptedFirstPictureOnly']}), end-to-end 0 re-reviews {h['gamesTrackedEndToEndZeroReReviews']}, "
                  f"re-reviews/100 positions {h['reReviewsPer100Positions']}"
                  + (f", starts via fallback {h['startsViaFallback']} {h['startsByReader']}"
                     if 'startsViaFallback' in h else '')
                  + (f", mean positions tracked before loss {h.get('meanPositionsTrackedBeforeLoss')}"
                     if mode == 'strict' else ''))
        cols = ['bucket', 'pics'] + [f'{c} {k}' for k in ('WRONG', 'correct', 'pending', 'withheld') for c in cfgs] \
            + ['positions'] + [f'{c} {k}' for k in ('tracked', 'missed', 'rr/100pos') for c in cfgs]
        print('| ' + ' | '.join(cols) + ' |')
        print('|---' * len(cols) + '|')
        rows = [('ALL', {c: hs[c]['overall'] for c in cfgs}, {c: hs[c]['positions'] for c in cfgs})]
        base = hs[cfgs[0]]
        for dim in ('difficulty', 'cameraMode', 'disturbanceKind', 'disturbance', 'moveFlag'):
            for k in sorted(base['by'][dim]):
                rows.append((f'{dim}={k}', {c: hs[c]['by'][dim].get(k) for c in cfgs},
                             {c: hs[c]['positionsBy'].get(dim, {}).get(k) for c in cfgs}))
        for name, pb, qb in rows:
            first_p = next(iter(pb.values()))
            first_q = next(iter(qb.values()))
            cells = [name, first_p['frames']]
            for k in ('wrongAccepted', 'correctAccepted', 'pending', 'withheld'):
                cells += [pb[c][k] for c in cfgs]
            cells.append(first_q['positions'] if first_q else '-')
            for k in ('tracked', 'missed'):
                cells += [qb[c][k] if qb[c] else '-' for c in cfgs]
            cells += [round(100 * qb[c]['reReviews'] / max(1, qb[c]['positions']), 1) if qb[c] else '-' for c in cfgs]
            print('| ' + ' | '.join(str(x) for x in cells) + ' |')
        for c, h in hs.items():
            s = h['squares']
            o = h['overall']
            print(f"{c}: WRONG {o['wrongAccepted']} = wrong move {o['wrongMoveAccepted']} + stale-unchanged "
                  f"{o['staleUnchanged']} (of which currentConfirmed {o['staleConfirmed']}); squares {s['squares']}: "
                  f"correct {s['correct']}, wrong-confident {s['wrongConfident']}, unknown {s['unknown']}")
    extra = sorted({m for c in cfgs for m in report['configs'][c]['modes'] if '@' in m})
    if extra:
        print(f"\n### self-aware variants (choose N on dev only; policy N = {report['policy']['pipeline']['SELF_REVIEW_AFTER_WITHHELD']})")
        print('| config | mode | WRONG | wrong move | stale | stale confirmed | positions tracked | missed | re-rev/100pos |')
        print('|---' * 9 + '|')
        for c in cfgs:
            for m in ['self-aware'] + extra:
                h = report['configs'][c]['modes'][m]; o, q = h['overall'], h['positions']
                print(f"| {c} | {m} | {o['wrongAccepted']} | {o['wrongMoveAccepted']} | {o['staleUnchanged']} | "
                      f"{o['staleConfirmed']} | {q['tracked']} | {q['missed']} | {h['reReviewsPer100Positions']} |")
    if report.get('agreeCostBreakdown'):
        print('\nagree-2 cost (re-review mode, tracked at agree1, missed at agree2):',
              json.dumps(report['agreeCostBreakdown']))
    print(f"detector errors: {len(report.get('detectorErrors', []))}")
    print(f"\nuptime at end: {report.get('uptime')}")
    print('ms/picture by stage:', json.dumps(report['msPerPicture']))
    moves = [e for e in report['wrongAcceptedEvents'] if not e.get('staleUnchanged')]
    print(f"WRONG ACCEPTED events: {len(report['wrongAcceptedEvents'])} (wrong moves {len(moves)}, rest stale-unchanged; "
          "wrong moves listed)")
    for e in moves:
        print('  ', json.dumps({k: e[k] for k in ('config', 'game', 'frame', 'truthMove', 'acceptedStatus',
                                                  'acceptedMove', 'wrongType', 'misreadSquares')}))
    print(f"guard-blocked WRONG single-picture inferences: {len(report['guardBlockedWrongInferences'])}")
    for e in report['guardBlockedWrongInferences']:
        print('  ', json.dumps({k: e[k] for k in ('config', 'game', 'frame', 'truthMove', 'inferredMove', 'guard',
                                                  'misreadSquares')}))


# ------------------------------------------------------------------ single-position scenes ----
def evaluate_single(root, split, out, binary):
    root, out = Path(root), Path(out)
    truth = json.loads((root / 'truth/truth.json').read_text())
    boards = {b['file']: b['placement'] for b in truth['boards']}
    scenes = [s for s in truth['scenes'] if s['split'] == split]
    positives = [s for s in scenes if s.get('corners')]
    negatives = [s for s in scenes if not s.get('corners')]
    dets = sp.run_detector([root / s['file'] for s in scenes], binary)
    start_place = oc.START_FEN
    starts = [s for s in positives if boards[s['board']] == start_place]
    rows, start_rows = [], []
    # 1. start orientation on every start-position scene (detected corners, 4 rotations)
    cal, cal_scene = None, None
    for s in starts:
        det = dets[str(root / s['file'])]
        row = {'id': s['id'], 'difficulty': s['difficulty'], 'found': bool(det.get('found'))}
        if det.get('found'):
            img, _ = sp.load_image(root / s['file'])
            ok = []
            panel = sp.rectify(img, det['corners'])
            a8 = truth_occ_a8h1(start_place)
            for r in range(4):
                try:
                    c = sp.clf().calibrate(panel, dict(zip(sp.SQUARES_A8H1, sp.screen_from_a8(a8, r))))
                    ok.append((r, c))
                except sp.clf().CalibrationError:
                    pass
            true_r, _ = sp.choose_rotation(det['corners'], s['corners'])
            row.update(rotationsCalibrated=[r for r, _ in ok], trueRotation=true_r,
                       accepted=len(ok) == 1, acceptedCorrect=len(ok) == 1 and ok[0][0] == true_r)
            if cal is None and len(ok) == 1 and ok[0][0] == true_r:
                cal, cal_scene = ok[0][1], s['id']
        start_rows.append(row)
    if cal is None:
        raise SystemExit('no start-position scene calibrated; cannot score the classifier')
    # 2. classifier per scene, detected corners (rotation chosen nearest truth: evaluation aid) and true corners
    for s in positives:
        if s['id'] == cal_scene:
            continue
        det = dets[str(root / s['file'])]
        truth_occ = truth_occ_a8h1(boards[s['board']] + ' w - - 0 1')
        img, _ = sp.load_image(root / s['file'])
        row = {'id': s['id'], 'difficulty': s['difficulty'], 'found': bool(det.get('found')),
               'disturbance': [k for k in ('glare', 'hand', 'banding') if s.get(k)] or ['none']}
        screen_true = sp.order_like_detector(s['corners'])
        variants = [('true', screen_true, sp.choose_rotation(screen_true, s['corners'])[0])]
        if det.get('found'):
            r, _ = sp.choose_rotation(det['corners'], s['corners'])
            if r is not None:
                dc = np.asarray(sp.rotate(det['corners'], r))
                row['cornerErrPx'] = round(float(np.max(np.linalg.norm(dc - np.asarray(s['corners']), axis=1))), 2)
                variants.append(('detected', det['corners'], r))
        for name, corners, r in variants:
            t = time.perf_counter()
            res = sp.clf().classify(sp.rectify(img, corners), cal)
            labels = sp.a8_from_screen(sp.labels_a8h1(res), r)
            row[name] = {'correct': sum(a == b for a, b in zip(labels, truth_occ)),
                         'wrong': sum(a not in (b, 'unknown') for a, b in zip(labels, truth_occ)),
                         'unknown': labels.count('unknown'), 'ms': round((time.perf_counter() - t) * 1000)}
            row[name]['wrongSquares'] = [f'{sq}:{b}->{a}' for sq, a, b in zip(sp.SQUARES_A8H1, labels, truth_occ)
                                         if a not in (b, 'unknown')]
        rows.append(row)
    neg = sum(bool(dets[str(root / s['file'])].get('found')) for s in negatives)
    agg = {}
    for r in rows:
        for key in ('all', r['difficulty'], *('dist=' + d for d in r['disturbance'])):
            a = agg.setdefault(key, {'scenes': 0, 'found': 0})
            a['scenes'] += 1
            a['found'] += r['found']
            for name in ('true', 'detected'):
                if name in r:
                    b = a.setdefault(name, {'frames': 0, 'squares': 0, 'correct': 0, 'wrong': 0, 'unknown': 0,
                                            'all64': 0, 'zeroWrong': 0})
                    b['frames'] += 1; b['squares'] += 64
                    for k in ('correct', 'wrong', 'unknown'):
                        b[k] += r[name][k]
                    b['all64'] += r[name]['correct'] == 64
                    b['zeroWrong'] += r[name]['wrong'] == 0
    report = {'schema': 'screen-pipeline-single-v1', 'split': split, 'root': str(root), 'policy': sp.policy(),
              'note': 'simulated images only; rotation for non-start scenes chosen nearest TRUE corners '
                      '(evaluation aid; tests detector+rectify+classifier, not orientation)',
              'calibrationScene': cal_scene, 'negatives': {'n': len(negatives), 'found': neg},
              'startScenes': start_rows, 'aggregate': agg, 'scenes': rows}
    out.mkdir(parents=True, exist_ok=True)
    (out / f'report-single-{split}.json').write_text(json.dumps(report, indent=1))
    acc = sum(r.get('accepted', False) for r in start_rows)
    accc = sum(r.get('acceptedCorrect', False) for r in start_rows)
    print(f'single-position {split} scenes (simulated images only); calibration from {cal_scene}')
    print(f'start-position scenes: {len(start_rows)}; exactly-one-rotation accepted {acc}, correct orientation {accc}')
    for r in start_rows:
        print('  ', r['id'], r['difficulty'], r.get('rotationsCalibrated'), 'true', r.get('trueRotation'))
    print(f"negatives found: {neg}/{len(negatives)}")
    print('| bucket | scenes | found | corners | frames | squares | correct | WRONG | unknown | all64 | 0 wrong |')
    print('|---' * 11 + '|')
    for key in sorted(agg, key=lambda k: (k != 'all', k)):
        a = agg[key]
        for name in ('true', 'detected'):
            if name in a:
                b = a[name]
                print(f"| {key} | {a['scenes']} | {a['found']} | {name} | {b['frames']} | {b['squares']} | {b['correct']} "
                      f"| {b['wrong']} | {b['unknown']} | {b['all64']} | {b['zeroWrong']} |")
    wrong = [(r['id'], n, r[n]['wrongSquares']) for r in rows for n in ('true', 'detected') if n in r and r[n]['wrong']]
    print('scenes with wrong-confident squares:', json.dumps(wrong))
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--scenes', type=Path)
    ap.add_argument('--split', help='smoke, dev, heldout, smoke2, dev2, heldout2, ...')
    ap.add_argument('--single-scenes', type=Path)
    ap.add_argument('--single-split', default='dev', choices=['dev', 'heldout'])
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--detector', type=Path, default=None, help='corner binary by path (overrides --corner-finder)')
    ap.add_argument('--corner-finder', default=sp.DEFAULT_FINDER, choices=sorted(sp.FINDERS),
                    help=f'corner finder by name (default {sp.DEFAULT_FINDER})')
    ap.add_argument('--classifier', default=sp.DEFAULT_CLASSIFIER, choices=sorted(sp.CLASSIFIERS))
    ap.add_argument('--agree', default='1,2', help='configs side by side: 1, 2, 2of3 (window alternative)')
    ap.add_argument('--self-aware-n', default='', help='extra SELF_REVIEW_AFTER_WITHHELD values to score (dev only)')
    ap.add_argument('--allow-detector-errors', action='store_true')
    ap.add_argument('--agree-interruption', choices=['reset', 'skip-unusable'], default=sp.POLICY['AGREE_INTERRUPTION'])
    ap.add_argument('--start-fallback', choices=sorted(sp.CLASSIFIERS), default=None,
                    help='backup reader tried only when --classifier refuses a start picture (off by default)')
    ap.add_argument('--start-self-check', action='store_true',
                    help='the default reader must read its start picture back as the stated start (off by default)')
    a = ap.parse_args()
    if a.detector is not None and a.corner_finder != sp.DEFAULT_FINDER:
        ap.error('give --detector or --corner-finder, not both')
    sp.set_finder(a.corner_finder)
    detector = a.detector if a.detector is not None else sp.finder_path()
    sp.POLICY['AGREE_INTERRUPTION'] = a.agree_interruption
    sp.set_classifier(a.classifier)
    sp.set_start_fallback(a.start_fallback)
    sp.set_start_self_check(a.start_self_check)
    if a.single_scenes:
        evaluate_single(a.single_scenes, a.single_split, a.out, detector)
    elif a.scenes and a.split:
        evaluate_games(a.scenes, a.split, a.out, detector, tuple(a.agree.split(',')),
                       tuple(int(x) for x in a.self_aware_n.split(',') if x), a.allow_detector_errors)
    else:
        ap.error('give --scenes and --split, or --single-scenes')


if __name__ == '__main__':
    main()
