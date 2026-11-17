#!/usr/bin/env python3
"""Screen pipeline (corners -> rectify -> occupancy -> move): synthetic rendered boards only, not camera evidence.

Run: python3 -B tests/screen_pipeline.py
"""
from pathlib import Path
import sys
import contextlib
import importlib.util
import tempfile
import unittest

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/recognition'))
sys.path.insert(0, str(ROOT / 'scripts/simulation'))
import occupancy_classifier as oc  # noqa: E402
import screen_pipeline as sp  # noqa: E402
import evaluate_screen_pipeline as ev  # noqa: E402
from render import render  # noqa: E402

SP_PATH = ROOT / 'scripts/recognition/screen_pipeline.py'

START = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
AFTER_E4 = 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1'
AFTER_E5 = 'rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2'
SCENE = {'quad': [[0, 0], [640, 0], [640, 640], [0, 640]], 'brightness': 1.0, 'blur': 0.0}  # identity: image = panel
W, H = 1280, 800
QUAD = np.array([[402.3, 151.6], [905.8, 170.2], [948.1, 690.4], [361.7, 672.9]])  # a8, h8, h1, a1 (keystone)


def flipped_placement(fen):
    """Placement as a site shows it with Black at the bottom: board turned 180 degrees, pieces upright."""
    ranks = fen.split()[0].split('/')
    return '/'.join(r[::-1] for r in reversed(ranks)) + ' w - - 0 1'


def screen_frame(fen, quad=QUAD, black_at_bottom=False):
    """Board of `fen` warped into a dark 1280x800 frame at `quad` (screen TL,TR,BR,BL; pixel centres at
    integers). With black_at_bottom the screen shows h1 at its top-left, pieces upright."""
    board = np.asarray(render(flipped_placement(fen) if black_at_bottom else fen, SCENE), np.float32)[64:576, 64:576]
    h = sp.homography(quad, [(0, 0), (512, 0), (512, 512), (0, 512)])  # image -> board edge coords
    xs, ys = np.meshgrid(np.arange(W, dtype=float), np.arange(H, dtype=float))
    den = h[2, 0] * xs + h[2, 1] * ys + h[2, 2]
    u = (h[0, 0] * xs + h[0, 1] * ys + h[0, 2]) / den - 0.5
    v = (h[1, 0] * xs + h[1, 1] * ys + h[1, 2]) / den - 0.5
    inside = ((u >= -0.5) & (u <= 511.5) & (v >= -0.5) & (v <= 511.5))[..., None]
    vals = sp._bilinear(board, u, v)
    return np.where(inside, vals, 30.0).astype(np.float32)


def flip180(img, quad):
    return img[::-1, ::-1].copy(), np.array([[W - 1 - x, H - 1 - y] for x, y in quad])


def det_for(quad):
    return {'found': True, 'confidence': 0.99, 'corners': sp.order_like_detector(quad)}


AFTER_E3 = 'rnbqkbnr/pppppppp/8/8/8/4P3/PPPP1PPP/RNBQKBNR b KQkq - 0 1'


@contextlib.contextmanager
def agree(n):
    old = sp.POLICY['AGREE_FRAMES']
    sp.POLICY['AGREE_FRAMES'] = n
    try:
        yield
    finally:
        sp.POLICY['AGREE_FRAMES'] = old


def reading(fen):
    """A hand-made classifier reading (White at bottom, so screen order = a8..h1) for the cache."""
    return {'screenLabels': ev.truth_occ_a8h1(fen), 'reasons': {}, 'rectifyMs': 0.0, 'classifyMs': 0.0}


def multi_game(positions):
    """positions: list of (fen, moveUci, n_pictures); position 0 is the start. Returns a multi-picture game."""
    frames, idx = [], 0
    for p, (fen, move, n) in enumerate(positions):
        for k in range(n):
            frames.append({'index': idx, 'positionIndex': p, 'file': f'{idx}.png', 'fen': fen,
                           'kind': ('start' if p == 0 else 'move') if k == 0 else 'repeat',
                           'moveUci': move if k == 0 else None, 'flags': [], 'corners': QUAD.tolist(),
                           'disturbance': {}})
            idx += 1
    return {'id': 'hand', 'startFen': positions[0][0], 'difficulty': 'easy', 'cameraMode': 'fixed', 'frames': frames}


class ScreenPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = sp.InferBridge()
        cls.start_img = screen_frame(START)
        cls.e4_img = screen_frame(AFTER_E4)

    @classmethod
    def tearDownClass(cls):
        cls.bridge.close()

    def setUp(self):
        # some tests switch the reader or the corner finder; put the globals back to their defaults so later tests do
        # not depend on order
        finders = dict(sp.FINDERS)

        def restore():
            sp.set_classifier(sp.DEFAULT_CLASSIFIER)
            sp.START_FALLBACK_CLASSIFIER = None
            sp.START_SELF_CHECK = False
            sp.FINDERS.clear(); sp.FINDERS.update(finders)
            sp._FINDER['name'] = sp.DEFAULT_FINDER
        self.addCleanup(restore)

    def test_square_order_conversion(self):
        a8h1 = ev.truth_occ_a8h1(AFTER_E4)
        a1h8 = sp.a8h1_to_a1h8(a8h1)
        self.assertEqual(sp.SQUARES_A1H8[:3], ['a1', 'b1', 'c1'])
        self.assertEqual(sp.SQUARES_A1H8[-1], 'h8')
        by_square = oc.occupancy_from_fen(AFTER_E4)
        self.assertEqual(a1h8, [by_square[s] for s in sp.SQUARES_A1H8])
        self.assertEqual(a1h8[sp.SQUARES_A1H8.index('e4')], 'white')
        self.assertEqual(a1h8[sp.SQUARES_A1H8.index('e2')], 'empty')
        self.assertEqual(a1h8[sp.SQUARES_A1H8.index('a8')], 'black')
        self.assertEqual(sp.a8h1_to_a1h8(list(range(64)))[:9], [56, 57, 58, 59, 60, 61, 62, 63, 48])

    def test_rectify_true_corners_classifies_exactly(self):
        cal = oc.calibrate(sp.rectify(self.start_img, QUAD), oc.occupancy_from_fen(START))
        labels = sp.labels_a8h1(oc.classify(sp.rectify(self.e4_img, QUAD), cal))
        self.assertEqual(labels, ev.truth_occ_a8h1(AFTER_E4))

    def test_four_rotations_resolve_to_one_and_follow_a_180_flip(self):
        """Same screen position, board shown White-at-bottom and then turned 180 degrees (Black at bottom)."""
        results = []
        for flipped in (False, True):
            img = screen_frame(START, black_at_bottom=flipped)
            tracker = sp.GameTracker(START, self.bridge)
            rec = tracker.start(0, img, det_for(QUAD))
            self.assertEqual(rec['status'], 'start-accepted', rec.get('rotationsTried'))
            self.assertEqual(sum(t['calibrated'] for t in rec['rotationsTried']), 1)
            a8_where = QUAD[2] if flipped else QUAD[0]  # turned board: a8 sits at the screen's bottom-right
            np.testing.assert_allclose(tracker.reference[0], a8_where, atol=1e-6)
            results.append((rec['rotation'], tracker))
        (r0, t0), (r1, t1) = results
        self.assertEqual((r0, r1), (0, 2))
        e4_up, e4_down = self.e4_img, screen_frame(AFTER_E4, black_at_bottom=True)
        with agree(1):
            rec0 = t0.step(1, e4_up, det_for(QUAD))
            rec1 = t1.step(1, e4_down, det_for(QUAD))
        self.assertEqual(rec0['labelsA8H1'], rec1['labelsA8H1'])
        self.assertEqual(sp.a8_from_screen(list(rec0['labelsA8H1']), 0),
                         ['.wb?'['empty white black unknown'.split().index(x)] for x in ev.truth_occ_a8h1(AFTER_E4)])
        self.assertEqual((rec0.get('acceptedMove'), rec1.get('acceptedMove')), ('e2e4', 'e2e4'))
        self.assertEqual(rec0['inference']['status'], 'move')
        # A pure 180-degree IMAGE flip is not what a site shows: it also turns the pieces upside down. The
        # calibration must refuse it in all four rotations (measured for v2 and v3), never pick one.
        img, quad = flip180(self.start_img, QUAD)
        rec = sp.GameTracker(START, self.bridge).start(0, img, det_for(quad))
        self.assertEqual(rec['status'], 'start-rejected')
        self.assertEqual([t['calibrated'] for t in rec['rotationsTried']], [False] * 4)

    def test_square_grid_rotation_round_trip(self):
        vals = list(range(64))
        for r in range(4):
            self.assertEqual(sp.a8_from_screen(sp.screen_from_a8(vals, r), r), vals)
        self.assertEqual(sp.screen_from_a8(vals, 2), vals[::-1])  # Black at bottom: screen TL is h1

    def test_wrong_stated_start_is_rejected(self):
        tracker = sp.GameTracker(AFTER_E4, self.bridge)  # claims e4 was played; screen shows the start
        rec = tracker.start(0, self.start_img, det_for(QUAD))
        self.assertEqual(rec['status'], 'start-rejected')
        self.assertFalse(tracker.started)
        self.assertEqual(sum(t['calibrated'] for t in rec['rotationsTried']), 0)

    def test_node_bridge_round_trip(self):
        res = self.bridge.infer(START, sp.a8h1_to_a1h8(ev.truth_occ_a8h1(AFTER_E4)))
        self.assertEqual(res['status'], 'move')
        self.assertEqual(res['move']['uci'], 'e2e4')
        self.assertEqual(self.bridge.infer(START, sp.a8h1_to_a1h8(ev.truth_occ_a8h1(START)))['status'], 'unchanged')
        with self.assertRaises(RuntimeError):
            self.bridge.infer(START, ['empty'] * 3)
        self.assertEqual(self.bridge.infer(START, sp.a8h1_to_a1h8(ev.truth_occ_a8h1(AFTER_E4)))['status'], 'move')

    def test_detector_failure_is_withheld(self):
        tracker = sp.GameTracker(START, self.bridge)
        tracker.start(0, self.start_img, det_for(QUAD))
        rec = tracker.step(1, self.e4_img, {'found': False, 'reason': 'no-lattice', 'confidence': 0})
        self.assertEqual((rec['status'], rec['cause']), ('withheld', 'detector-not-found'))
        self.assertEqual(tracker.fen, START)
        if sp.DEFAULT_DETECTOR.exists():  # the real binary on a blank frame
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / 'blank.png'
                Image.new('RGB', (640, 480), (40, 40, 40)).save(p)
                det = sp.run_detector([p])[str(p)]
                self.assertFalse(det['found'])
                self.assertFalse(det.get('error'))
                self.assertEqual(tracker.step(2, self.e4_img, det)['cause'], 'detector-not-found')

    def _fake_detector(self, d, body):
        exe = Path(d) / 'fake-detect'
        exe.write_text('#!/bin/sh\n' + body + '\n')
        exe.chmod(0o755)
        return exe

    def test_detector_error_is_not_board_not_found(self):
        tracker = sp.GameTracker(START, self.bridge)
        tracker.start(0, self.start_img, det_for(QUAD))
        with tempfile.TemporaryDirectory() as d:
            img = str(Path(d) / 'x.png')
            for body in ('exit 3', 'echo not-json', 'echo \'{"image": "' + img + '", "found": true}\''):
                det = sp.run_detector([img], self._fake_detector(d, body))[img]
                self.assertTrue(det['error'], body)
                self.assertFalse(det['found'])
                self.assertEqual(tracker.step(1, self.e4_img, det)['cause'], 'detector-error')
            det = sp.run_detector([img], Path(d) / 'missing-binary')[img]
            self.assertTrue(det['error'])

    def _tagged_finders(self, d):
        """Two stand-in finders that answer 'not found' with their own name as the reason."""
        for name, tag in (('fakeA', 'fake-a'), ('fakeB', 'fake-b')):
            exe = Path(d) / tag
            exe.write_text('#!/bin/sh\nfor p in "$@"; do echo "{\\"image\\": \\"$p\\", \\"found\\": false, '
                           '\\"confidence\\": 0, \\"reason\\": \\"' + tag + '\\"}"; done\n')
            exe.chmod(0o755)
            sp.FINDERS[name] = exe
        return Path(d) / 'x.png'

    def test_corner_finder_default_and_selection(self):
        self.assertEqual((sp.DEFAULT_FINDER, sp._FINDER['name']), ('original', 'original'))
        self.assertEqual(sp.finder_path(), sp.DEFAULT_DETECTOR)  # default = the frozen original binary
        self.assertEqual(sp.FINDERS['round2'].name, 'screen-board-detect-round2')
        self.assertNotIn('cornerFinder', sp.policy())  # default: policy hash layout unchanged
        with tempfile.TemporaryDirectory() as d:
            img = str(self._tagged_finders(d))
            for name, tag in (('fakeA', 'fake-a'), ('fakeB', 'fake-b'), ('fakeA', 'fake-a')):
                sp.set_finder(name)
                self.assertEqual(sp.finder_path(), sp.FINDERS[name])
                det = sp.run_detector([img])[img]  # no binary given: the selected finder runs
                self.assertEqual((det['reason'], det['found'], det.get('error')), (tag, False, None))
                self.assertEqual(sp.policy()['cornerFinder']['name'], name)
            self.assertEqual(sp.set_finder('original'), 'fakeA')  # returns the previous name for restoring
            self.assertNotIn('cornerFinder', sp.policy())
        if sp.FINDERS['round2'].exists():  # the real round-2 binary on a blank frame
            self.assertEqual(sp.set_finder('round2'), 'original')
            self.assertEqual(sp.policy()['cornerFinder']['binarySha256'][:8], '3292bcae')
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / 'blank.png'
                Image.new('RGB', (640, 480), (40, 40, 40)).save(p)
                det = sp.run_detector([p])[str(p)]
                self.assertFalse(det['found'])
                self.assertFalse(det.get('error'))

    def test_unknown_corner_finder_is_refused(self):
        with self.assertRaises(SystemExit) as ctx:
            sp.set_finder('round9')
        self.assertIn('unknown corner finder', str(ctx.exception))
        self.assertEqual(sp._FINDER['name'], 'original')  # a failed switch changes nothing

    def test_missing_corner_finder_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            img = str(self._tagged_finders(d))
            sp.set_finder('fakeA')
            sp.FINDERS['gone'] = Path(d) / 'no-such-binary'
            with self.assertRaises(SystemExit) as ctx:  # selecting a missing binary is refused at once
                sp.set_finder('gone')
            self.assertIn('missing or not executable', str(ctx.exception))
            self.assertEqual(sp._FINDER['name'], 'fakeA')  # still the chosen finder, not silently another one
            (Path(d) / 'not-exec').write_text('#!/bin/sh\n')  # present but not executable: refused too
            sp.FINDERS['noexec'] = Path(d) / 'not-exec'
            with self.assertRaises(SystemExit):
                sp.set_finder('noexec')
            # the selected binary disappears after selection: every picture is a detector error, and no other
            # finder (fakeB, or the original) answers in its place (real pictures, so any finder could answer them)
            imgs = [img, str(Path(d) / 'y.png')]
            for p in imgs:
                Image.new('RGB', (640, 480), (40, 40, 40)).save(p)
            (Path(d) / 'fake-a').unlink()
            dets = sp.run_detector(imgs)
            self.assertEqual([(x['found'], x['error']) for x in dets.values()], [(False, True)] * 2)
            self.assertTrue(all(x['reason'].startswith('detector-error:') for x in dets.values()))
            tracker = sp.GameTracker(START, self.bridge)
            rec = tracker.start(0, self.start_img, dets[img])
            self.assertEqual((rec['status'], rec['cause']), ('start-rejected', 'detector-error'))

    def test_scorer_exits_nonzero_on_detector_errors(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / 'scenes'
            (root / 'truth').mkdir(parents=True)
            game = multi_game([(START, None, 1), (AFTER_E4, 'e2e4', 1)])
            game.update(split='devx', id='g0')
            (root / 'truth/games.json').write_text(__import__('json').dumps({'games': [game]}))
            exe = self._fake_detector(d, 'exit 1')
            with self.assertRaises(SystemExit) as ctx:
                ev.evaluate_games(root, 'devx', Path(d) / 'out', exe, agrees=('1',))
            self.assertEqual(ctx.exception.code, 2)
            rep = ev.evaluate_games(root, 'devx', Path(d) / 'out2', exe, agrees=('1',), allow_detector_errors=True)
            self.assertEqual(len(rep['detectorErrors']), 2)
            self.assertEqual(rep['configs']['agree1']['modes']['strict']['startRejected'], 1)

    def test_orientation_jump_is_withheld(self):
        tracker = sp.GameTracker(START, self.bridge)
        tracker.start(0, self.start_img, det_for(QUAD))
        far = QUAD + np.array([300.0, 0.0])  # board jumped by more than a quarter side
        rec = tracker.step(1, self.e4_img, det_for(far))
        self.assertEqual((rec['status'], rec['cause']), ('withheld', 'orientation'))

    def _mini(self):
        imgs = {0: self.start_img, 1: self.e4_img, 2: self.e4_img, 3: screen_frame(AFTER_E5)}
        fens = [START, AFTER_E4, AFTER_E4, AFTER_E5]
        game = {'id': 'mini', 'startFen': START, 'frames': [
            {'index': i, 'file': f'{i}.png', 'kind': k, 'fen': fens[i], 'moveUci': m, 'flags': [],
             'corners': QUAD.tolist(), 'disturbance': {}}
            for i, (k, m) in enumerate([('start', None), ('move', 'e2e4'), ('repeat', None), ('move', 'e7e5')])]}
        scenes = Path('/nonexistent')
        dets = {str(scenes / f['file']): (det_for(QUAD) if f['index'] != 2 else {'found': False}) for f in game['frames']}
        return game, scenes, dets, imgs

    def test_mini_game_agree1_is_round_one_behaviour(self):
        game, scenes, dets, imgs = self._mini()
        with agree(1):
            for mode in ('strict', 're-review'):
                recs, summ, _ = ev.run_mode(mode, scenes, game, dets, self.bridge, {}, lambda f: imgs[f['index']])
                verdicts = [r['verdict']['verdict'] for r in recs]
                self.assertEqual(verdicts, ['start-accepted', 'correct-accepted', 'withheld', 'correct-accepted'], mode)
                self.assertEqual(summ['wrongAccepted'], 0)
                self.assertEqual(summ['reReviews'], 1 if mode == 're-review' else 0)
                self.assertEqual(recs[-1]['acceptedMove'], 'e7e5')
                self.assertTrue(all('pending' != r['status'] for r in recs))

    def test_mini_game_agree2_never_accepts_a_single_picture(self):
        game, scenes, dets, imgs = self._mini()
        with agree(2):
            recs, summ, _ = ev.run_mode('strict', scenes, game, dets, self.bridge, {}, lambda f: imgs[f['index']])
        self.assertEqual([r['status'] for r in recs], ['start-accepted', 'pending', 'withheld', 'withheld'])
        self.assertEqual(recs[1]['guard'], 'discarded')  # the withheld picture in between reset the count
        self.assertEqual(summ['wrongAccepted'], 0)

    def run_hand(self, positions, readings, n=2, mode='strict', dets=None):
        game = multi_game(positions)
        cache = {i: reading(fen) for i, fen in readings.items()}
        scenes = Path('/nonexistent')
        dets = dets or {}
        dets = {str(scenes / f['file']): dets.get(f['index'], det_for(QUAD)) for f in game['frames']}
        imgs = {f['index']: self.start_img for f in game['frames']}
        with agree(n):
            recs, summ, pos = ev.run_mode(mode, scenes, game, dets, self.bridge, cache, lambda f: imgs[f['index']])
        return game, recs, summ, pos

    def test_two_pictures_agreeing_on_a_wrong_move_is_wrong_accepted(self):
        _, recs, summ, pos = self.run_hand([(START, None, 1), (AFTER_E4, 'e2e4', 3)],
                                           {1: AFTER_E3, 2: AFTER_E3, 3: AFTER_E4})
        self.assertEqual([r['status'] for r in recs[1:]], ['pending', 'accepted', 'withheld'])
        self.assertEqual(recs[2]['acceptedMove'], 'e2e3')
        self.assertEqual((recs[2]['verdict']['verdict'], recs[2]['verdict']['wrongType']), ('WRONG-ACCEPTED', 'wrong-move'))
        self.assertEqual(summ['wrongAccepted'], 1)
        self.assertFalse(pos[0]['tracked'])

    def test_one_wrong_picture_is_blocked_then_two_correct_agree(self):
        game, recs, summ, pos = self.run_hand([(START, None, 1), (AFTER_E4, 'e2e4', 3)],
                                              {1: AFTER_E3, 2: AFTER_E4, 3: AFTER_E4})
        self.assertEqual([r['status'] for r in recs[1:]], ['pending', 'pending', 'accepted'])
        self.assertEqual(recs[1]['guard'], 'discarded')
        self.assertEqual((recs[3]['acceptedMove'], recs[3]['verdict']['verdict']), ('e2e4', 'correct-accepted'))
        f = game['frames']
        self.assertTrue(ev.guard_blocked_wrong(recs[1], f[1], f[0]))
        self.assertFalse(ev.guard_blocked_wrong(recs[2], f[2], f[0]))
        self.assertEqual(summ['wrongAccepted'], 0)
        self.assertTrue(pos[0]['tracked'])
        with agree(1):  # the same readings with no guard accept the wrong move at once
            _, recs1, summ1, _ = self.run_hand([(START, None, 1), (AFTER_E4, 'e2e4', 3)],
                                               {1: AFTER_E3, 2: AFTER_E4, 3: AFTER_E4}, n=1)
        self.assertEqual(recs1[1]['acceptedMove'], 'e2e3')
        self.assertGreaterEqual(summ1['wrongAccepted'], 1)

    def test_pictures_of_two_different_positions_never_confirm_each_other(self):
        # one picture of the e4 position, then two of the position after e4 e5 (real rendered pictures)
        game = multi_game([(START, None, 1), (AFTER_E4, 'e2e4', 1), (AFTER_E5, 'e7e5', 2)])
        imgs = {0: self.start_img, 1: self.e4_img, 2: screen_frame(AFTER_E5), 3: screen_frame(AFTER_E5)}
        scenes = Path('/nonexistent')
        dets = {str(scenes / f['file']): det_for(QUAD) for f in game['frames']}
        with agree(2):
            recs, summ, pos = ev.run_mode('strict', scenes, game, dets, self.bridge, {}, lambda f: imgs[f['index']])
        self.assertEqual([r['status'] for r in recs[1:]], ['pending', 'withheld', 'withheld'])
        self.assertEqual([r['inference']['status'] for r in recs[1:]], ['move', 'no-legal-explanation',
                                                                        'no-legal-explanation'])
        self.assertEqual(recs[1]['guard'], 'discarded')
        self.assertEqual(summ['wrongAccepted'], 0)
        self.assertEqual([p['tracked'] for p in pos], [False, False])
        # the guard compares move AND tracked FEN: same move text from another FEN does not count
        t = sp.GameTracker(START, self.bridge, {1: reading(AFTER_E4), 2: reading(AFTER_E4)})
        t.start(0, self.start_img, det_for(QUAD))
        with agree(2):
            t.step(1, None, det_for(QUAD))
            t.pending['fen'] = AFTER_E5  # simulate a pending move recorded from another tracked position
            self.assertEqual(t.step(2, None, det_for(QUAD))['status'], 'pending')

    def test_skip_unusable_variant(self):
        old = sp.POLICY['AGREE_INTERRUPTION']
        sp.POLICY['AGREE_INTERRUPTION'] = 'skip-unusable'
        try:
            # detector miss between two agreeing pictures: skipped, move confirmed
            _, recs, summ, _ = self.run_hand([(START, None, 1), (AFTER_E4, 'e2e4', 3)], {1: AFTER_E4, 3: AFTER_E4},
                                             dets={2: {'found': False}})
            self.assertEqual([r['status'] for r in recs[1:]], ['pending', 'withheld', 'accepted'])
            # a different position in between (no-legal-explanation) still resets
            game = multi_game([(START, None, 1), (AFTER_E4, 'e2e4', 1), (AFTER_E5, 'e7e5', 1), (AFTER_E4, None, 1)])
            cache = {1: reading(AFTER_E4), 2: reading(AFTER_E5), 3: reading(AFTER_E4)}
            scenes = Path('/nonexistent')
            dets = {str(scenes / f['file']): det_for(QUAD) for f in game['frames']}
            with agree(2):
                recs, summ, _ = ev.run_mode('strict', scenes, game, dets, self.bridge, cache, lambda f: self.start_img)
            self.assertEqual([r['status'] for r in recs[1:]], ['pending', 'withheld', 'pending'])
            self.assertEqual(recs[1]['guard'], 'discarded')
        finally:
            sp.POLICY['AGREE_INTERRUPTION'] = old

    def test_rereview_per_position_in_multi_picture_roots(self):
        _, recs, summ, pos = self.run_hand([(START, None, 1), (AFTER_E4, 'e2e4', 2), (AFTER_E5, 'e7e5', 2)],
                                           {1: AFTER_E4, 2: AFTER_E3, 3: AFTER_E5, 4: AFTER_E5}, mode='re-review')
        self.assertEqual(summ['reReviews'], 1)  # e4 position missed, reset once at its last picture
        self.assertEqual([p['tracked'] for p in pos], [False, True])
        self.assertEqual(recs[-1]['acceptedMove'], 'e7e5')
        self.assertEqual(summ['wrongAccepted'], 0)

    def test_multi_picture_start(self):
        # first start picture unusable (detector), second calibrates, third must read unchanged
        _, recs, summ, _ = self.run_hand([(START, None, 3), (AFTER_E4, 'e2e4', 2)], {2: START, 3: AFTER_E4, 4: AFTER_E4},
                                         dets={0: {'found': False}})
        self.assertEqual([r['status'] for r in recs[:3]], ['start-rejected', 'start-accepted', 'accepted'])
        self.assertEqual(recs[2]['startCheck'], 'agrees')
        self.assertTrue(summ['startAccepted'])
        self.assertFalse(summ['startAcceptedFirstPictureOnly'])
        # a later start picture that reads a move contradicts the start: whole start rejected
        _, recs, summ, _ = self.run_hand([(START, None, 2), (AFTER_E4, 'e2e4', 2)], {1: AFTER_E4})
        self.assertEqual(recs[1]['startCheck'], 'contradicts')
        self.assertFalse(summ['startAccepted'])

    def test_classifier_switch(self):
        sp.set_classifier('v2')
        self.assertIs(sp.clf(), oc)
        self.assertEqual(sp.DEFAULT_CLASSIFIER, 'v3')
        with self.assertRaises(SystemExit):
            sp.set_classifier('v9')
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / 'fake_partial_classifier.py').write_text('def calibrate(*a):\n    pass\n')
            sys.path.insert(0, d)
            old = dict(sp.CLASSIFIERS)
            try:
                sp.CLASSIFIERS.update(vmissing='no_such_classifier_module_xyz', vpartial='fake_partial_classifier')
                with self.assertRaises(SystemExit) as ctx:
                    sp.set_classifier('vmissing')
                self.assertIn('no_such_classifier_module_xyz.py', str(ctx.exception))
                with self.assertRaises(SystemExit) as ctx:
                    sp.set_classifier('vpartial')
                self.assertIn('must match the v2 API', str(ctx.exception))
                self.assertIs(sp.clf(), oc)  # a failed switch leaves the current classifier in place
            finally:
                sp.CLASSIFIERS.clear(); sp.CLASSIFIERS.update(old); sys.path.remove(d)

    def test_fresh_import_starts_on_v3_without_set_classifier(self):
        # a library caller that never picks a reader must get v3 (v2's blur-gate hole is closed only in v3.1)
        spec = importlib.util.spec_from_file_location('screen_pipeline_fresh', SP_PATH)
        fresh = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fresh)
        self.assertEqual(fresh._CLASSIFIER['name'], 'v3')
        self.assertEqual(fresh.clf().__name__, 'occupancy_classifier_v3')
        doc = fresh.policy()
        self.assertEqual(doc['classifierName'], 'v3')
        self.assertEqual(doc['classifier'], fresh.clf().policy())

    def test_v2_still_selectable_by_name(self):
        try:
            self.assertIs(sp.set_classifier('v2'), oc)
            self.assertIs(sp.clf(), oc)
            self.assertNotIn('classifierName', sp.policy())  # v2 keeps the round-1 hash layout
        finally:
            sp.set_classifier(sp.DEFAULT_CLASSIFIER)

    def test_more_unusable_pictures_than_the_skip_cap_drop_the_pending_move(self):
        cap = sp.POLICY['AGREE_MAX_SKIPPED']
        n = cap + 1
        _, recs, _, _ = self.run_hand([(START, None, 1), (AFTER_E4, 'e2e4', n + 2)], {1: AFTER_E4, n + 2: AFTER_E4},
                                      dets={i: {'found': False} for i in range(2, n + 2)})
        self.assertEqual(recs[1]['guard'], 'discarded')
        self.assertEqual(recs[-1]['status'], 'pending')  # the late picture starts a new count
        _, recs, _, _ = self.run_hand([(START, None, 1), (AFTER_E4, 'e2e4', cap + 2)],
                                      {1: AFTER_E4, cap + 2: AFTER_E4},
                                      dets={i: {'found': False} for i in range(2, cap + 2)})
        self.assertEqual(recs[-1]['status'], 'accepted')  # exactly the cap: still confirmed

    def test_move_on_a_later_start_picture_rejects_the_start_under_agree1(self):
        _, recs, summ, _ = self.run_hand([(START, None, 2), (AFTER_E4, 'e2e4', 1)], {1: AFTER_E4, 2: AFTER_E4}, n=1)
        self.assertEqual(recs[1]['startCheck'], 'contradicts')
        self.assertEqual(recs[1]['status'], 'start-rejected')
        self.assertFalse(summ['startAccepted'])
        self.assertEqual(summ['wrongAccepted'], 0)

    def test_stale_unchanged_counting_with_and_without_confirmation(self):
        # the e4 position is misread as "nothing moved" on all three pictures
        for n, confirmed in ((1, [True, True, True]), (2, [False, True, True])):
            _, recs, summ, _ = self.run_hand([(START, None, 1), (AFTER_E4, 'e2e4', 3)],
                                             {1: START, 2: START, 3: START}, n=n)
            verdicts = [r['verdict'] for r in recs[1:]]
            self.assertEqual([v.get('staleUnchanged') for v in verdicts], [True] * 3)
            self.assertEqual([v.get('staleConfirmed') for v in verdicts], confirmed, n)
            self.assertEqual(summ['wrongAccepted'], 3)
        b = ev._empty_bucket()
        for v in verdicts:
            ev._add(b, v, 0)
        self.assertEqual((b['staleUnchanged'], b['staleConfirmed'], b['wrongMoveAccepted']), (3, 2, 0))
        # a single misread right after a confirmed move is not reported as current
        _, recs, _, _ = self.run_hand([(START, None, 1), (AFTER_E4, 'e2e4', 2), (AFTER_E5, 'e7e5', 2)],
                                      {1: AFTER_E4, 2: AFTER_E4, 3: AFTER_E4, 4: AFTER_E5}, n=2)
        self.assertTrue(recs[2]['currentConfirmed'])       # move confirmed by agreement
        self.assertTrue(recs[3]['verdict'].get('staleUnchanged'))
        self.assertFalse(recs[3]['currentConfirmed'])      # one stale "unchanged" is not enough

    def test_self_aware_mode_only_reviews_when_the_pipeline_asks(self):
        positions = [(START, None, 1), (AFTER_E4, 'e2e4', 2), (AFTER_E5, 'e7e5', 2)]
        readings = {1: START, 2: START, 3: AFTER_E5, 4: AFTER_E5}  # e4 silently missed (read as unchanged)
        _, recs, summ, pos = self.run_hand(positions, readings, n=2, mode='self-aware')
        self.assertEqual([r.get('reviewRequested') for r in recs[1:]], [None, None, 'no-legal-explanation', None])
        self.assertEqual(summ['reReviews'], 1)
        self.assertEqual([p['tracked'] for p in pos], [False, True])
        self.assertEqual(recs[-1]['status'], 'accepted')
        # the oracle mode would have reset at the end of the missed e4 position instead
        _, _, summ_rr, _ = self.run_hand(positions, readings, n=2, mode='re-review')
        self.assertEqual(summ_rr['reReviews'], 1)
        # withheld pictures in a row trigger a request at the policy count
        k = sp.POLICY['SELF_REVIEW_AFTER_WITHHELD']
        _, recs, summ, _ = self.run_hand([(START, None, 1), (AFTER_E4, 'e2e4', k)], {}, n=2, mode='self-aware',
                                         dets={i: {'found': False} for i in range(1, k + 1)})
        self.assertEqual([bool(r.get('reviewRequested')) for r in recs[1:]], [False] * (k - 1) + [True])

    def test_v3_runs_through_the_whole_pipeline_on_a_smoke2_game(self):
        root = Path('/Users/alexmunzon/chess-builds/pipeline-2026-11-15/scenes-v2')
        if not (root / 'truth/games.json').exists() or importlib.util.find_spec('occupancy_classifier_v3') is None:
            self.skipTest('scenes-v2 or v3 classifier not present')
        game = next(g for g in sp.load_games(root)['games'] if g['id'] == 'smoke2-g00')
        try:
            sp.set_classifier('v3')
            dets = sp.run_detector([root / f['file'] for f in game['frames']])
            with agree(2):
                recs, summ, pos = ev.run_mode('strict', root, game, dets, self.bridge, {},
                                              lambda f: (lambda: sp.load_image(root / f['file'])[0]))
        finally:
            sp.set_classifier('v2')
        self.assertTrue(summ['startAccepted'])
        self.assertEqual(summ['wrongAccepted'], 0)
        self.assertGreaterEqual(sum(p['tracked'] for p in pos), len(pos) - 1)


class ScorerTests(unittest.TestCase):
    prev = {'fen': START}

    def rec(self, status, move=None, after=START, before=START, labels=None):
        r = {'status': 'accepted' if status in ('move', 'unchanged') else 'withheld', 'trackedFenBefore': before,
             'trackedFen': after, 'inference': {'status': status}}
        if move:
            r['acceptedMove'] = move
        if r['status'] == 'withheld':
            r['cause'] = 'classifier-unknowns'
        if labels:
            r['labelsA8H1'] = labels
        return r

    def test_wrong_move_counts_as_wrong_accepted(self):
        wrong_fen = 'rnbqkbnr/pppppppp/8/8/8/4P3/PPPP1PPP/RNBQKBNR b KQkq - 0 1'
        e3_labels = ''.join({'empty': '.', 'white': 'w', 'black': 'b'}[x] for x in ev.truth_occ_a8h1(wrong_fen))
        v = ev.score_frame(self.rec('move', 'e2e3', wrong_fen, labels=e3_labels),
                           {'kind': 'move', 'fen': AFTER_E4, 'moveUci': 'e2e4'}, self.prev)
        self.assertEqual((v['verdict'], v['wrongType']), ('WRONG-ACCEPTED', 'wrong-move'))
        self.assertEqual([m['square'] for m in v['misread']], ['e4', 'e3'])

    def test_missed_move_counts_as_wrong_accepted(self):
        v = ev.score_frame(self.rec('unchanged', after=START), {'kind': 'move', 'fen': AFTER_E4, 'moveUci': 'e2e4'},
                           self.prev)
        self.assertEqual((v['verdict'], v['wrongType']), ('WRONG-ACCEPTED', 'unchanged-but-move-happened'))

    def test_false_move_on_repeat_counts_as_wrong_accepted(self):
        v = ev.score_frame(self.rec('move', 'e2e4', AFTER_E4), {'kind': 'repeat', 'fen': START, 'moveUci': None},
                           self.prev)
        self.assertEqual((v['verdict'], v['wrongType']), ('WRONG-ACCEPTED', 'move-on-repeat-frame'))

    def test_correct_and_withheld(self):
        v = ev.score_frame(self.rec('move', 'e2e4', AFTER_E4), {'kind': 'move', 'fen': AFTER_E4, 'moveUci': 'e2e4'},
                           self.prev)
        self.assertEqual(v['verdict'], 'correct-accepted')
        v = ev.score_frame(self.rec('unchanged'), {'kind': 'repeat', 'fen': START, 'moveUci': None}, self.prev)
        self.assertEqual(v['verdict'], 'correct-accepted')
        v = ev.score_frame(self.rec('uncertain'), {'kind': 'move', 'fen': AFTER_E4, 'moveUci': 'e2e4'}, self.prev)
        self.assertEqual((v['verdict'], v['hidesRealMove']), ('withheld', True))

    def test_bucket_counts(self):
        b = ev._empty_bucket()
        for v in ({'verdict': 'WRONG-ACCEPTED'}, {'verdict': 'correct-accepted'},
                  {'verdict': 'withheld', 'cause': 'detector-error'}):
            ev._add(b, v, 0)
        self.assertEqual((b['wrongAccepted'], b['correctAccepted'], b['withheldByCause']['detector-error']), (1, 1, 1))


def warp_board(board, quad=QUAD):
    """A 512x512 playing area warped into a dark 1280x800 frame at `quad` (same geometry as screen_frame)."""
    h = sp.homography(quad, [(0, 0), (512, 0), (512, 512), (0, 512)])
    xs, ys = np.meshgrid(np.arange(W, dtype=float), np.arange(H, dtype=float))
    den = h[2, 0] * xs + h[2, 1] * ys + h[2, 2]
    u = (h[0, 0] * xs + h[0, 1] * ys + h[0, 2]) / den - 0.5
    v = (h[1, 0] * xs + h[1, 1] * ys + h[1, 2]) / den - 0.5
    inside = ((u >= -0.5) & (u <= 511.5) & (v >= -0.5) & (v <= 511.5))[..., None]
    return np.where(inside, sp._bilinear(np.asarray(board, np.float32), u, v), 30.0).astype(np.float32)


def fake_reader(name, calibrate):
    """A stand-in square reader with the v2 API. classify() fails the test if it is ever called."""
    import types
    mod = types.ModuleType(name)
    mod.CalibrationError = type('CalibrationError', (Exception,), {})
    mod.calls = []

    def cal(panel, stated):
        mod.calls.append('calibrate')
        return calibrate(mod)

    def classify(panel, calibration):
        raise AssertionError(f'{name}.classify must not be called')
    mod.calibrate, mod.classify = cal, classify
    return mod


class StartFallbackTests(unittest.TestCase):
    """Backup reader at game start (START_FALLBACK_CLASSIFIER). Solid ('flat') pieces drawn by the scene generator
    are a real case where v3.1 refuses the start and v4.3 accepts it (measured: v3 0 of 4 orientations, v4 exactly 1)."""

    @classmethod
    def setUpClass(cls):
        import make_screen_game_scenes as gen  # generator drawing only, never used by a reader
        cls.bridge = sp.InferBridge()
        cls.flat = {(fen, wb): warp_board(gen.stress_board(fen, wb, {'style': 'flat'}))
                    for fen in (START, AFTER_E4) for wb in (True, False)}
        cls.classic_start = screen_frame(START)
        cls.classic_e4 = screen_frame(AFTER_E4)

    @classmethod
    def tearDownClass(cls):
        cls.bridge.close()

    def setUp(self):
        # leave global state exactly as found (earlier tests may leave v2 selected; that is theirs to keep)
        found = (dict(sp._CLASSIFIER), sp.START_FALLBACK_CLASSIFIER, dict(sp.CLASSIFIERS), dict(sp.POLICY),
                 sp.START_SELF_CHECK)

        def restore():
            sp._CLASSIFIER.clear(); sp._CLASSIFIER.update(found[0])
            sp.START_FALLBACK_CLASSIFIER = found[1]
            sp.START_SELF_CHECK = found[4]
            sp.CLASSIFIERS.clear(); sp.CLASSIFIERS.update(found[2])
            sp.POLICY.clear(); sp.POLICY.update(found[3])
            for name in [n for n in sys.modules if n.startswith('fake_fallback_')]:
                del sys.modules[name]
        self.addCleanup(restore)
        sp.set_classifier('v3')

    def register(self, key, mod):
        sys.modules[mod.__name__] = mod
        sp.CLASSIFIERS[key] = mod.__name__
        return mod

    def test_off_by_default_and_a_v3_refusal_stays_a_refusal(self):
        spec = importlib.util.spec_from_file_location('screen_pipeline_fresh_fb', SP_PATH)
        fresh = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fresh)
        self.assertIsNone(fresh.START_FALLBACK_CLASSIFIER)
        self.assertNotIn('startFallback', fresh.policy())
        sp.set_start_fallback(None)
        tracker = sp.GameTracker(START, self.bridge)
        rec = tracker.start(0, self.flat[(START, True)], det_for(QUAD))
        self.assertEqual((rec['status'], rec['cause']), ('start-rejected', '0-rotations-calibrated'))
        self.assertEqual(set(rec), {'index', 'stage', 'detector', 'timingsMs', 'rotationsTried', 'status', 'cause',
                                    'trackedFen'})  # the record layout of the committed code: nothing new when off
        self.assertFalse(tracker.started)
        rec = tracker.start(0, self.classic_start, det_for(QUAD))  # off: an accepted start has no new fields either
        self.assertEqual(rec['status'], 'start-accepted')
        self.assertNotIn('startReader', rec)
        self.assertNotIn('reader', tracker.step(1, self.classic_e4, det_for(QUAD)))

    def test_v3_accepts_and_the_fallback_is_never_asked(self):
        spy = self.register('vspy', fake_reader('fake_fallback_spy', lambda m: {'fake': True}))  # records any call
        sp.set_start_fallback('vspy')
        rec = sp.GameTracker(START, self.bridge).start(0, self.classic_start, det_for(QUAD))
        self.assertEqual((rec['status'], rec['startReader'], rec['startFallback']), ('start-accepted', 'v3', 'not-needed'))
        self.assertEqual(spy.calls, [])
        sp.set_start_fallback('v4')
        tracker = sp.GameTracker(START, self.bridge)
        rec = tracker.start(0, self.classic_start, det_for(QUAD))
        self.assertEqual((rec['startReader'], rec['startFallback']), ('v3', 'not-needed'))
        self.assertNotIn('fallbackRotationsTried', rec)
        with agree(2):
            recs = [tracker.step(i, self.classic_e4, det_for(QUAD)) for i in (1, 2)]
        self.assertEqual(recs[1]['acceptedMove'], 'e2e4')
        self.assertEqual([r['reader'] for r in recs], ['v3', 'v3'])
        self.assertIsNone(tracker.reader_module)
        self.assertEqual(set(tracker.cache), {1, 2})  # default reader: the cache keys of the committed code

    def test_v3_refuses_v4_accepts_and_v4_reads_the_rest_of_the_game(self):
        sp.set_start_fallback('v4')
        for wb, rotation in ((True, 0), (False, 2)):
            tracker = sp.GameTracker(START, self.bridge)
            rec = tracker.start(0, self.flat[(START, wb)], det_for(QUAD))
            self.assertEqual((rec['status'], rec['startReader'], rec['startFallback'], rec['rotation']),
                             ('start-accepted', 'v4', 'accepted', rotation))
            self.assertEqual([t['calibrated'] for t in rec['rotationsTried']], [False] * 4)  # v3.1 refused
            self.assertEqual(sum(t['calibrated'] for t in rec['fallbackRotationsTried']), 1)
            self.assertIs(tracker.reader_module, sys.modules[sp.CLASSIFIERS['v4']])
            with agree(2):
                recs = [tracker.step(i, self.flat[(AFTER_E4, wb)], det_for(QUAD)) for i in (1, 2)]
            self.assertEqual([r['status'] for r in recs], ['pending', 'accepted'])
            self.assertEqual(recs[1]['acceptedMove'], 'e2e4')
            self.assertEqual([r['reader'] for r in recs], ['v4', 'v4'])
            self.assertEqual(set(tracker.cache), {('v4', 1), ('v4', 2)})  # never mixed with the default's readings
            tracker.human_rereview(AFTER_E4)  # a re-review keeps the start's reader and calibration
            self.assertEqual(tracker.step(3, self.flat[(AFTER_E4, wb)], det_for(QUAD))['reader'], 'v4')
        self.assertEqual(sp._CLASSIFIER['name'], 'v3')  # the global default reader is untouched
        doc = sp.policy()
        self.assertEqual(doc['startFallback']['classifierName'], 'v4')

    def test_v3_and_v4_both_refuse_is_a_refusal(self):
        sp.set_start_fallback('v4')
        for picture in (self.classic_start, self.flat[(START, True)]):  # the screen shows the start, e4 is claimed
            tracker = sp.GameTracker(AFTER_E4, self.bridge)
            rec = tracker.start(0, picture, det_for(QUAD))
            self.assertEqual((rec['status'], rec['startFallback'], rec['cause']),
                             ('start-rejected', 'refused', '0-rotations-calibrated'))
            self.assertNotIn('startReader', rec)
            self.assertFalse(tracker.started)
            self.assertEqual(tracker.step(1, picture, det_for(QUAD))['cause'], 'no-start')

    def test_ambiguous_orientation_is_never_handed_to_the_fallback(self):
        self.register('vall', fake_reader('fake_fallback_all', lambda m: {'fake': True}))  # fits every orientation
        spy = self.register('vspy', fake_reader('fake_fallback_spy2', lambda m: {'fake': True}))
        sp.set_classifier('vall')
        sp.set_start_fallback('vspy')
        rec = sp.GameTracker(START, self.bridge).start(0, self.classic_start, det_for(QUAD))
        self.assertEqual((rec['status'], rec['cause'], rec['startFallback']),
                         ('start-rejected', '4-rotations-calibrated', 'not-tried'))
        self.assertEqual(spy.calls, [])

    def test_setting_is_validated_and_read_once_per_game(self):
        self.assertIsNone(sp.set_start_fallback('v4'))
        with self.assertRaises(SystemExit):
            sp.set_start_fallback('v9')
        self.assertEqual(sp.START_FALLBACK_CLASSIFIER, 'v4')  # a failed set changes nothing
        tracker = sp.GameTracker(START, self.bridge)
        self.assertEqual(sp.set_start_fallback(None), 'v4')
        rec = tracker.start(0, self.flat[(START, True)], det_for(QUAD))  # the game keeps the setting it began with
        self.assertEqual(rec['startReader'], 'v4')

    def not_the_start_flat(self):
        """Three solid-piece pictures that are NOT the start, built the way the v4.3 review's attack_start.py builds
        them: v4.3's start check alone accepts each (v3.1 refuses each), its own reading of the picture does not."""
        import make_screen_game_scenes as gen

        def xy(sq):
            return 'abcdefgh'.index(sq[0]) * 64, (8 - int(sq[1])) * 64

        def is_dark(sq):
            return ('abcdefgh'.index(sq[0]) + 8 - int(sq[1])) % 2 == 1

        def board(hide=None):
            return np.asarray(gen.stress_board(START, True, {'style': 'flat', 'hide': hide} if hide else
                                               {'style': 'flat'}), float)

        def sprite(b, label, sq, dx=0, dy=0):
            rgb, a = gen.sprite(label, is_dark(sq), 'flat')
            x, y = xy(sq)
            blk = b[y + dy:y + dy + 64, x + dx:x + dx + 64]
            a = a[:blk.shape[0], :blk.shape[1], None]
            blk[:] = blk * (1 - a) + rgb[:blk.shape[0], :blk.shape[1]] * a
        shifted = board('e2')
        sprite(shifted, 'P', 'e2', 0, -10)  # the e2 pawn drawn 10 px up, off its square (a move being animated)
        shape = board('e2')
        x, y = xy('e2')
        shape[y + 12:y + 53, x + 18:x + 47] = (250, 250, 247)  # e2 empty, a piece-coloured box on it
        layered = board()
        sprite(layered, 'p', 'd5')  # an extra black pawn on d5 under a 90 % layer in the square's own colour
        x, y = xy('d5')
        light, dark = gen.THEMES['classic']
        layered[y:y + 64, x:x + 64] = layered[y:y + 64, x:x + 64] * 0.1 + np.array(dark if is_dark('d5') else light) * 0.9
        return {'piece off its square': shifted, 'shape on an empty start square': shape,
                'extra piece under a layer': layered}

    def test_fallback_self_check_refuses_pictures_that_are_not_the_start(self):
        sp.set_start_fallback('v4')
        for name, b in self.not_the_start_flat().items():
            tracker = sp.GameTracker(START, self.bridge)
            rec = tracker.start(0, warp_board(b), det_for(QUAD))
            self.assertEqual([t['calibrated'] for t in rec['rotationsTried']], [False] * 4, name)  # v3.1 refused
            self.assertEqual(sum(t['calibrated'] for t in rec['fallbackRotationsTried']), 1, name)  # v4.3 calibrated
            self.assertEqual((rec['status'], rec['startFallback']), ('start-rejected', 'refused-self-check'), name)
            self.assertFalse(rec['fallbackSelfCheck']['passed'], name)
            self.assertGreaterEqual(rec['fallbackSelfCheck']['squaresNotAsStated'], 1, name)
            self.assertFalse(tracker.started, name)
            self.assertNotIn('startReader', rec)

    def test_real_solid_piece_starts_still_come_through_the_self_check(self):
        root = Path('/Users/alexmunzon/chess-builds/pipeline-2026-11-15/scenes-stress')
        if not (root / 'truth/games.json').exists() or not sp.DEFAULT_DETECTOR.exists():
            self.skipTest('scenes-stress or the corner detector not present')
        sp.set_start_fallback('v4')
        games = [g for g in sp.load_games(root)['games'] if g['id'].startswith('stressdev-style-flat-')]
        self.assertEqual(len(games), 3)
        for g in games:
            starts = [f for f in g['frames'] if ev.position_of(f) == 0]
            dets = sp.run_detector([root / f['file'] for f in starts])
            tracker = sp.GameTracker(g['startFen'], self.bridge)
            recs = [tracker.start(f['index'], sp.load_image(root / f['file'])[0], dets[str(root / f['file'])])
                    for f in starts[:1]]
            self.assertEqual((recs[0]['status'], recs[0]['startReader']), ('start-accepted', 'v4'), g['id'])
            self.assertTrue(recs[0]['fallbackSelfCheck']['passed'], g['id'])

    def test_scorer_reports_which_reader_accepted_the_start(self):
        game = multi_game([(START, None, 1), (AFTER_E4, 'e2e4', 2)])
        scenes = Path('/nonexistent')
        dets = {str(scenes / f['file']): det_for(QUAD) for f in game['frames']}
        pics = {0: self.flat[(START, True)], 1: self.flat[(AFTER_E4, True)], 2: self.flat[(AFTER_E4, True)]}
        sp.set_start_fallback(None)
        with agree(2):
            _, summ, _ = ev.run_mode('strict', scenes, game, dets, self.bridge, {}, lambda f: pics[f['index']])
        self.assertFalse(summ['startAccepted'])
        self.assertNotIn('startReader', summ)
        sp.set_start_fallback('v4')
        with agree(2):
            recs, summ, pos = ev.run_mode('strict', scenes, game, dets, self.bridge, {}, lambda f: pics[f['index']])
        self.assertEqual((summ['startAccepted'], summ['startReader'], summ['wrongAccepted']), (True, 'v4', 0))
        self.assertEqual(recs[-1]['acceptedMove'], 'e2e4')
        head = ev.summarise('agree2/strict', [(game, recs)], [summ], [(game, pos)], scenes, Path('/nonexistent'),
                            [], [], {})
        self.assertEqual((head['startsViaFallback'], head['startsByReader']), (1, {'v4': 1}))


class StartSelfCheckTests(unittest.TestCase):
    """The default reader's start self-check (START_SELF_CHECK, off by default). Classic pictures that are NOT the start,
    built the way the v4.3 review's attack_start.py builds them, which v3.1's start check alone accepts."""

    @classmethod
    def setUpClass(cls):
        import make_screen_game_scenes as gen  # generator drawing only, never used by a reader
        cls.bridge = sp.InferBridge()
        cls.classic_start = screen_frame(START)
        cls.classic_e4 = screen_frame(AFTER_E4)
        cls.black_start = screen_frame(START, black_at_bottom=True)

        def xy(sq):
            return 'abcdefgh'.index(sq[0]) * 64, (8 - int(sq[1])) * 64

        def is_dark(sq):
            return ('abcdefgh'.index(sq[0]) + 8 - int(sq[1])) % 2 == 1

        def board(hide=None):
            return np.asarray(gen.stress_board(START, True, {'hide': hide} if hide else {}), float)

        def shifted(dy):  # the e2 pawn drawn dy px up, partly off its square (the first move being animated)
            b = board('e2')
            rgb, a = gen.sprite('P', is_dark('e2'), 'classic')
            x, y = xy('e2')
            blk = b[y - dy:y - dy + 64, x:x + 64]
            blk[:] = blk * (1 - a[..., None]) + rgb * a[..., None]
            return warp_board(b)
        # measured on the review's attack pictures: v3.1's start check alone accepts these, its self-check refuses them
        cls.doctored = {f'e2 pawn {dy} px off its square': shifted(dy) for dy in (6, 14)}

    @classmethod
    def tearDownClass(cls):
        cls.bridge.close()

    def setUp(self):
        found = (dict(sp._CLASSIFIER), sp.START_FALLBACK_CLASSIFIER, dict(sp.CLASSIFIERS), sp.START_SELF_CHECK)

        def restore():
            sp._CLASSIFIER.clear(); sp._CLASSIFIER.update(found[0])
            sp.START_FALLBACK_CLASSIFIER = found[1]
            sp.CLASSIFIERS.clear(); sp.CLASSIFIERS.update(found[2])
            sp.START_SELF_CHECK = found[3]
            for name in [n for n in sys.modules if n.startswith('fake_fallback_')]:
                del sys.modules[name]
        self.addCleanup(restore)
        sp.set_classifier('v3')
        sp.set_start_fallback(None)

    def test_off_by_default_and_nothing_changes(self):
        spec = importlib.util.spec_from_file_location('screen_pipeline_fresh_sc', SP_PATH)
        fresh = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fresh)
        self.assertIs(fresh.START_SELF_CHECK, False)
        self.assertNotIn('startSelfCheck', fresh.policy())
        off_hash = sp.policy()['sha256']
        self.assertIs(sp.set_start_self_check(True), False)
        self.assertIn('startSelfCheck', sp.policy())
        self.assertNotEqual(sp.policy()['sha256'], off_hash)
        self.assertIs(sp.set_start_self_check(False), True)
        self.assertEqual(sp.policy()['sha256'], off_hash)  # off again: the policy hash of the code before the option
        rec = sp.GameTracker(START, self.bridge).start(0, self.classic_start, det_for(QUAD))
        self.assertEqual(rec['status'], 'start-accepted')
        self.assertEqual(set(rec), {'index', 'stage', 'detector', 'timingsMs', 'rotationsTried', 'status', 'rotation',
                                    'trackedFen', 'currentConfirmed', 'startLabel'})  # the record layout before the option
        for name, picture in self.doctored.items():  # off: the plain start check accepts these pictures
            rec = sp.GameTracker(START, self.bridge).start(0, picture, det_for(QUAD))
            self.assertEqual(rec['status'], 'start-accepted', name)
            self.assertNotIn('startSelfCheck', rec)

    def test_on_refuses_doctored_starts_the_plain_check_accepts(self):
        sp.set_start_self_check(True)
        for name, picture in self.doctored.items():
            tracker = sp.GameTracker(START, self.bridge)
            rec = tracker.start(0, picture, det_for(QUAD))
            self.assertEqual(sum(t['calibrated'] for t in rec['rotationsTried']), 1, name)  # v3.1 calibrated
            self.assertEqual((rec['status'], rec['cause']), ('start-rejected', 'start-self-check-failed'), name)
            self.assertFalse(rec['startSelfCheck']['passed'], name)
            self.assertGreaterEqual(rec['startSelfCheck']['squaresNotAsStated'], 1, name)
            self.assertFalse(tracker.started, name)
            self.assertEqual(tracker.step(1, self.classic_e4, det_for(QUAD))['cause'], 'no-start', name)

    def test_on_still_accepts_a_clean_start_and_tracks_the_game(self):
        sp.set_start_self_check(True)
        for picture, rotation in ((self.classic_start, 0), (self.black_start, 2)):
            rec = sp.GameTracker(START, self.bridge).start(0, picture, det_for(QUAD))
            self.assertEqual((rec['status'], rec['rotation']), ('start-accepted', rotation))
            self.assertEqual((rec['startSelfCheck']['passed'], rec['startSelfCheck']['squaresNotAsStated']), (True, 0))
        tracker = sp.GameTracker(START, self.bridge)
        tracker.start(0, self.classic_start, det_for(QUAD))
        with agree(2):
            recs = [tracker.step(i, self.classic_e4, det_for(QUAD)) for i in (1, 2)]
        self.assertEqual(recs[1]['acceptedMove'], 'e2e4')

    def test_a_refused_start_is_not_handed_to_the_fallback(self):
        spy = sys.modules.setdefault('fake_fallback_sc_spy', fake_reader('fake_fallback_sc_spy', lambda m: {'fake': True}))
        sp.CLASSIFIERS['vspy'] = spy.__name__
        sp.set_start_fallback('vspy')
        sp.set_start_self_check(True)
        rec = sp.GameTracker(START, self.bridge).start(0, self.doctored['e2 pawn 6 px off its square'], det_for(QUAD))
        self.assertEqual((rec['status'], rec['cause'], rec['startFallback']),
                         ('start-rejected', 'start-self-check-failed', 'not-tried'))
        self.assertEqual(spy.calls, [])

    def test_setting_is_read_once_per_game(self):
        sp.set_start_self_check(True)
        tracker = sp.GameTracker(START, self.bridge)
        sp.set_start_self_check(False)
        rec = tracker.start(0, self.doctored['e2 pawn 6 px off its square'], det_for(QUAD))
        self.assertEqual(rec['cause'], 'start-self-check-failed')  # the game keeps the setting it began with


if __name__ == '__main__':
    unittest.main(verbosity=1)
