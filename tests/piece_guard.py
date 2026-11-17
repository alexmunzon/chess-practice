#!/usr/bin/env python3
"""Withhold-only piece guard: contract tests on synthetic rendered boards (not camera evidence).

The guard has exactly two outcomes, 'withhold' and 'no objection', and 'no objection' is no information.
Run: python3 -B tests/piece_guard.py
"""
import copy
import pickle
from pathlib import Path
import sys
import unittest
from unittest import mock

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/recognition'))
sys.path.insert(0, str(ROOT / 'scripts/simulation'))
import piece_classifier_v2 as pc
import piece_guard as pg
from render import render

START = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
MIDGAME = 'r1b1k1nr/ppppqppp/2n5/2b1p3/2B1P3/5N2/PPPPQPPP/RNB1K2R w KQkq - 6 5'
QUAD_A = [[70, 66], [700, 60], [698, 702], [60, 712]]
QUAD_B = [[80, 50], [690, 76], [705, 690], [52, 700]]


def board_corners(quad):
    h = pc._homography([(0, 0), (640, 0), (640, 640), (0, 640)], quad)
    pts = []
    for u, v in [(64, 64), (576, 64), (576, 576), (64, 576)]:
        p = h @ np.array([u, v, 1.0])
        pts.append([p[0] / p[2] - 0.5, p[1] / p[2] - 0.5])
    return pts


def scene(quad, **extra):
    return {'quad': quad, 'brightness': 1.0, 'blur': 0.3, **extra}


CA, CB = board_corners(QUAD_A), board_corners(QUAD_B)


def with_arrow(image, corners, a, b):
    h = pc._homography([(0, 0), (8, 0), (8, 8), (0, 8)], np.asarray(corners))

    def centre(sq):
        p = h @ np.array(['abcdefgh'.index(sq[0]) + 0.5, 8 - int(sq[1]) + 0.5, 1.0])
        return p[0] / p[2], p[1] / p[2]
    base = image.convert('RGBA')
    layer = Image.new('RGBA', base.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).line([centre(a), centre(b)], fill=(255, 170, 0, 170), width=14)
    return Image.alpha_composite(base, layer).convert('RGB')


def fen_of(pos):
    rows = []
    for rank in range(8, 0, -1):
        row, gap = '', 0
        for f in 'abcdefgh':
            p = pos.get(f + str(rank))
            if p:
                row += (str(gap) if gap else '') + p
                gap = 0
            else:
                gap += 1
        rows.append(row + (str(gap) if gap else ''))
    return '/'.join(rows) + ' w - - 0 1'


def moved(pos, *pairs, drop=(), put=()):
    p = dict(pos)
    for a, b in pairs:
        p[b] = p.pop(a)
    for s in drop:
        p.pop(s, None)
    for s, q in put:
        p[s] = q
    return p


def settled(guard, image, corners, believed, disturbed=()):
    """A settled picture seen in two consecutive frames; the guard's answer on the second."""
    guard.check(image, corners, believed, disturbed)
    return guard.check(image, corners, believed, disturbed)


def review(guard, image, corners, position):
    """A person reviewed `position`: re-baseline on a settled picture of it (seen once before, because the reader
    confirms nothing on the first picture of a new guard and a re-baseline needs pieces named)."""
    guard.check(image, corners, position)
    return guard.rebaseline_after_human_review(image, corners, position)


_PICS = {}


def picture_of(pos):
    if fen_of(pos) not in _PICS:
        _PICS[fen_of(pos)] = render(fen_of(pos), scene(QUAD_B))
    return _PICS[fen_of(pos)]


class Guard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.start = [(render(START, scene(QUAD_A)), CA)]
        cls.mid = render(MIDGAME, scene(QUAD_B))
        cls.truth = pc.placement(MIDGAME)

    def guard(self, **kw):
        return pg.PieceGuard(self.start, START, **kw)

    def assert_no_confirmation(self, out):
        """The outcome exposes only must_withhold() and reasons; nothing a caller could read as a confirmation."""
        self.assertIsInstance(out, pg.GuardOutcome)
        self.assertIs(type(out.must_withhold()), bool)
        self.assertTrue(out == (pg.WITHHOLD if out.must_withhold() else pg.NO_OBJECTION))
        self.assertFalse(any('consistent' in r or 'confirm' in r for r in out.reasons), out.reasons)
        for name in ('outcome', 'squares', 'verdict', 'consistent', 'confirmed', 'result', 'reading'):
            with self.assertRaises(TypeError):
                getattr(out, name, None)
        with self.assertRaises(TypeError):
            bool(out)
        if not out.must_withhold():
            self.assertEqual(out.reasons, ())
        else:
            self.assertGreater(len(out.reasons), 0)

    # ---- the outcome type --------------------------------------------------------------------------------------
    def test_exactly_two_outcomes(self):
        self.assertEqual(pg.OUTCOMES, ('withhold', 'no objection'))
        for bad in ('confirmed', 'consistent', 'ok', '', None):
            with self.assertRaises(ValueError):
                pg.GuardOutcome(bad)
        self.assertIn('no information', pg.__doc__)
        self.assertIn('never restore or grant advice', pg.GuardOutcome.__doc__)

    def test_comparison_is_safe(self):
        # the review's trap: `out == WITHHOLD` must be True for a real withhold (it was always False)
        wrong = dict(self.truth, f3='B', c4='N')
        w = settled(self.guard(), self.mid, CB, wrong)
        n = settled(self.guard(), self.mid, CB, self.truth)
        self.assertTrue(w == pg.WITHHOLD and pg.WITHHOLD == w and w != pg.NO_OBJECTION and w in (pg.WITHHOLD,))
        self.assertTrue(n == pg.NO_OBJECTION and n != pg.WITHHOLD and not (n == pg.WITHHOLD))
        # anything else raises instead of quietly answering False
        for other in ('withold', 'Withhold', 'confirmed', None, 0, True, w, ('withhold',), b'withhold'):
            for op in (lambda a, b: a == b, lambda a, b: a != b, lambda a, b: b == a):
                with self.assertRaises(TypeError):
                    op(w, other)
        for op in (lambda: w < n, lambda: sorted([w, n]), lambda: hash(w), lambda: {w}, lambda: bool(n),
                   lambda: not w, lambda: any([n]), lambda: str(w), lambda: f'{w}', lambda: '%s' % w,
                   lambda: w.outcome, lambda: w.outcome == 'withold', lambda: getattr(w, 'verdict', pg.WITHHOLD),
                   lambda: pickle.dumps(n), lambda: copy.copy(n), lambda: copy.deepcopy(n), lambda: w == None):
            with self.assertRaises(TypeError):
                op()
        self.assertNotIn(repr(w), pg.OUTCOMES)
        with self.assertRaises(AttributeError):
            n._genuine = False

    def test_must_withhold_is_the_one_pattern(self):
        wrong = dict(self.truth, f3='B', c4='N')
        self.assertIs(settled(self.guard(), self.mid, CB, wrong).must_withhold(), True)
        self.assertIs(settled(self.guard(), self.mid, CB, self.truth).must_withhold(), False)
        # a no-objection outcome a caller builds by hand is not genuine: it must withhold, and == agrees
        fake = pg.GuardOutcome(pg.NO_OBJECTION)
        self.assertIs(fake.must_withhold(), True)
        self.assertTrue(fake == pg.WITHHOLD and fake != pg.NO_OBJECTION)
        self.assertIs(pg.GuardOutcome(pg.WITHHOLD, ('x',)).must_withhold(), True)
        self.assertTrue(pg.__doc__.lstrip().startswith('Withhold-only guard'))
        self.assertIn('if out.must_withhold():', pg.__doc__.split('\n\n')[1])

    def test_every_withhold_has_a_reason(self):
        with self.assertRaises(ValueError):
            pg.GuardOutcome(pg.WITHHOLD)
        with self.assertRaises(ValueError):
            pg.GuardOutcome(pg.WITHHOLD, ('',))
        with self.assertRaises(ValueError):
            pg.GuardOutcome(pg.NO_OBJECTION, ('x',))
        with self.assertRaises(ValueError):
            pg.GuardOutcome(pg.WITHHOLD, ['objection: f3'])
        # a faked reader that says objection without naming a square still gives a reason
        g = self.guard()
        g.check(self.mid, CB, self.truth)
        fake = {'verdict': 'objection', 'reason': 'objection', 'squares': {s: 'cannot-tell' for s in pc.SQUARES}}
        with mock.patch.object(pg.reader, 'compare', return_value=fake):
            out = g.check(self.mid, CB, self.truth)
        self.assertEqual((out.must_withhold(), out.reasons), (True, ('objection',)))

    # ---- withholds ---------------------------------------------------------------------------------------------
    def test_objection_withholds(self):
        wrong = dict(self.truth)
        wrong['f3'], wrong['c4'] = 'B', 'N'                       # believed position has N and B swapped
        for strict in (True, False):
            out = settled(self.guard(withhold_on_unsure_disturbed=strict), self.mid, CB, wrong)
            self.assertEqual(out.must_withhold(), True)
            self.assertIn('objection: f3', out.reasons)
            self.assert_no_confirmation(out)
        # the true position on the same picture: no objection
        out = settled(self.guard(), self.mid, CB, self.truth)
        self.assertEqual(out.must_withhold(), False)
        self.assert_no_confirmation(out)

    def test_reader_exception_withholds(self):
        g = self.guard()
        g.check(self.mid, CB, self.truth)
        with mock.patch.object(pg.reader, 'read', side_effect=RuntimeError('boom')):
            out = g.check(self.mid, CB, self.truth)
        self.assertEqual((out.must_withhold(), out.reasons), (True, ('reader-error: RuntimeError',)))
        with mock.patch.object(pg.reader, 'compare', side_effect=KeyError('a1')):
            out = g.check(self.mid, CB, self.truth)
        self.assertEqual((out.must_withhold(), out.reasons), (True, ('guard-error: KeyError',)))
        with mock.patch.object(pg.reader, 'compare', return_value={'verdict': 'confirmed', 'squares': {}}):
            self.assertEqual(g.check(self.mid, CB, self.truth).must_withhold(), True)
        with mock.patch.object(pg.reader, 'calibrate', side_effect=MemoryError()):
            out = self.guard().check(self.mid, CB, self.truth)
        self.assertEqual((out.must_withhold(), out.reasons), (True, ('start-refused: MemoryError',)))
        # pictures and corners the reader refuses (it answers instead of raising) also withhold
        arr = np.asarray(self.mid, np.float32)
        for image, corners in ((arr.mean(axis=2), CB), (self.mid.convert('RGBA'), CB), (None, CB),
                               (self.mid, [[np.nan, 0]] * 4), (self.mid, CB[2:] + CB[:2])):
            out = settled(self.guard(), image, corners, self.truth)
            self.assertEqual(out.must_withhold(), True)
            self.assertTrue(out.reasons[0].startswith('reading-refused'), out.reasons)

    def test_no_start_withholds(self):
        out = pg.PieceGuard(None, START).check(self.mid, CB, self.truth)
        self.assertEqual((out.must_withhold(), out.reasons), (True, ('no-start',)))
        refused = [(with_arrow(render(START, scene(QUAD_A)), CA, 'e2', 'e7'), CA)]
        unusable = [(np.full((768, 768, 3), 90, np.float32), CA)]
        for start in (refused, unusable, []):
            for strict in (True, False):
                out = settled(pg.PieceGuard(start, START, withhold_on_unsure_disturbed=strict), self.mid, CB,
                              self.truth)
                self.assertEqual((out.must_withhold(), out.reasons), (True, ('start-refused',)))

    def test_partial_or_malformed_belief_withholds(self):
        named_only = {s: p for s, p in self.truth.items() if p not in 'KQkq'}
        kings = 'impossible-position: not one king of each colour'
        for believed, reason in ((named_only, kings), (dict(self.truth, d4='K'), kings),
                                 (dict(self.truth, d4='empty'), 'malformed-belief'), (None, 'malformed-belief'),
                                 (dict(self.truth, z9='P'), 'malformed-belief'), (dict(self.truth, E2='Q'), 'malformed-belief'),
                                 (list(self.truth.items()), 'malformed-belief'), (MIDGAME, 'malformed-belief'),
                                 ({}, kings)):
            for strict in (True, False):
                out = settled(self.guard(withhold_on_unsure_disturbed=strict), self.mid, CB, believed)
                self.assertEqual((out.must_withhold(), out.reasons), (True, (reason,)))
        out = settled(self.guard(), self.mid, CB, self.truth, disturbed=('z9',))
        self.assertEqual((out.must_withhold(), out.reasons), (True, ('malformed-disturbed-squares',)))

    def test_impossible_position_withholds(self):
        # every one of these believed positions is impossible in chess, yet looks fine to the reader on the squares
        # it can check (the extra pawn stands where the reader sees nothing)
        free = [s for s in pc.SQUARES if s not in self.truth]
        rank8 = dict(self.truth, **{[s for s in free if s[1] == '8'][0]: 'P'})
        rank1 = dict(self.truth, **{[s for s in free if s[1] == '1'][0]: 'p'})
        nine = dict(self.truth, **{[s for s in free if s[1] in '3456'][0]: 'P'})
        many = dict(self.truth)
        for s in [s for s in free if s[1] in '3456'][:9]:
            many[s] = 'N'                                                   # 15 + 9 = 24 white pieces
        for believed, why in ((rank8, 'pawn on rank 1 or 8'), (rank1, 'pawn on rank 1 or 8'),
                              (nine, 'too many white pieces or pawns'), (many, 'too many white pieces or pawns')):
            for strict in (True, False):
                out = settled(self.guard(withhold_on_unsure_disturbed=strict), self.mid, CB, believed)
                self.assertEqual((out.must_withhold(), out.reasons), (True, ('impossible-position: ' + why,)))

    def test_caller_misuse_withholds(self):
        # the review's misuse cases: each must withhold
        class Lying(dict):                                    # get() and items() disagree with the dict's contents
            def get(self, k, d=None):
                return pc.placement(MIDGAME).get(k, d)

            def items(self):
                return pc.placement(MIDGAME).items()
        lying = Lying({s: p for s, p in self.truth.items() if p in 'Kk'})
        out = settled(self.guard(withhold_on_unsure_disturbed=False), self.mid, CB, lying)
        self.assertEqual(out.must_withhold(), True)
        self.assertTrue(all(r.startswith('objection: ') for r in out.reasons), out.reasons)

        class Falsy:                                          # falsy, but yields a square when iterated
            def __iter__(self):
                return iter(['e2'])

            def __bool__(self):
                return False
        for disturbed in (Falsy(), (s for s in ['e2']), iter(['e2']), {'e2': 1}, 5, 0, np.array(['e2']), 'E2',
                          ['e2', None], b'e2'):
            out = settled(self.guard(), self.mid, CB, self.truth, disturbed)
            self.assertEqual((out.must_withhold(), out.reasons), (True, ('malformed-disturbed-squares',)), disturbed)
        # one generator reused for two calls: the second call must not see an empty list
        g = self.guard()
        gen = (s for s in ['e2'])
        self.assertEqual(g.check(self.mid, CB, self.truth, gen), pg.WITHHOLD)
        self.assertEqual(g.check(self.mid, CB, self.truth, gen), pg.WITHHOLD)
        # the strict setting cannot be changed after creation
        g = self.guard()
        with self.assertRaises(AttributeError):
            g.withhold_on_unsure_disturbed = False
        self.assertEqual(settled(g, self.mid, CB, self.truth, ('e2',)), pg.WITHHOLD)
        for odd in ('False', 0, None, np.False_, []):                     # only False itself is lenient
            self.assertTrue(self.guard(withhold_on_unsure_disturbed=odd).withhold_on_unsure_disturbed, odd)
        # a compare() answer with missing or odd fields
        g = self.guard()
        g.check(self.mid, CB, self.truth)
        allc = {s: 'consistent' for s in pc.SQUARES}
        for fake in ({'verdict': 'consistent', 'squares': allc}, {'verdict': 'consistent', 'squares': allc, 'reason': None},
                     {'verdict': 'consistent', 'reason': ''}, {'verdict': 'OBJECTION', 'squares': allc, 'reason': ''},
                     {'verdict': 'consistent', 'squares': dict(allc, a1='yes'), 'reason': ''}, None, 'consistent'):
            with mock.patch.object(pg.reader, 'compare', return_value=fake):
                out = g.check(self.mid, CB, self.truth)
            self.assertEqual((out.must_withhold(), out.reasons), (True, ('malformed-compare',)), fake)
        # benign variants of the true position stay usable
        import collections
        for believed in (collections.OrderedDict(self.truth), {s: np.str_(p) for s, p in self.truth.items()}):
            self.assertEqual(settled(self.guard(), self.mid, CB, believed), pg.NO_OBJECTION)

    def test_reading_after_a_reader_error_is_not_confirmed_by_an_older_picture(self):
        # picture X read, the reader fails on the next picture, then X again: nothing may be confirmed against the
        # reading from before the failure, so the strict guard withholds on the disturbed f3 knight
        for exc in (RuntimeError('boom'), KeyboardInterrupt()):
            g = self.guard()
            g.check(self.mid, CB, self.truth)
            self.assertEqual(g.check(self.mid, CB, self.truth, ('f3',)), pg.NO_OBJECTION)      # confirmed: control
            with mock.patch.object(pg.reader, 'read', side_effect=exc):
                try:
                    g.check(self.mid, CB, self.truth)
                except KeyboardInterrupt:
                    pass
            out = g.check(self.mid, CB, self.truth, ('f3',))
            self.assertEqual((out.must_withhold(), out.reasons), (True, ('cannot-tell on disturbed square: f3',)))

    def test_malformed_reading_withholds(self):
        # a reader returning a malformed reading: compare says cannot-tell 'malformed-result'; the guard must withhold
        # even with no disturbed squares
        for fake in ({}, None, {'a1': {'label': 'R'}}, {s: {'label': 'empty'} for s in pc.SQUARES}):
            for strict in (True, False):
                g = self.guard(withhold_on_unsure_disturbed=strict)
                with mock.patch.object(pg.reader, 'read', return_value=fake):
                    out = g.check(self.mid, CB, self.truth)
                self.assertEqual((out.must_withhold(), out.reasons), (True, ('malformed-result',)), fake)

    def test_reader_saying_it_cannot_judge_withholds(self):
        # defence in depth: the guard checks the believed position itself first, so the real compare() never reaches
        # these answers through the guard; a reader (or a future compare) that says it cannot judge must still withhold
        g = self.guard(withhold_on_unsure_disturbed=False)
        g.check(self.mid, CB, self.truth)
        none = {s: 'cannot-tell' for s in pc.SQUARES}
        for why in ('partial-belief', 'malformed-belief', 'malformed-result', 'reading-refused: bad-image'):
            with mock.patch.object(pg.reader, 'compare', return_value={'verdict': 'cannot-tell', 'reason': why,
                                                                        'squares': none}):
                out = g.check(self.mid, CB, self.truth)
            self.assertEqual((out.must_withhold(), out.reasons), (True, (why,)))

    def after_move(self, picture_pos, before, after, strict=True):
        """Fresh guard re-baselined on `before` (shown on its own picture), then a settled picture of picture_pos
        checked twice as the move before -> after; returns the second answer."""
        g = self.guard(withhold_on_unsure_disturbed=strict)
        self.assertIs(review(g, picture_of(before), CB, before).must_withhold(), False)
        img = render(fen_of(picture_pos), scene(QUAD_B))
        g.check_after_move(img, CB, before, after)
        return g.check_after_move(img, CB, before, after)

    def test_check_after_move_derives_the_changed_squares(self):
        before = moved(self.truth, ('f3', 'g1'))                            # MIDGAME arose from g1-f3
        for strict in (True, False):
            # honest knight move: vacated g1 is not asked for "empty" (the reader never says it)
            self.assertIs(self.after_move(self.truth, before, self.truth, strict).must_withhold(), False)
            # believed queen move e2-e3 that never happened, and an honest one: queens are never checkable
            qm = moved(self.truth, ('e2', 'e3'))
            for picture in (self.truth, qm):
                out = self.after_move(picture, self.truth, qm, strict)
                self.assertEqual((out.must_withhold(), out.reasons), (True, ('king-or-queen-moved: never checkable',)))
            # a different piece on the arrival square, or the knight elsewhere: objection
            out = self.after_move(moved(self.truth, put=[('f3', 'B')]), before, self.truth, strict)
            self.assertIn('objection: f3', out.reasons)
            out = self.after_move(moved(before, ('g1', 'h3')), before, self.truth, strict)
            self.assertIs(out.must_withhold(), True)

    def test_every_accepted_shape_passes_on_a_matching_picture(self):
        t = self.truth
        ep0 = {'e1': 'K', 'e8': 'k', 'e5': 'P', 'd5': 'p', 'a2': 'P', 'h7': 'p', 'b1': 'N', 'g8': 'n', 'c1': 'B',
               'f8': 'b', 'a1': 'R', 'h8': 'r'}
        bep0 = {'e1': 'K', 'e8': 'k', 'd4': 'p', 'e4': 'P', 'a2': 'P', 'h7': 'p', 'b1': 'N', 'g8': 'n', 'c1': 'B',
                'f8': 'b', 'a1': 'R', 'h8': 'r'}
        pr0 = moved(ep0, ('a2', 'a7'), drop=['h7'])
        pr0c = moved(pr0, ('h8', 'b8'))
        bp = moved(t, ('h7', 'b3'))                                       # a black pawn white can take on b3
        shapes = {'knight f3-g5': (t, moved(t, ('f3', 'g5'))),
                  'knight takes f3xe5': (t, moved(t, ('f3', 'e5'))),
                  'bishop c4-b5': (t, moved(t, ('c4', 'b5'))),
                  'bishop takes c4xf7': (t, moved(t, ('c4', 'f7'))),
                  'rook h1-g1': (t, moved(t, ('h1', 'g1'))),
                  'pawn one a2-a3': (t, moved(t, ('a2', 'a3'))),
                  'pawn two a2-a4': (t, moved(t, ('a2', 'a4'))),
                  'black pawn one d7-d6': (t, moved(t, ('d7', 'd6'))),
                  'black pawn two h7-h5': (t, moved(t, ('h7', 'h5'))),
                  'pawn takes a2xb3': (bp, moved(bp, ('a2', 'b3'))),
                  'en passant white e5xd6': (ep0, moved(ep0, ('e5', 'd6'), drop=['d5'])),
                  'en passant black d4xe3': (bep0, moved(bep0, ('d4', 'e3'), drop=['e4'])),
                  'promotion a7-a8=N': (pr0, moved(pr0, ('a7', 'a8'), put=[('a8', 'N')])),
                  'promotion a7-a8=R': (pr0, moved(pr0, ('a7', 'a8'), put=[('a8', 'R')])),
                  'promotion a7xb8=B': (pr0c, moved(pr0c, ('a7', 'b8'), put=[('b8', 'B')]))}
        for name, (before, after) in shapes.items():
            self.assertEqual(pg._move_arrival(pg._believed(before), pg._believed(after)),
                             [s for s in pc.SQUARES if before.get(s) != after.get(s) and s in after][0], name)
            out = self.after_move(after, before, after)
            self.assertIs(out.must_withhold(), False, (name, out.reasons))

    def test_every_other_change_withholds(self):
        t = self.truth
        before = moved(t, ('f3', 'g1'))
        ep0 = {'e1': 'K', 'e8': 'k', 'e5': 'P', 'd5': 'p', 'a2': 'P', 'h7': 'p', 'b1': 'N', 'g8': 'n', 'c1': 'B',
               'f8': 'b', 'a1': 'R', 'h8': 'r'}
        pr0 = moved(ep0, ('a2', 'a7'), drop=['h7'])
        rejected = {
            'identical': (t, t, 'no-move'),
            'knight move and the white queen vanishes': (before, moved(t, drop=['e2']), 'king-or-queen-moved'),
            'knight move and the black queen vanishes': (before, moved(t, drop=['e7']), 'king-or-queen-moved'),
            'pawn move and a rook vanishes': (t, moved(t, ('a2', 'a3'), drop=['a8']), 'not-a-single-move'),
            'in-place kind change N->B on f3': (t, moved(t, put=[('f3', 'B')]), 'not-a-single-move'),
            'in-place colour change N->n on f3': (moved(t, drop=['g8']), moved(t, drop=['g8'], put=[('f3', 'n')]),
                                                  'not-a-single-move'),
            'knight teleport g1-h6': (before, moved(before, ('g1', 'h6')), 'not-a-single-move'),
            'bishop off its diagonal c4-c5': (moved(t, drop=['c5']), moved(t, ('c4', 'c5')), 'not-a-single-move'),
            'rook diagonal h1-g2': (moved(t, drop=['g2']), moved(moved(t, drop=['g2']), ('h1', 'g2')), 'not-a-single-move'),
            'knight straight three f3-f6': (t, moved(t, ('f3', 'f6')), 'not-a-single-move'),
            'bishop knight-like c4xe5': (t, moved(t, ('c4', 'e5')), 'not-a-single-move'),
            'two movers': (t, moved(t, ('f3', 'g5'), ('c4', 'b5')), 'not-a-single-move'),
            'two pieces swapped': (t, moved(t, put=[('f3', 'B'), ('c4', 'N')]), 'not-a-single-move'),
            'castling': (t, moved(t, ('e1', 'g1'), ('h1', 'f1')), 'king-or-queen-moved'),
            'king one step': (t, moved(t, ('e1', 'f1')), 'king-or-queen-moved'),
            'piece appears from nowhere': (moved(t, drop=['g8']), t, 'not-a-single-move'),
            'piece vanishes': (t, moved(t, drop=['a2']), 'not-a-single-move'),
            'pawn backwards a3-a2': (moved(t, ('a2', 'a3')), t, 'not-a-single-move'),
            'pawn two from a3': (moved(t, ('a2', 'a3')), moved(t, ('a2', 'a5')), 'not-a-single-move'),
            'pawn straight onto a piece d7xd6?': (moved(t, put=[('d6', 'N')], drop=['b1']),
                                                  moved(t, ('d7', 'd6'), put=[('b1', 'N')], drop=['b1']) if False else
                                                  moved(moved(t, put=[('d6', 'N')], drop=['b1']), ('d7', 'd6')), 'not-a-single-move'),
            'pawn diagonal to an empty square': (t, moved(t, ('a2', 'b3')), 'not-a-single-move'),
            'capture of an own piece': (t, moved(t, ('f3', 'd2')), 'not-a-single-move'),
            'promotion to a queen': (pr0, moved(pr0, ('a7', 'a8'), put=[('a8', 'Q')]), 'king-or-queen-moved'),
            'promotion from the 6th rank': (moved(pr0, ('a7', 'a6')), moved(pr0, ('a7', 'a8'), put=[('a8', 'N')]),
                                            'not-a-single-move'),
            'pawn turns into a knight off the last rank': (t, moved(t, ('a2', 'a3'), put=[('a3', 'N')]), 'not-a-single-move'),
            'en passant on the wrong rank': (moved(ep0, ('e5', 'e4'), ('d5', 'd4')),
                                             moved(ep0, ('e5', 'd5'), drop=['d5']) if False else
                                             moved(moved(ep0, ('e5', 'e4'), ('d5', 'd4')), ('e4', 'd5'), drop=['d4']),
                                             'not-a-single-move'),
        }
        rejected.update({
            'move plus a piece appearing': (moved(t, ('f3', 'g1'), drop=['h7']), moved(t, ('h7', 'h6')), 'not-a-single-move'),
            'en passant plus another piece vanishing': (ep0, moved(ep0, ('e5', 'd6'), drop=['d5', 'b1']), 'not-a-single-move'),
            'diagonal pawn step while a far enemy pawn vanishes': (ep0, moved(ep0, ('e5', 'd6'), drop=['h7']), 'not-a-single-move'),
            'promotion to the other colour': (pr0, moved(pr0, ('a7', 'a8'), put=[('a8', 'n')]), 'not-a-single-move'),
            'promotion two files across a7-c8': (pr0, moved(pr0, ('a7', 'c8'), put=[('c8', 'N')]), 'not-a-single-move'),
            'en passant removing a knight beside': (dict(ep0, d5='n'), moved(dict(ep0, d5='n'), ('e5', 'd6'), drop=['d5']),
                                                    'not-a-single-move'),
            'en passant onto an occupied square': (dict(ep0, d6='n'), moved(dict(ep0, d6='n'), ('e5', 'd6'), drop=['d5']),
                                                   'not-a-single-move'),
        })
        for name, (b, a, why) in rejected.items():
            for strict in (True, False):
                g = self.guard(withhold_on_unsure_disturbed=strict)
                self.assertIs(review(g, picture_of(b), CB, b).must_withhold(), False, name)
                out = g.check_after_move(self.mid, CB, b, a)
                self.assertIs(out.must_withhold(), True, name)
                self.assertTrue(out.reasons[0].startswith(why), (name, out.reasons))
        # malformed or impossible positions on either side
        for b, a in ((None, t), (t, None), (dict(t, z9='P'), t), (t, moved(t, put=[('d4', 'K')]))):
            self.assertIs(self.guard().check_after_move(self.mid, CB, b, a).must_withhold(), True)

    def test_baseline(self):
        t = self.truth
        before = moved(t, ('f3', 'g1'))
        pic_before, pic_t = render(fen_of(before), scene(QUAD_B)), self.mid
        g = self.guard()
        # after construction the baseline is the reviewed start: a different "before" withholds
        out = g.check_after_move(pic_t, CB, before, t)
        self.assertEqual(out.reasons, ('before-differs-from-baseline',))
        # a plain check never moves the baseline; rebaseline_after_human_review with no objection does
        g.check(pic_before, CB, before)
        self.assertEqual(g.check_after_move(pic_t, CB, before, t).reasons, ('before-differs-from-baseline',))
        g.check(pic_before, CB, before)                                      # settle: g1 confirmed next time
        self.assertIs(g.rebaseline_after_human_review(pic_before, CB, moved(before, put=[('g1', 'B')])).must_withhold(), True)
        self.assertEqual(g._baseline, pc.placement(START))                   # an objection leaves the baseline alone
        self.assertEqual(g.check_after_move(pic_t, CB, before, t).reasons, ('before-differs-from-baseline',))
        self.assertIs(review(g, pic_before, CB, before).must_withhold(), False)
        # the review's case: a wrong "before" (a fake pawn move a3-a2) hides the real move g1-f3; the knight is
        # missing from f3 in the picture
        nof3 = render(fen_of(moved(t, drop=['f3'])), scene(QUAD_B))
        wrong_before = moved(t, ('a2', 'a3'))
        for _ in range(2):
            out = g.check_after_move(nof3, CB, wrong_before, t)
            self.assertEqual(out.reasons, ('before-differs-from-baseline',))
        # the first picture after the move cannot confirm f3: withhold, baseline stays; the same move is checked
        # again on the next picture and accepted; the baseline then moves to the new position
        self.assertIs(g.check_after_move(pic_t, CB, before, t).must_withhold(), True)
        self.assertIs(g.check_after_move(pic_t, CB, before, t).must_withhold(), False)
        a3 = moved(t, ('a2', 'a3'))
        self.assertEqual(g.check_after_move(pic_t, CB, before, t).reasons, ('before-differs-from-baseline',))
        # a withheld move (queen, never checkable) keeps the old baseline: the next move withholds until re-baseline
        qm = moved(t, ('e2', 'e3'))
        pic_qm = render(fen_of(qm), scene(QUAD_B))
        self.assertIs(g.check_after_move(pic_qm, CB, t, qm).must_withhold(), True)
        nxt = moved(qm, ('a2', 'a3'))
        pic_nxt = render(fen_of(nxt), scene(QUAD_B))
        for _ in range(2):
            self.assertEqual(g.check_after_move(pic_nxt, CB, qm, nxt).reasons, ('before-differs-from-baseline',))
        self.assertIs(g.rebaseline_after_human_review(pic_nxt, CB, qm).must_withhold(), True)       # a3 pawn: objection
        self.assertIs(review(g, pic_qm, CB, qm).must_withhold(), False)
        g.check_after_move(pic_nxt, CB, qm, nxt)
        self.assertIs(g.check_after_move(pic_nxt, CB, qm, nxt).must_withhold(), False)
        del a3

    def test_stale_outcome_withholds(self):
        g = self.guard()
        g.check(self.mid, CB, self.truth)
        old = g.check(self.mid, CB, self.truth)
        self.assertIs(old.must_withhold(), False)
        self.assertTrue(old == pg.NO_OBJECTION)
        g.check_after_move(self.mid, CB, self.truth, self.truth)            # a later move call makes `old` stale
        self.assertIs(old.must_withhold(), True)
        old = g.check(self.mid, CB, self.truth)
        self.assertIs(old.must_withhold(), False)
        g.check(self.mid, CB, dict(self.truth, f3='B', c4='N'))            # any later call makes `old` stale
        self.assertIs(old.must_withhold(), True)
        self.assertTrue(old == pg.WITHHOLD)
        latest = g.check(self.mid, CB, self.truth)
        self.assertIs(latest.must_withhold(), False)
        other = self.guard()
        other.check(self.mid, CB, self.truth)                                 # another guard's calls do not matter
        self.assertIs(latest.must_withhold(), False)
        # a forged genuine marker or sequence number is not genuine (m08)
        for marker in (True, object(), 1, pg._GENUINE):
            fake = pg.GuardOutcome(pg.NO_OBJECTION, _genuine=marker, _issuer=g, _seq=g._seq)
            self.assertIs(fake.must_withhold(), marker is not pg._GENUINE, marker)
        self.assertIs(pg.GuardOutcome(pg.NO_OBJECTION, _genuine=pg._GENUINE, _issuer=g, _seq=g._seq - 1).must_withhold(), True)
        self.assertIs(pg.GuardOutcome(pg.NO_OBJECTION, _genuine=pg._GENUINE, _issuer=object(), _seq=1).must_withhold(), True)

    def test_hostile_input_never_escapes(self):
        class Hostile(str):
            def __str__(self):
                raise RuntimeError('x')

            def __eq__(self, other):
                raise RuntimeError('x')

            def __hash__(self):
                return str.__hash__(self)
        hostile_key = {(Hostile(s) if s == 'f3' else s): p for s, p in self.truth.items()}
        hostile_val = {s: (Hostile(p) if s == 'f3' else p) for s, p in self.truth.items()}
        g = self.guard()
        g.check(self.mid, CB, self.truth)
        for bel in (hostile_key, hostile_val):
            out = g.check(self.mid, CB, bel)                                  # copied as plain strings: judged normally
            self.assertIs(out.must_withhold(), False)
            out = g.check_after_move(self.mid, CB, bel, bel)
            self.assertIs(out.must_withhold(), True)
            out = g.check(self.mid, CB, self.truth, disturbed=[Hostile('f3')])
            self.assertIs(out.must_withhold(), True)
        self.assertIs(g.rebaseline_after_human_review(self.mid, CB, self.truth).must_withhold(), False)
        with mock.patch.object(pg, '_move_arrival', side_effect=KeyError('z')):
            out = g.check_after_move(self.mid, CB, self.truth, moved(self.truth, ('a2', 'a3')))
        self.assertEqual(out.reasons, ('malformed-input: KeyError',))
        with mock.patch.object(pg, '_believed', side_effect=RuntimeError('z')):
            self.assertEqual(g.check(self.mid, CB, self.truth).reasons, ('malformed-input: RuntimeError',))
        with mock.patch.object(pg.reader, 'placement', side_effect=RuntimeError('z')):
            self.assertTrue(self.guard().check(self.mid, CB, self.truth).reasons[0].startswith('start-refused'))

    def test_rebaseline_is_an_explicit_human_review_claim(self):
        g = self.guard()
        with self.assertRaises(TypeError):                                    # the old parameter fails loudly
            g.check(self.mid, CB, self.truth, rebaseline=True)
        doc = pg.PieceGuard.rebaseline_after_human_review.__doc__
        for phrase in ('ONLY after a person has reviewed the full position', 'automatically after a withhold defeats the guard',
                       'wrong kings or queens', 'pieces invented on empty squares'):
            self.assertIn(phrase, ' '.join(doc.split()))
        start = dict(g._baseline)
        for image, position in ((self.mid, dict(self.truth, z9='P')), (np.zeros((4, 4)), self.truth),
                                (self.mid, moved(self.truth, put=[('d4', 'K')]))):
            self.assertIs(g.rebaseline_after_human_review(image, CB, position).must_withhold(), True)
            self.assertEqual(g._baseline, start)

    def test_automatic_rebaseline_after_a_withhold_is_the_documented_limit(self):
        # the review's auto_rebase case: the knight really moved f3-g5 and the queen is still on e2, but the tracker
        # also believes the queen vanished. The guard withholds the move. Until round 7 an automatic re-baseline on
        # the same picture was accepted; since round 8 it withholds, because e2 is called empty and not seen empty.
        t = self.truth
        truth = moved(t, ('f3', 'g5'))
        believed = moved(t, ('f3', 'g5'), drop=['e2'])
        g = self.guard()
        self.assertIs(review(g, self.mid, CB, t).must_withhold(), False)
        img = render(fen_of(truth), scene(QUAD_B))
        outs = [g.check_after_move(img, CB, t, believed) for _ in range(2)]
        self.assertEqual([o.reasons for o in outs], [('king-or-queen-moved: never checkable',)] * 2)
        r = [g.rebaseline_after_human_review(img, CB, believed) for _ in range(2)][-1]
        self.assertEqual(r.reasons, ('square called empty not seen empty: e2',))
        self.assertEqual(g._baseline, t)
        # the limit that remains (pinned): the tracker believes the white king and queen swapped squares (e1, e2);
        # both squares hold a piece and the reader never names kings or queens, so an automatic re-baseline on the
        # same picture is ACCEPTED, and the next move then gets no objection. This is why the method may only be
        # called after a person reviewed the position.
        believed = moved(truth, put=[('e1', 'Q'), ('e2', 'K')])
        r = [g.rebaseline_after_human_review(img, CB, believed) for _ in range(2)][-1]
        self.assertIs(r.must_withhold(), False)                               # the limit: accepted without a review
        self.assertEqual(g._baseline['e1'], 'Q')
        nxt = moved(believed, ('c6', 'd4'))
        img2 = render(fen_of(moved(truth, ('c6', 'd4'))), scene(QUAD_B))
        outs = [g.check_after_move(img2, CB, believed, nxt) for _ in range(2)]
        self.assertEqual([o.must_withhold() for o in outs], [True, False])    # first picture unconfirmed, then accepted

    def test_calls_are_serialised_and_outcomes_go_stale_when_a_later_call_starts(self):
        import threading
        t = self.truth
        a1 = moved(t, ('f3', 'g5'))
        pic_a1 = render(fen_of(a1), scene(QUAD_B))
        real_cmp = pc.compare
        wrong = dict(a1, g5='B')                                             # the picture shows a knight on g5
        for later in ('plain check', 'move call', 'rebaseline', 'rebaseline that withholds'):
            g = self.guard()
            self.assertIs(review(g, self.mid, CB, t).must_withhold(), False)
            g.check_after_move(pic_a1, CB, t, a1)                              # first picture of the move
            inside, release, res = threading.Event(), threading.Event(), {}

            def slow(*a, **k):
                if threading.current_thread().name == 'A':
                    inside.set()
                    release.wait(10)
                return real_cmp(*a, **k)
            with mock.patch.object(pc, 'compare', side_effect=slow):
                ta = threading.Thread(name='A', target=lambda: res.__setitem__('A', g.check_after_move(pic_a1, CB, t, a1)))
                ta.start()
                self.assertTrue(inside.wait(10))
                call = {'plain check': lambda: g.check(pic_a1, CB, a1),
                        'move call': lambda: g.check_after_move(pic_a1, CB, t, a1),
                        'rebaseline': lambda: g.rebaseline_after_human_review(pic_a1, CB, a1),
                        'rebaseline that withholds': lambda: g.rebaseline_after_human_review(pic_a1, CB, wrong)}[later]
                tb = threading.Thread(name='B', target=lambda: res.__setitem__('B', call()))
                tb.start()
                tb.join(0.5)
                self.assertTrue(tb.is_alive(), later)                         # B waits for A: calls are serialised
                release.set()
                ta.join(10)
                tb.join(10)
            self.assertIs(res['A'].must_withhold(), True, later)                # B started after A: A's answer is stale
            self.assertEqual(res['A'].reasons, (), later)                      # (it was a no objection when made)
            self.assertIs(type(res['B'].must_withhold()), bool)
            # A's stale answer did not move the baseline; only B (the latest call) can
            moved_by_b = later in ('move call', 'rebaseline') and not res['B'].must_withhold()
            if later == 'rebaseline':
                self.assertIs(moved_by_b, True)                               # the reviewed a1 is on the picture
            if later == 'rebaseline that withholds':                          # B took its number before A decided,
                self.assertIs(res['B'].must_withhold(), True)                 # so A's stale move did not move it (m06)
            self.assertEqual(g._baseline, a1 if moved_by_b else t, later)

    def test_before_is_validated_and_copied_before_the_baseline_comparison(self):
        class Liar(str):
            def __eq__(self, other):
                return True

            def __ne__(self, other):
                return False
            __hash__ = str.__hash__
        t = self.truth
        g = self.guard()
        self.assertIs(review(g, self.mid, CB, t).must_withhold(), False)
        hidden = dict(t, e2=Liar('Q'))
        gone = moved(t, ('f3', 'g5'), drop=['e2'])                            # believed: queen vanished as well
        img = render(fen_of(moved(t, ('f3', 'g5'))), scene(QUAD_B))
        outs = [g.check_after_move(img, CB, hidden, gone) for _ in range(2)]
        self.assertEqual([o.reasons for o in outs], [('king-or-queen-moved: never checkable',)] * 2)
        self.assertIn('e2', g._baseline)
        # a believed_before that differs from the baseline but claims to be equal (m09): compared as its plain copy
        fake_before = dict(t, f3=Liar('B'))                                  # plain value 'B', baseline has 'N'
        out = g.check_after_move(img, CB, fake_before, moved(t, ('f3', 'g5')))
        self.assertEqual(out.reasons, ('before-differs-from-baseline',))

    def test_entry_copies_are_used_after_the_read(self):
        # the caller's belief (and square list) changed while the picture is read must not change the answer
        real_read = pc.read
        for call in ('check', 'check_after_move'):
            g = self.guard()
            before = dict(self.truth, f3='B', c4='N')                          # wrong at entry
            self.assertIs(review(g, picture_of(before), CB, before).must_withhold(), False)   # its own picture
            g.check(self.mid, CB, self.truth)
            bel = moved(before, ('a2', 'a3')) if call == 'check_after_move' else dict(before)
            dist = ['f3']

            def read_and_mutate(*a, **k):
                r = real_read(*a, **k)
                bel.update(self.truth)
                before.clear()
                dist.clear()
                return r
            with mock.patch.object(pg.reader, 'read', side_effect=read_and_mutate):
                out = g.check(self.mid, CB, bel, dist) if call == 'check' else g.check_after_move(self.mid, CB, before, bel)
            self.assertIs(out.must_withhold(), True, call)
            self.assertIn('objection: f3', out.reasons, call)

    def test_impossible_position_boundaries(self):
        t = self.truth
        self.assertEqual(sum(p == 'P' for p in t.values()), 8)
        self.assertEqual(sum(p.isupper() for p in t.values()), 16)
        self.assertEqual(sum(p == 'p' for p in t.values()), 8)
        free = [s for s in pc.SQUARES if s not in t and s[1] in '3456']
        # exactly 8 pawns and exactly 16 pieces of a colour are allowed
        self.assertIs(settled(self.guard(), self.mid, CB, t).must_withhold(), False)
        cases = {'not one king of each colour': [dict(t, **{free[0]: 'k'}), moved(t, drop=['e8'])],
                 'too many white pieces or pawns': [moved(t, drop=['c4'], put=[(free[0], 'P')]),       # 9 pawns, 16 pieces
                                                    dict(t, **{free[0]: 'N'})],                       # 8 pawns, 17 pieces
                 'too many black pieces or pawns': [moved(t, drop=['c5'], put=[(free[0], 'p')]),
                                                    dict(t, **{free[0]: 'n'})]}
        for why, beliefs in cases.items():
            for believed in beliefs:
                out = settled(self.guard(withhold_on_unsure_disturbed=False), self.mid, CB, believed)
                self.assertEqual((out.must_withhold(), out.reasons), (True, ('impossible-position: ' + why,)))

    # ---- what the guard cannot see: a self-consistently wrong start -----------------------------------------------
    def test_self_consistently_wrong_start_gives_no_objection_at_most(self):
        # demo_guard.py case 1: the picture shows knights and bishops swapped on both sides (960-like) but the start is
        # reviewed as the standard position; after "g1-f3" the reader agrees with 8 wrong squares
        pic960 = 'rbnqknbr/pppppppp/8/8/8/8/PPPPPPPP/RBNQKNBR w - - 0 1'
        shown_after = 'rbnqknbr/pppppppp/8/8/8/5B2/PPPPPPPP/RBNQKN1R w - - 0 1'
        belief = pc.placement('rnbqkbnr/pppppppp/8/8/8/5N2/PPPPPPPP/RNBQKB1R w - - 0 1')
        start = [(render(pic960, scene(QUAD_A)), CA)]
        picture = render(shown_after, scene(QUAD_B))
        # the situation: underneath, the reader calls the wrong squares consistent
        cal = pc.calibrate(start, START)
        self.assertEqual(cal['state'], 'ok')
        res = pc.read(picture, CB, cal, previous=pc.read(picture, CB, cal))
        wrong = [s for s in pc.SQUARES if belief.get(s) != pc.placement(shown_after).get(s)]
        self.assertEqual(sum(pc.compare(res, belief)['squares'][s] == 'consistent' for s in wrong), 8)
        # the guard: 'no objection' at most, never anything that reads as a confirmation
        for strict in (True, False):
            for disturbed in ((), ('f3',), ('g1', 'f3')):
                out = settled(pg.PieceGuard(start, START, withhold_on_unsure_disturbed=strict), picture, CB, belief,
                              disturbed)
                self.assert_no_confirmation(out)
                if not (strict and 'g1' in disturbed):
                    self.assertEqual(out.must_withhold(), False)
        # demo_guard.py case 2: the start learned with the board turned 180 degrees, later pictures with the same lock
        rot = lambda c: c[2:] + c[:2]                                                    # noqa: E731
        g = pg.PieceGuard([(render(START, scene(QUAD_A)), rot(CA))], START)
        out = settled(g, self.mid, rot(CB), self.truth)
        self.assert_no_confirmation(out)

    # ---- the disturbed-square option ----------------------------------------------------------------------------
    def test_disturbed_square_option(self):
        # e2 holds the white queen, which the reader never names (one start square): 'cannot tell' there
        for disturbed in (('e2',), ('e2', 'f3'), 'e2', ('d4',)):
            strict = settled(self.guard(), self.mid, CB, self.truth, disturbed)
            lenient = settled(self.guard(withhold_on_unsure_disturbed=False), self.mid, CB, self.truth, disturbed)
            self.assertEqual(strict.must_withhold(), True, disturbed)
            unsure = [s for s in (disturbed if isinstance(disturbed, tuple) else (disturbed,)) if s != 'f3']
            self.assertEqual(strict.reasons, tuple('cannot-tell on disturbed square: ' + s for s in unsure))
            self.assertEqual(lenient.must_withhold(), False, disturbed)
        # f3 holds a well-learned knight the reader names: no objection either way
        for strict in (True, False):
            out = settled(self.guard(withhold_on_unsure_disturbed=strict), self.mid, CB, self.truth, ('f3',))
            self.assertEqual(out.must_withhold(), False)
        # the strict value is the default
        self.assertTrue(self.guard().withhold_on_unsure_disturbed)
        # the first picture after a new guard cannot be confirmed (no previous reading): strict withholds on f3 too
        out = self.guard().check(self.mid, CB, self.truth, ('f3',))
        self.assertEqual(out.must_withhold(), True)

    # ---- round 6 ------------------------------------------------------------------------------------------------
    def test_rebaseline_needs_evidence_in_the_picture(self):
        # the review's badcorners.py: degenerate corners make the reader say 'cannot tell' on all 64 squares without
        # refusing; a re-baseline to a wrong position must withhold and leave the baseline alone
        t = self.truth
        a1 = moved(t, ('f3', 'g5'))
        b1 = moved(a1, ('c6', 'd4'))                                          # wrong: the picture shows a1
        for corners in ([[0, 0], [1, 0], [1, 1], [0, 1]], [[0, 0], [10, 0], [10, 10], [0, 10]],
                        [[0, 0], [100, 0], [200, 0], [300, 0]]):
            g = self.guard()
            self.assertIs(review(g, self.mid, CB, t).must_withhold(), False)
            outs = [g.rebaseline_after_human_review(picture_of(a1), corners, b1) for _ in range(2)]
            self.assertEqual([o.must_withhold() for o in outs], [True, True], corners)
            self.assertTrue(all(o.reasons[0].startswith('too-little-evidence: 0 of') for o in outs), outs)
            self.assertEqual(g._baseline, t)
            # check_after_move already withholds there: the arrival square is never named
            outs = [g.check_after_move(picture_of(a1), corners, t, a1) for _ in range(2)]
            self.assertEqual([o.must_withhold() for o in outs], [True, True], corners)
            self.assertEqual(g._baseline, t)
        # the first picture of a new guard names nothing (the reader's confirmation rule): withhold, then accepted
        g = self.guard()
        out = g.rebaseline_after_human_review(self.mid, CB, t)
        self.assertEqual(out.reasons, ('too-little-evidence: 0 of 28 nameable pieces named',))   # 32 minus kings, queens
        self.assertEqual(g._baseline, pc.placement(START))
        self.assertIs(g.rebaseline_after_human_review(self.mid, CB, t).must_withhold(), False)
        self.assertEqual(g._baseline, t)
        # the share: kings and queens never count; below REBASELINE_NAMED_SHARE withholds, at it passes
        self.assertEqual(g._nameable, frozenset('PNBRpnbr'))
        nameable = [s for s, p in sorted(t.items()) if p not in 'KQkq']
        need = -(-len(nameable) * 3 // 4)                                       # ceil(0.75 x 28) = 21
        self.assertEqual((len(nameable), need), (28, 21))
        self.assertEqual(pg.REBASELINE_NAMED_SHARE, 0.75)
        for named, withhold in ((need - 1, True), (need, False), (1, True)):
            sq = {s: 'cannot-tell' for s in pc.SQUARES}
            sq.update({s: 'consistent' for s in nameable[:named]})
            sq.update({s: 'consistent' for s, p in t.items() if p in 'KQkq'})    # never counted
            fake = {'verdict': 'cannot-tell', 'reason': 'unsure-squares', 'squares': sq}
            g = self.guard()
            g.check(self.mid, CB, t)                                           # no square 'unconfirmed' next time
            with mock.patch.object(pg.reader, 'compare', return_value=fake):
                out = g.rebaseline_after_human_review(self.mid, CB, t)
            self.assertIs(out.must_withhold(), withhold, named)
            self.assertEqual(g._baseline, pc.placement(START) if withhold else t, named)
            if withhold:
                self.assertEqual(out.reasons, (f'too-little-evidence: {named} of 28 nameable pieces named',))
        # a start that learned no kind well enough leaves nothing nameable: every re-baseline withholds
        g = self.guard()
        with mock.patch.object(g, '_nameable', frozenset()):
            outs = [g.rebaseline_after_human_review(self.mid, CB, t) for _ in range(2)]
        self.assertEqual(outs[-1].reasons, ('too-little-evidence: 0 of 0 nameable pieces named',))

    def test_reentrant_call_withholds_and_does_not_deadlock(self):
        import threading
        t = self.truth
        a1 = moved(t, ('f3', 'g5'))
        pic_a1 = picture_of(a1)
        real_read = pc.read
        calls = lambda g: {'check': lambda: g.check(pic_a1, CB, a1),                     # noqa: E731
                           'check_after_move': lambda: g.check_after_move(pic_a1, CB, t, a1),
                           'rebaseline': lambda: g.rebaseline_after_human_review(pic_a1, CB, a1)}
        for outer in ('check', 'check_after_move', 'rebaseline'):
            for kind in ('check', 'check_after_move', 'rebaseline'):                # each inner call on its own (n12)
                g = self.guard()
                self.assertIs(review(g, self.mid, CB, t).must_withhold(), False)
                g.check_after_move(pic_a1, CB, t, a1)                          # first picture of the move
                inner, depth = {}, []

                def hook(*a, **k):                                             # e.g. a reader callback into the guard
                    if not depth:
                        depth.append(1)
                        inner[kind] = calls(g)[kind]()
                    return real_read(*a, **k)
                res = {}
                with mock.patch.object(pg.reader, 'read', side_effect=hook):
                    th = threading.Thread(target=lambda: res.__setitem__('out', calls(g)[outer]()), daemon=True)
                    th.start()
                    th.join(20)
                self.assertFalse(th.is_alive(), f'{outer}/{kind}: deadlock')
                self.assertEqual((inner[kind].must_withhold(), inner[kind].reasons), (True, (pg._REENTRANT,)),
                                 (outer, kind))
                self.assertIs(res['out'].must_withhold(), True, (outer, kind))   # a call happened during it
                self.assertEqual(g._baseline, t, (outer, kind))
                # the guard still works afterwards: the same move is accepted on the next picture
                self.assertIs(g.check_after_move(pic_a1, CB, t, a1).must_withhold(), False, (outer, kind))

    def test_rebaseline_refuses_a_picture_that_changed_since_the_previous_one(self):
        # the sixth review's c_follow.py: the guard sees X, then a re-baseline claims X on a slightly different
        # picture Y; the changed square is 'unconfirmed' (cannot tell), so the 0.75 share alone let it through
        t = self.truth
        for name, y in (('knight f3-g5', moved(t, ('f3', 'g5'))), ('pawn a2-a4', moved(t, ('a2', 'a4'))),
                        ('bishop c4xf7', moved(t, ('c4', 'f7'))), ('knight f3 -> bishop', moved(t, put=[('f3', 'B')])),
                        ('two changes', moved(t, ('f3', 'g5'), ('c6', 'd4')))):
            g = self.guard()
            self.assertIs(review(g, self.mid, CB, t).must_withhold(), False)
            g.check(self.mid, CB, t)                                          # the guard has just seen X
            out = g.rebaseline_after_human_review(picture_of(y), CB, t)      # picture Y, claiming X
            self.assertIs(out.must_withhold(), True, name)
            self.assertTrue(out.reasons and all(r.startswith('unconfirmed square') or r.startswith('objection')
                                                for r in out.reasons), (name, out.reasons))
            self.assertEqual(g._baseline, t, name)
            # the honest claim on that changed picture also withholds once; on the next picture of Y it is accepted
            g.check(self.mid, CB, t)
            self.assertIs(g.rebaseline_after_human_review(picture_of(y), CB, y).must_withhold(), True, name)
            self.assertIs(g.rebaseline_after_human_review(picture_of(y), CB, y).must_withhold(), False, name)
            self.assertEqual(g._baseline, y, name)
        # the knight case exactly: the one changed square is named in the reason
        g = self.guard()
        review(g, self.mid, CB, t)
        g.check(self.mid, CB, t)
        out = g.rebaseline_after_human_review(picture_of(moved(t, ('f3', 'g5'))), CB, t)
        self.assertEqual(out.reasons, ('unconfirmed square (picture changed since the previous one): g5',))

    def test_decision_and_baseline_update_cannot_be_split_by_a_later_call(self):
        # n17: while a call decides and moves the baseline, a later call on another thread cannot take its sequence
        # number in between (it waits on the sequence lock until the baseline is set)
        import threading
        t = self.truth
        a1 = moved(t, ('f3', 'g5'))
        pic_a1 = picture_of(a1)
        real_mw = pg.GuardOutcome.must_withhold
        for method in ('check_after_move', 'rebaseline'):
            g = self.guard()
            self.assertIs(review(g, self.mid, CB, t).must_withhold(), False)
            g.check_after_move(pic_a1, CB, t, a1)
            state = {}

            def mw(out):
                if threading.current_thread().name == 'A' and 'b' not in state:   # the decision inside the call
                    state['b'] = threading.Thread(target=g._enter, daemon=True)     # a later call starting
                    state['b'].start()
                    state['b'].join(0.5)
                    state['b_done_during_decision'] = not state['b'].is_alive()
                return real_mw(out)
            res = {}
            call = (lambda: g.check_after_move(pic_a1, CB, t, a1)) if method == 'check_after_move' else \
                (lambda: g.rebaseline_after_human_review(pic_a1, CB, a1))
            with mock.patch.object(pg.GuardOutcome, 'must_withhold', mw):
                ta = threading.Thread(name='A', target=lambda: res.__setitem__('A', call()), daemon=True)
                ta.start()
                ta.join(20)
                state['b'].join(5)
            self.assertIs(state['b_done_during_decision'], False, method)
            self.assertEqual(g._baseline, a1, method)                       # decided before the later call started
            self.assertIs(res['A'].must_withhold(), True, method)            # ... which makes the answer stale

    def test_baseline_moves_only_with_a_still_valid_decision_and_a_later_stale_answer_fails_safe(self):
        t = self.truth
        a1 = moved(t, ('f3', 'g5'))
        b1 = moved(a1, ('c6', 'd4'))
        pic_a1, pic_b1 = picture_of(a1), picture_of(b1)
        doc = ' '.join(pg.PieceGuard.check_after_move.__doc__.split())
        for phrase in ('only if no later call on this guard has started by then', 'the caller reads withhold',
                       'can only add withholds'):
            self.assertIn(phrase, doc)
        real_cmp = pc.compare
        for method in ('check_after_move', 'rebaseline'):
            # a later call takes its sequence number before the decision: no baseline move, the answer withholds
            g = self.guard()
            self.assertIs(review(g, self.mid, CB, t).must_withhold(), False)
            g.check(pic_a1, CB, a1)

            def later_starts(*a, **k):
                g._enter()                                                     # what a later call does first
                return real_cmp(*a, **k)
            with mock.patch.object(pg.reader, 'compare', side_effect=later_starts):
                out = (g.check_after_move(pic_a1, CB, t, a1) if method == 'check_after_move'
                       else g.rebaseline_after_human_review(pic_a1, CB, a1))
            self.assertIs(out.must_withhold(), True, method)
            self.assertEqual(g._baseline, t, method)
        # a later call that starts after the decision: the caller reads withhold, the baseline has moved (documented)
        g = self.guard()
        self.assertIs(review(g, self.mid, CB, t).must_withhold(), False)
        g.check_after_move(pic_a1, CB, t, a1)
        out = g.check_after_move(pic_a1, CB, t, a1)
        self.assertIs(out.must_withhold(), False)
        g.check(pic_a1, CB, a1)                                                # the later call
        self.assertIs(out.must_withhold(), True)
        self.assertEqual(g._baseline, a1)
        # fails safe: repeating the move withholds; the next move from a1 is checked as usual
        self.assertEqual(g.check_after_move(pic_a1, CB, t, a1).reasons, ('before-differs-from-baseline',))
        outs = [g.check_after_move(pic_b1, CB, a1, b1) for _ in range(2)]
        self.assertEqual([o.must_withhold() for o in outs], [True, False])

    # ---- round 8 ------------------------------------------------------------------------------------------------
    def test_rebaseline_refuses_a_piece_on_a_square_called_empty_under_corner_jitter(self):
        # the seventh review's atk7b/atk7c: the guard saw X; one piece moved to an empty square (picture Y); a review
        # claiming X was accepted because the square where the piece really stands read 'thin-runner-up' (not
        # 'unconfirmed') under jittered corners. Every square the claim calls empty must now read 'no-piece-seen'.
        def jitter(px, seed):
            r = np.random.default_rng(seed)
            return [list(np.asarray(p) + r.uniform(-px, px, 2)) for p in CB]
        for fen, a, b, px, seed in (('rn1qkbnr/1Ppppppp/8/8/8/8/1PPPPPPP/RNBQKBNR w - - 0 1', 'f1', 'b6', 2, 635513),
                                    ('3r1rk1/pp1nbppp/4pn2/5b2/3P4/2N1B3/PPP2PPP/R2QKBNR w - - 0 1', 'a2', 'd5', 2, 15238),
                                    ('rn1qkbnr/1Ppppppp/8/8/8/8/1PPPPPPP/RNBQKBNR w - - 0 1', 'f1', 'f3', 5, 11487)):
            x = pc.placement(fen)
            y = moved(x, (a, b))
            corners = jitter(px, seed)
            g = self.guard()
            g.check(picture_of(x), corners, x)                                 # the guard has just seen X
            out = g.rebaseline_after_human_review(picture_of(y), corners, x)  # picture Y, claiming X
            self.assertIs(out.must_withhold(), True, (a, b))
            self.assertIn('square called empty not seen empty: ' + b, out.reasons, (a, b))
            self.assertEqual(g._baseline, pc.placement(START), (a, b))

    def test_rebaseline_refuses_a_king_or_queen_capture_hidden_in_the_claim(self):
        # the seventh review's atk7d: a king or queen captured a pawn, knight or bishop (picture Y) and the review
        # claims the position before the capture (X). The capturer's old square reads 'no-piece-seen' although the
        # claim calls it occupied; without the rule the captured piece stayed as a phantom in the baseline.
        t = self.truth
        x2 = moved(t, drop=['a7'], put=[('d2', 'n')])                         # a black knight the white king can take
        cases = (('Q e2xe5', t, moved(t, ('e2', 'e5')), 'e2'), ('q e7xe4', t, moved(t, ('e7', 'e4')), 'e7'),
                 ('Q e2xc6', t, moved(t, ('e2', 'c6')), 'e2'), ('K e1xd2', x2, moved(x2, ('e1', 'd2')), 'e1'))
        for name, x, y, old in cases:
            for seen in ('x', 'y'):
                g = self.guard()
                g.check(picture_of(x if seen == 'x' else y), CB, x)
                out = g.rebaseline_after_human_review(picture_of(y), CB, x)
                self.assertIs(out.must_withhold(), True, (name, seen))
                self.assertIn('square called occupied seen without a piece: ' + old, out.reasons, (name, seen))
                self.assertEqual(g._baseline, pc.placement(START), (name, seen))
            # the honest claim of the same picture is accepted
            self.assertIs(review(g, picture_of(y), CB, y).must_withhold(), False, name)
            self.assertEqual(g._baseline, y, name)

    def test_knight_moving_diagonally_withholds(self):
        # mutant m11 of the seventh review (a knight may also move one or two squares diagonally) survived the suite
        t = self.truth
        g = self.guard()
        self.assertIs(review(g, self.mid, CB, t).must_withhold(), False)
        # one or two squares diagonally, onto an empty square or (c6xe4) onto an enemy piece
        for a, b in (('f3', 'g4'), ('f3', 'h5'), ('f3', 'd1'), ('c6', 'd5'), ('c6', 'e4')):
            with self.assertRaises(pg._Malformed, msg=(a, b)) as cm:
                pg._move_arrival(pg._believed(t), pg._believed(moved(t, (a, b))))
            self.assertTrue(str(cm.exception).startswith(f'not-a-single-move: {t[a]} cannot go {a}-{b}'), cm.exception)
        for b in ('g4', 'h5'):
            after = moved(t, ('f3', b))
            outs = [g.check_after_move(picture_of(after), CB, t, after) for _ in range(2)]
            self.assertEqual([o.must_withhold() for o in outs], [True, True], b)
            self.assertTrue(all(o.reasons[0].startswith('not-a-single-move: N cannot go f3-' + b) for o in outs), b)
            self.assertEqual(g._baseline, t, b)


    def test_rebaseline_empty_evidence_rule_independently_withholds(self):
        # Fault injection at the reader boundary: all occupied squares remain correct, but one claimed empty
        # square is unsure. Unlike the move fixtures, no vacated occupied square can mask removal of this rule.
        g = self.guard()
        settled(g, self.mid, CB, self.truth)
        reading = copy.deepcopy(g._previous)
        self.assertNotIn('a3', self.truth)
        self.assertEqual(reading['a3']['reason'], 'no-piece-seen')
        baseline = dict(g._baseline)
        for reason in ('thin-runner-up', 'thin-evidence'):
            reading['a3'].update(label='unsure', reason=reason)
            with mock.patch.object(pg.reader, 'read', return_value=reading):
                out = g.rebaseline_after_human_review(self.mid, CB, self.truth)
            self.assertIs(out.must_withhold(), True, reason)
            self.assertEqual(g._baseline, baseline, reason)
        reading['a3'].update(label='unsure', reason='no-piece-seen')
        with mock.patch.object(pg.reader, 'read', return_value=reading):
            out = g.rebaseline_after_human_review(self.mid, CB, self.truth)
        self.assertIs(out.must_withhold(), False)  # positive control: the test can accept correct evidence
        self.assertEqual(g._baseline, self.truth)


if __name__ == '__main__':
    result = unittest.main(exit=False, verbosity=1).result
    print(f'{result.testsRun - len(result.failures) - len(result.errors)} of {result.testsRun} tests passed'
          f' ({len(result.skipped)} skipped)')
    sys.exit(0 if result.wasSuccessful() else 1)
