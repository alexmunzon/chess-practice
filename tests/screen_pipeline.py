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


if __name__ == '__main__':
    unittest.main(verbosity=1)
