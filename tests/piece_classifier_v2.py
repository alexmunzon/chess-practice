#!/usr/bin/env python3
"""Piece-type reader v2: contract and safety rules on synthetic rendered boards (not camera evidence).

Each safety rule has a test that fails when the rule is removed or loosened (checked with mutated private copies,
see docs/PIECE_CLASSIFIER.md, "v2").
Run: python3 -B tests/piece_classifier_v2.py
"""
from pathlib import Path
import sys
import unittest

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/recognition'))
sys.path.insert(0, str(ROOT / 'scripts/simulation'))
import piece_classifier_v2 as pc
from render import render

START = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
# 1.e4 e5 2.Nf3 Nc6 3.Bc4 Bc5 4.Qe2 Qe7 (pieces of every type on new squares of both colours)
MIDGAME = 'r1b1k1nr/ppppqppp/2n5/2b1p3/2B1P3/5N2/PPPPQPPP/RNB1K2R w KQkq - 6 5'
QUAD_A = [[70, 66], [700, 60], [698, 702], [60, 712]]
QUAD_B = [[80, 50], [690, 76], [705, 690], [52, 700]]
SMOKE = Path('/Users/alexmunzon/chess-builds/pipeline-2026-11-15/scenes')
THIN = set('QKqk')        # one start square each in the standard start


def board_corners(quad):
    src = [(0, 0), (640, 0), (640, 640), (0, 640)]
    h = pc._homography(src, quad)
    pts = []
    for u, v in [(64, 64), (576, 64), (576, 576), (64, 576)]:
        p = h @ np.array([u, v, 1.0])
        pts.append([p[0] / p[2] - 0.5, p[1] / p[2] - 0.5])
    return pts


def scene(quad, **extra):
    return {'quad': quad, 'brightness': 1.0, 'blur': 0.3, **extra}


def panel_box(square):
    col, row = 'abcdefgh'.index(square[0]), 8 - int(square[1])
    return [64 + col * 64, 64 + row * 64, 64 + col * 64 + 63, 64 + row * 64 + 63]


def centre(corners, square):
    h = pc._homography([(0, 0), (8, 0), (8, 8), (0, 8)], np.asarray(corners))
    col, row = 'abcdefgh'.index(square[0]), 8 - int(square[1])
    p = h @ np.array([col + 0.5, row + 0.5, 1.0])
    return p[0] / p[2], p[1] / p[2]


def with_arrow(image, corners, a, b, width=14):
    """Semi-transparent orange arrow shaft from square a to square b, as chess sites draw them."""
    base = image.convert('RGBA')
    layer = Image.new('RGBA', base.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).line([centre(corners, a), centre(corners, b)], fill=(255, 170, 0, 170), width=width)
    return Image.alpha_composite(base, layer).convert('RGB')


def with_highlight(image, corners, square, rgba=(255, 255, 0, 100)):
    """Semi-transparent last-move highlight filling one square, as chess sites draw it."""
    base = image.convert('RGBA')
    layer = Image.new('RGBA', base.size, (0, 0, 0, 0))
    h = pc._homography([(0, 0), (8, 0), (8, 8), (0, 8)], np.asarray(corners))
    col, row = 'abcdefgh'.index(square[0]), 8 - int(square[1])
    pts = []
    for a, b in ((0, 0), (1, 0), (1, 1), (0, 1)):
        q = h @ np.array([col + a, row + b, 1.0])
        pts.append((q[0] / q[2], q[1] / q[2]))
    ImageDraw.Draw(layer).polygon(pts, fill=rgba)
    return Image.alpha_composite(base, layer).convert('RGB')


def with_move_dot(image, corners, square, alpha=30, radius=9):
    """Faint grey legal-move dot in the middle of an empty square, as chess sites draw move hints."""
    base = image.convert('RGBA')
    layer = Image.new('RGBA', base.size, (0, 0, 0, 0))
    x, y = centre(corners, square)
    ImageDraw.Draw(layer).ellipse((x - radius, y - radius, x + radius, y + radius), fill=(0, 0, 0, alpha))
    return Image.alpha_composite(base, layer).convert('RGB')


def with_noise(image, sd, seed=5):
    """Camera-like pixel noise (float array, values kept in 0..255)."""
    a = np.asarray(image, np.float32)
    return np.clip(a + np.random.default_rng(seed).normal(0, sd, a.shape), 0, 255).astype(np.float32)


def with_glare(image, corners, square, amp=200.0, radius=26.0):
    img = np.asarray(image, float)
    cx, cy = centre(corners, square)
    yy, xx = np.mgrid[0:img.shape[0], 0:img.shape[1]]
    spot = amp * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * radius ** 2))[..., None]
    return Image.fromarray(np.clip(img + spot, 0, 255).astype(np.uint8))


def labels(result):
    return {s: r['label'] for s, r in result.items()}


def read_twice(image, corners, cal):
    """A settled picture seen in two consecutive frames: the second reading is confirmed by the first."""
    return pc.read(image, corners, cal, previous=pc.read(image, corners, cal))


class Contract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cal = pc.calibrate([(render(START, scene(QUAD_A)), board_corners(QUAD_A))], START)
        img = render(START, scene(QUAD_B))
        cls.tiles, cls.inside, cls.q = pc._square_tiles_q(img, board_corners(QUAD_B), cls.cal['lumContrast'])

    def settled(self, tiles):
        return pc._settled(tiles, self.inside, self.cal, self.q)

    def check(self, fen, result):
        """Every square: the true piece or 'unsure'; every piece of a well-evidenced kind is named."""
        truth = pc.placement(fen)
        self.assertEqual(set(result), set(pc.SQUARES))
        for s in pc.SQUARES:
            want = truth.get(s)
            got = result[s]['label']
            if want is None or want in THIN:
                self.assertEqual(got, 'unsure', (s, result[s]))
            else:
                self.assertEqual(got, want, (s, result[s]))

    # ---- basic contract -------------------------------------------------------------------------------
    def test_clean_start_is_accepted(self):
        self.assertEqual(self.cal['state'], 'ok', self.cal['problems'])
        self.assertEqual(self.cal['evidence']['P'], 8)
        self.assertEqual(self.cal['evidence']['Q'], 1)

    def test_start_position_read_on_another_view(self):
        img = render(START, scene(QUAD_B, brightness=0.85))
        self.check(START, read_twice(img, board_corners(QUAD_B), self.cal))

    def test_moved_pieces_named_on_new_square_colours(self):
        self.check(MIDGAME, read_twice(render(MIDGAME, scene(QUAD_B)), board_corners(QUAD_B), self.cal))

    def test_board_seen_from_blacks_side(self):
        def flipped(fen):
            ranks = fen.split()[0].split('/')
            return '/'.join(r[::-1] for r in ranks[::-1]) + ' w - - 0 1'

        def corners(quad):
            tl, tr, br, bl = board_corners(quad)
            return [br, bl, tl, tr]

        cal = pc.calibrate([(render(flipped(START), scene(QUAD_A)), corners(QUAD_A))], START)
        self.check(MIDGAME, read_twice(render(flipped(MIDGAME), scene(QUAD_B)), corners(QUAD_B), cal))

    def test_blank_square_is_unsure(self):
        for square in ('e2', 'e4', 'd8'):
            img = render(START, scene(QUAD_B, occlusions=[{'box': panel_box(square), 'color': [128, 128, 128]}]))
            self.assertEqual(read_twice(img, board_corners(QUAD_B), self.cal)[square]['label'], 'unsure', square)

    def test_squares_outside_the_image_are_never_named(self):
        img = np.asarray(render(START, scene(QUAD_B)))
        cut = Image.fromarray(img[:, :420].copy())      # right part of the board is cut off
        res = read_twice(cut, board_corners(QUAD_B), self.cal)
        self.assertEqual(set(res), set(pc.SQUARES))
        h = pc._homography([(0, 0), (8, 0), (8, 8), (0, 8)], np.asarray(board_corners(QUAD_B)))
        outside = 0
        for s in pc.SQUARES:
            col, row = 'abcdefgh'.index(s[0]), 8 - int(s[1])
            xs = [(h @ np.array([col + a, row + b, 1.0])) for a in (0, 1) for b in (0, 1)]
            if max(p[0] / p[2] for p in xs) > 419:
                outside += 1
                self.assertEqual(res[s]['label'], 'unsure', s)
        self.assertGreater(outside, 8)

    def assert_refused_start(self, cal):
        self.assertEqual(cal['state'], 'no-reference', cal.get('problems'))
        self.assertEqual(cal['problems'][0][0], 'unusable-start', cal['problems'])
        res = read_twice(render(START, scene(QUAD_B)), board_corners(QUAD_B), cal)
        self.assertTrue(all(r['label'] == 'unsure' and r['reason'] == 'no-reference' for r in res.values()))

    def test_bad_inputs_are_refused(self):
        # since 2026-11-17 a refusal is an answer (refused start, 'unsure' everywhere), not an exception
        self.assert_refused_start(pc.calibrate([], START))
        img = render(START, scene(QUAD_A))
        mirrored = board_corners(QUAD_A)
        mirrored = [mirrored[1], mirrored[0], mirrored[3], mirrored[2]]
        res = pc.read(img, mirrored, self.cal, previous=pc.read(img, board_corners(QUAD_A), self.cal))
        self.assertTrue(all(r['label'] == 'unsure' and r['reason'] == 'bad-corners' for r in res.values()))
        cut = Image.fromarray(np.asarray(img)[:400].copy())
        self.assert_refused_start(pc.calibrate([(cut, board_corners(QUAD_A))], START))

    def test_malformed_input_is_unsure_not_an_exception(self):
        img = render(MIDGAME, scene(QUAD_B))
        arr = np.asarray(img, np.float32)
        c = board_corners(QUAD_B)
        prev = read_twice(img, c, self.cal)
        self.assertGreater(sum(r['label'] != 'unsure' for r in prev.values()), 20)     # the good picture is read
        nan = arr.copy()
        nan[300:320, 300:320] = np.nan
        cases = {'bad-image': [np.zeros((0, 0, 3), np.float32), arr.mean(axis=2),
                               np.concatenate([arr, np.full(arr.shape[:2] + (1,), 255, np.float32)], axis=2),
                               img.convert('RGBA'), img.convert('L'), nan, 'not a picture', None],
                 'bad-corners': [[[np.nan, 0]] * 4, c[:3], 'a1'],
                 'orientation-changed': [c[2:] + c[:2]]}
        for reason, items in cases.items():
            for item in items:
                image, corners = (img, item) if reason != 'bad-image' else (item, c)
                res = pc.read(image, corners, self.cal, previous=prev)
                self.assertEqual(set(res), set(pc.SQUARES))
                self.assertTrue(all(r['label'] == 'unsure' and r['reason'] == reason for r in res.values()),
                                (reason, res['a1']))
                self.assertEqual(pc.compare(res, pc.placement(MIDGAME))['reason'], 'reading-refused: ' + reason)
        # no start learned, or a start that could not be used: every answer unsure, compare cannot tell
        for cal in (None, {}, pc.calibrate([(np.full((768, 768, 3), 90, np.float32), board_corners(QUAD_A))], START),
                    pc.calibrate([(render(START, scene(QUAD_A)), board_corners(QUAD_A))], ''),
                    pc.calibrate([(render(START, scene(QUAD_A)), board_corners(QUAD_A))], '8/8/8/8/8/8/8/8 w - - 0 1'),
                    {k: v for k, v in self.cal.items() if k != 'state'}):
            res = pc.read(img, c, cal, previous=prev)
            self.assertTrue(all(r['label'] == 'unsure' and r['reason'] == 'no-reference' for r in res.values()))
            self.assertEqual(pc.compare(res, pc.placement(MIDGAME))['verdict'], 'cannot-tell')
        # the reader failing inside (here: a garbled previous reading) is unsure everywhere, not an exception
        res = pc.read(img, c, self.cal, previous={s: 3 for s in pc.SQUARES})
        self.assertTrue(all(r['label'] == 'unsure' and r['reason'] == 'read-failed' for r in res.values()))
        # compare before any reading, or with a malformed reading or belief
        truth = pc.placement(MIDGAME)
        for result, believed, reason in (({}, truth, 'malformed-result'), (None, truth, 'malformed-result'),
                                         ({'a1': {'label': 'R'}}, truth, 'malformed-result'),
                                         (dict(prev, a1={'label': 'empty'}), truth, 'malformed-result'),
                                         (prev, None, 'malformed-belief'), (prev, dict(truth, d4='empty'), 'malformed-belief'),
                                         (prev, dict(truth, z9='P'), 'malformed-belief')):
            out = pc.compare(result, believed)
            self.assertEqual((out['verdict'], out['reason']), ('cannot-tell', reason))
            if reason == 'malformed-result' or believed is None:
                self.assertTrue(all(v == 'cannot-tell' for v in out['squares'].values()))
        # a malformed belief entry is cannot-tell on its own square; an objection elsewhere is kept (review finding 5)
        out = pc.compare(prev, dict(truth, d4='empty'))
        self.assertEqual(out['squares']['d4'], 'cannot-tell')
        wrong = dict(truth, f3='B', c4='N')
        for bad in (dict(wrong, z9='P'), dict(wrong, d4='empty'), dict(wrong, E2='Q'), dict(wrong, d4=None)):
            out = pc.compare(prev, bad)
            self.assertEqual((out['verdict'], out['squares']['f3']), ('objection', 'objection'), bad)
        # a believed piece letter where the reader names the same piece but the entry is malformed is never consistent
        out = pc.compare(prev, dict(truth, f3=['N']))
        self.assertEqual((out['verdict'], out['reason'], out['squares']['f3']), ('cannot-tell', 'malformed-belief', 'cannot-tell'))

    # ---- v1 gates ---------------------------------------------------------------------------------------
    def test_poor_fit_with_clear_margin_is_unsure(self):
        # the same picture judged against a board whose learned contrast is 4x lower: every residual is 16x larger
        # relative to the contrast while every margin is unchanged, so only the fit gate can stop these squares
        cal = dict(self.cal, contrast=self.cal['contrast'] / 4)
        res = pc._settled(self.tiles, self.inside, cal, self.q)
        base = self.settled(self.tiles)
        cases = 0
        for s, r in res.items():
            if base[s]['label'] != 'unsure' and r['fit'] > 1.2 * pc.POLICY['FIT_MAX']:
                cases += 1
                self.assertEqual(r['label'], 'unsure', (s, r))
                self.assertEqual(r['reason'], 'poor-fit', (s, r))
        self.assertGreater(cases, 5)

    def test_over_bright_piece_needing_gain_above_ceiling_is_unsure(self):
        # each piece scaled so its best gain would be 3.15, 5 % above the 3.0 ceiling: the clipped match still fits
        # and wins clearly, so only the gain gate stops it
        base = self.settled(self.tiles)
        tiles = self.tiles.copy()
        squares = ('a1', 'b1', 'c1', 'a2', 'h7', 'g8', 'b8', 'f8')
        for s in squares:
            i = pc.SQUARES.index(s)
            m = tiles[i].mean(axis=(0, 1), keepdims=True)
            tiles[i] = m + (3.15 / base[s]['gain']) * (tiles[i] - m)
        res = self.settled(tiles)
        cases = 0
        for s in squares:
            r = res[s]
            if r['fit'] < pc.POLICY['FIT_MAX'] and r['marginSolid'] > 2.4 and (r['marginThin'] or 99) > 3.6:
                cases += 1
                self.assertEqual(r['label'], 'unsure', (s, r))
                self.assertEqual(r['reason'], 'gain-at-limit', (s, r))
        self.assertGreater(cases, 2)

    def test_colour_inverted_piece_is_not_named_as_itself(self):
        # a negative gain would turn a white piece into a black one: the 0.6 floor forbids it
        tiles = self.tiles.copy()
        squares = ('a1', 'b1', 'c1', 'a2', 'h7', 'g8')
        for s in squares:
            i = pc.SQUARES.index(s)
            m = tiles[i].mean(axis=(0, 1), keepdims=True)
            tiles[i] = m - (tiles[i] - m)
        res = self.settled(tiles)
        truth = pc.placement(START)
        for s in squares:
            self.assertNotEqual(res[s]['label'], truth[s], (s, res[s]))

    def test_margin_between_1_5_and_2_is_unsure(self):
        # g1 shows a blend of the white knight and the white bishop (both on dark squares); find blends whose
        # best-to-second ratio is between 1.5 and 2.0 and which nothing but the margin gate would stop
        g1, c1 = pc.SQUARES.index('g1'), pc.SQUARES.index('c1')
        cases = 0
        for a in np.linspace(0.5, 0.8, 31):
            tiles = self.tiles.copy()
            tiles[g1] = a * self.tiles[g1] + (1 - a) * self.tiles[c1]
            r = self.settled(tiles)['g1']
            if 1.55 < r['marginSolid'] < 1.95 and r['fit'] < 0.8 * pc.POLICY['FIT_MAX'] and (r['marginThin'] or 99) > 3.3:
                cases += 1
                self.assertEqual(r['label'], 'unsure', r)
                self.assertEqual(r['reason'], 'small-margin', r)
        self.assertGreater(cases, 0)

    # ---- v2 rule 1: start cleanliness ---------------------------------------------------------------
    def test_start_with_long_arrow_is_refused(self):
        img = with_arrow(render(START, scene(QUAD_A)), board_corners(QUAD_A), 'e2', 'e7')
        cal = pc.calibrate([(img, board_corners(QUAD_A))], START)
        self.assertEqual(cal['state'], 'no-reference')
        res = read_twice(render(START, scene(QUAD_B)), board_corners(QUAD_B), cal)
        self.assertTrue(all(r['label'] == 'unsure' and r['reason'] == 'no-reference' for r in res.values()))

    def test_start_with_short_arrow_on_pieces_only_is_refused(self):
        img = with_arrow(render(START, scene(QUAD_A)), board_corners(QUAD_A), 'b1', 'b2')
        self.assertEqual(pc.calibrate([(img, board_corners(QUAD_A))], START)['state'], 'no-reference')

    def test_start_with_arrow_over_empty_squares_only_is_refused(self):
        # no piece is touched, so the sibling check cannot see it: the empty squares must be flat
        img = with_arrow(render(START, scene(QUAD_A)), board_corners(QUAD_A), 'a4', 'h4')
        cal = pc.calibrate([(img, board_corners(QUAD_A))], START)
        self.assertEqual(cal['state'], 'no-reference')
        self.assertTrue(all(p[0] == 'empty-square-not-flat' for p in cal['problems']), cal['problems'])

    def test_start_with_glare_on_a_piece_is_refused(self):
        img = with_glare(render(START, scene(QUAD_A)), board_corners(QUAD_A), 'c2')
        self.assertEqual(pc.calibrate([(img, board_corners(QUAD_A))], START)['state'], 'no-reference')

    # ---- v2 rule 2: thin evidence and missing kinds ---------------------------------------------------
    def test_kind_learned_from_one_square_is_never_named(self):
        res = read_twice(render(MIDGAME, scene(QUAD_B)), board_corners(QUAD_B), self.cal)
        for s in ('e2', 'e1', 'e7', 'e8'):            # Q, K, q, k: one start square each
            self.assertEqual(res[s]['label'], 'unsure', (s, res[s]))
            self.assertEqual(res[s]['reason'], 'thin-evidence', (s, res[s]))

    def test_kind_missing_from_start_blocks_its_colour(self):
        start = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RN1QK1NR w KQkq - 0 1'      # no white bishops at the start
        cal = pc.calibrate([(render(start, scene(QUAD_A)), board_corners(QUAD_A))], start)
        self.assertEqual(cal['state'], 'ok', cal['problems'])
        res = read_twice(render(MIDGAME, scene(QUAD_B)), board_corners(QUAD_B), cal)
        truth = pc.placement(MIDGAME)
        for s, p in truth.items():
            if p.isupper():
                self.assertEqual(res[s]['label'], 'unsure', (s, res[s]))
            elif p not in THIN:
                self.assertEqual(res[s]['label'], p, (s, res[s]))

    # ---- v2 rule 3: mid-move confirmation --------------------------------------------------------------
    def test_piece_passing_over_a_square_is_not_named(self):
        # e2-e4 drawn half-way: the pawn sits exactly centred on e3, which is empty before and after the move
        corners = board_corners(QUAD_B)
        before = read_twice(render(START, scene(QUAD_B)), corners, self.cal)
        passing = 'rnbqkbnr/pppppppp/8/8/8/4P3/PPPP1PPP/RNBQKBNR w KQkq - 0 1'
        mid = pc.read(render(passing, scene(QUAD_B)), corners, self.cal, previous=before)
        self.assertEqual(mid['e3']['best'], 'P')
        self.assertEqual(mid['e3']['label'], 'unsure', mid['e3'])
        self.assertEqual(mid['e3']['reason'], 'unconfirmed', mid['e3'])
        self.assertEqual(mid['d2']['label'], 'P')                 # unchanged squares stay named
        # with no previous picture nothing can be confirmed
        self.assertTrue(all(r['label'] == 'unsure' for r in pc.read(render(START, scene(QUAD_B)), corners, self.cal).values()))

    # ---- v2 rule 4: picture quality -----------------------------------------------------------------------
    def test_heavily_blurred_picture_is_unsure_everywhere(self):
        img = render(MIDGAME, scene(QUAD_B, blur=4.0))
        res = read_twice(img, board_corners(QUAD_B), self.cal)
        self.assertTrue(all(r['label'] == 'unsure' for r in res.values()))
        self.assertEqual(res['a1']['reason'], 'poor-picture')

    def test_corners_off_by_several_pixels_are_unsure_everywhere(self):
        corners = (np.asarray(board_corners(QUAD_B)) + [6.0, 5.0]).tolist()
        res = read_twice(render(MIDGAME, scene(QUAD_B)), corners, self.cal)
        self.assertTrue(all(r['label'] == 'unsure' for r in res.values()))

    # ---- v2 rule 5: guard comparison ------------------------------------------------------------------
    def test_compare_consistent_objection_cannot_tell(self):
        res = read_twice(render(MIDGAME, scene(QUAD_B)), board_corners(QUAD_B), self.cal)
        truth = pc.placement(MIDGAME)
        ok = pc.compare(res, truth)
        self.assertNotEqual(ok['verdict'], 'objection')
        self.assertEqual(ok['squares']['f3'], 'consistent')
        self.assertEqual(ok['squares']['e2'], 'cannot-tell')      # queen: thin evidence
        # the overall verdict needs EVERY believed piece confirmed: kings and queens are unsure, so cannot tell
        self.assertEqual((ok['verdict'], ok['reason']), ('cannot-tell', 'unsure-squares'))
        # a square believed empty is never confirmed: the reader does not say "empty" ('no-piece-seen' is unsure)
        for s in pc.SQUARES:
            if s not in truth:
                self.assertEqual(res[s]['reason'], 'no-piece-seen', s)
                self.assertEqual(ok['squares'][s], 'cannot-tell', s)
        wrong = dict(truth)
        wrong['f3'], wrong['c4'] = 'B', 'N'                       # believed position has N and B swapped
        bad = pc.compare(res, wrong)
        self.assertEqual(bad['verdict'], 'objection')
        self.assertEqual(bad['squares']['f3'], 'objection')
        gone = dict(truth)
        del gone['f3']                                            # believed empty, but a knight is seen there
        self.assertEqual(pc.compare(res, gone)['squares']['f3'], 'objection')
        refused = pc.calibrate([(with_arrow(render(START, scene(QUAD_A)), board_corners(QUAD_A), 'e2', 'e7'),
                                 board_corners(QUAD_A))], START)
        none = pc.compare(pc.read(render(MIDGAME, scene(QUAD_B)), board_corners(QUAD_B), refused), truth)
        self.assertEqual(none['verdict'], 'cannot-tell')

    def test_compare_partial_position_is_never_consistent(self):
        res = read_twice(render(MIDGAME, scene(QUAD_B)), board_corners(QUAD_B), self.cal)
        truth = pc.placement(MIDGAME)
        # the reviewer's case: belief = only the squares the reader names (kings and queens left out)
        named = {s: p for s, p in truth.items() if res[s]['label'] != 'unsure'}
        self.assertTrue(all(res[s]['label'] == p for s, p in named.items()))      # every believed piece is named
        out = pc.compare(res, named)
        self.assertEqual((out['verdict'], out['reason']), ('cannot-tell', 'partial-belief'))
        # a reader that could name every piece (kings and queens relabelled as confirmed), so that "consistent" is
        # reachable: the full belief is consistent, any belief with a piece left out is not
        full = {s: (dict(r, label=truth[s], reason='ok') if s in truth else r) for s, r in res.items()}
        self.assertEqual(pc.compare(full, truth)['verdict'], 'consistent')
        for s in truth:
            part = {k: v for k, v in truth.items() if k != s}
            unseen = dict(full, **{s: dict(full[s], label='unsure', reason='small-margin')})
            for result in (full, unseen):
                out = pc.compare(result, part)
                self.assertNotEqual(out['verdict'], 'consistent', (s, out['reason']))
            self.assertEqual(pc.compare(unseen, part)['reason'],
                             'partial-belief' if truth[s] in 'Kk' else 'believed-empty-square-unclear', s)
        self.assertEqual(pc.compare(full, {})['verdict'], 'objection')         # pieces seen where none believed
        no_kings = {s: (dict(r, label='unsure', reason='no-piece-seen') if s in truth else r) for s, r in full.items()}
        self.assertEqual(pc.compare(no_kings, {})['reason'], 'partial-belief')         # no kings: not a position

    def test_read_tiles_refuses_a_refused_start(self):
        # evaluate() and _settled() call read_tiles directly; a refused start still carries its (dirty) shapes, which
        # must never be used
        refused = pc.calibrate([(with_arrow(render(START, scene(QUAD_A)), board_corners(QUAD_A), 'e2', 'e7'),
                                 board_corners(QUAD_A))], START)
        self.assertEqual(refused['state'], 'no-reference')
        self.assertGreater(len(refused['kinds']), 0)
        res = pc._settled(self.tiles, self.inside, refused, self.q)
        self.assertTrue(all(r['label'] == 'unsure' and r['reason'] == 'no-reference' for r in res.values()))

    # ---- added 2026-11-17: tests for the rules the review's mutants showed untested ---------------------------
    def test_thin_runner_up_needs_margin_3(self):
        # f1 shows a blend of the bishop (well evidenced, 2 start squares) and the queen (1 start square); where the
        # well-evidenced margin is clear (>= 2) but the queen fits less than 3x worse the square must stay unsure
        # with reason thin-runner-up, also when the queen fits less than 2x worse (the reason names the thin kind)
        between, close = 0, 0
        for tgt, src in (('f1', 'd1'), ('f8', 'd8')):
            it, isrc = pc.SQUARES.index(tgt), pc.SQUARES.index(src)
            for a in np.linspace(0.5, 0.7, 41):
                tiles = self.tiles.copy()
                tiles[it] = a * self.tiles[it] + (1 - a) * self.tiles[isrc]
                r = self.settled(tiles)[tgt]
                if r['best'] != tgt and r['best'] != pc.placement(START)[tgt]:
                    continue
                if not (r['fit'] < 0.8 * pc.POLICY['FIT_MAX'] and 0.65 < r['gain'] < 2.8 and r['marginSolid'] > 2.05):
                    continue
                if 2.05 < r['marginThin'] < 2.95:
                    between += 1
                elif r['marginThin'] < 1.95:
                    close += 1
                else:
                    continue
                self.assertEqual(r['label'], 'unsure', r)
                self.assertEqual(r['reason'], 'thin-runner-up', r)
        self.assertGreater(between, 2)
        self.assertGreater(close, 2)

    def test_corners_off_by_two_board_pixels_are_unsure_everywhere(self):
        # corners 4 camera pixels off: the pieces still match inside the 2 px shift, so without the picture-quality
        # gate 28 squares would be named; the boundaries sit 2.3 board pixels off, beyond MISALIGN_MAX
        corners = (np.asarray(board_corners(QUAD_B)) + [4.0, 0.0]).tolist()
        img = render(MIDGAME, scene(QUAD_B))
        tiles, inside, q = pc._square_tiles_q(img, corners, self.cal['lumContrast'])
        self.assertTrue(pc.POLICY['MISALIGN_MAX'] < q['misalign'] < 1.5 * pc.POLICY['MISALIGN_MAX'], q)
        self.assertLess(q['blur'], pc.POLICY['BLUR_MAX'])
        self.assertGreater(sum(r['label'] != 'unsure' for r in pc._settled(tiles, inside, self.cal, None).values()), 20)
        res = read_twice(img, corners, self.cal)
        self.assertTrue(all(r['label'] == 'unsure' and r['reason'] == 'poor-picture' for r in res.values()))

    def test_start_with_highlight_under_a_knight_is_refused(self):
        # a last-move highlight under the g1 knight would be learned into the knight shape; the knight has only one
        # sibling (b1), so the two-square sibling limits must catch it
        img = with_highlight(render(START, scene(QUAD_A)), board_corners(QUAD_A), 'g1')
        cal = pc.calibrate([(img, board_corners(QUAD_A))], START)
        self.assertEqual(cal['state'], 'no-reference')
        self.assertTrue(all(p[0] == 'piece-disagrees-with-siblings' for p in cal['problems']), cal['problems'])

    def test_start_with_faint_move_dot_is_refused(self):
        # a faint legal-move hint dot on the empty e3 square: no piece is touched, the empty-square check must see it
        img = with_move_dot(render(START, scene(QUAD_A)), board_corners(QUAD_A), 'e3')
        cal = pc.calibrate([(img, board_corners(QUAD_A))], START)
        self.assertEqual(cal['state'], 'no-reference')
        self.assertEqual([p[:2] for p in cal['problems']], [('empty-square-not-flat', 'e3')])

    def test_noisy_start_with_arrow_on_two_pawns_is_refused(self):
        # a noisy camera picture (pixel noise sd 10): the clean start is accepted, but a short arrow over the d2 and
        # e2 pawns must still be refused; the pawn sibling limit grows with the picture noise, so a looser noise
        # factor would accept this start
        clean = pc.calibrate([(with_noise(render(START, scene(QUAD_A)), 10), board_corners(QUAD_A))], START)
        self.assertEqual(clean['state'], 'ok', clean['problems'])
        self.assertGreater(clean['startScores']['sigma'], 3.0)
        img = with_noise(with_arrow(render(START, scene(QUAD_A)), board_corners(QUAD_A), 'd2', 'e2', width=18), 10)
        cal = pc.calibrate([(img, board_corners(QUAD_A))], START)
        self.assertEqual(cal['state'], 'no-reference')
        self.assertEqual({p[1] for p in cal['problems']}, {'d2', 'e2'}, cal['problems'])

    @unittest.skipUnless((SMOKE / 'truth/games.json').exists(), 'scene data not present')
    def test_clean_scene_pictures(self):
        import json
        game = [g for g in json.loads((SMOKE / 'truth/games.json').read_text())['games'] if g['id'] == 'smoke-g01'][0]
        frames = game['frames']
        cal = pc.calibrate([(Image.open(SMOKE / frames[0]['file']), frames[0]['corners'])], game['startFen'])
        self.assertEqual(cal['state'], 'ok', cal['problems'])
        for f in (frames[1], frames[-1]):
            res = read_twice(Image.open(SMOKE / f['file']), f['corners'], cal)
            self.check(f['fen'], {s: (r if r['reason'] != 'poor-picture' else r) for s, r in res.items()})


if __name__ == '__main__':
    result = unittest.main(exit=False, verbosity=1).result
    print(f'{result.testsRun - len(result.failures) - len(result.errors)} of {result.testsRun} tests passed'
          f' ({len(result.skipped)} skipped)')
    sys.exit(0 if result.wasSuccessful() else 1)
