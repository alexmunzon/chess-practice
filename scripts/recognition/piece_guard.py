#!/usr/bin/env python3
"""Withhold-only guard around the piece-type reader v2 (feasibility prototype; NOT connected to anything).

THE ONE CALLER PATTERN:
    out = guard.check_after_move(image, corners, believed_before, believed_after)   # or guard.check(...)
    if out.must_withhold():
        pause advice                 # out.reasons says why
    # otherwise: change nothing. 'no objection' is no information; it never restores or grants advice.
Read each outcome at once: `must_withhold()` is True for any outcome once a later call on the same guard has
STARTED, so an old 'no objection' kept for later always reads as withhold. Calls on one guard are serialised by a lock.

The guard can only take advice away. Its answer has exactly two values: withhold (with at least one reason) and
no objection. `must_withhold()` returns a plain bool: False only for a genuine no-objection outcome made by the guard
itself and still the guard's latest outcome; True for everything else (including outcomes a caller builds by hand).
`out == WITHHOLD` and `out == NO_OBJECTION` follow must_withhold(). Everything else raises TypeError: other
comparisons, ordering, hashing, `if out:`, `str(out)`, f-strings, the old `.outcome` attribute, any unknown attribute
(so `getattr(out, name, default)` raises too), pickling and copying. Python cannot intercept `out is ...` or
`isinstance(...)`; those stay wrong and are listed in docs/PIECE_CLASSIFIER.md.

Why "no objection" carries no information (review of 2026-11-17): a start reviewed wrongly in a self-consistent way
(knight and bishop swapped on both sides, the board turned 180 degrees) is learned without complaint, and the reader
then agrees with wrong squares; a piece paused mid-slide can be named where the tracker made the same mistake.

It withholds on: any objection from the reader; any exception (other than interrupt-type ones such as
KeyboardInterrupt) from the reader, from validating the caller's input or inside the guard (caught broadly, fail
closed); a missing or refused start; a reading the reader refused (bad picture, bad corners, a board orientation
different from the start's); a believed position that cannot be normalised or is impossible (squares off the board,
unknown piece letters, not exactly one king of each colour, a pawn on rank 1 or 8, more than 8 pawns or more than 16
pieces of one colour); square lists that cannot be normalised; and 'cannot tell' on the squares the calling style
names (below). Every input is validated and copied once at entry; nothing the caller passed is read again after that.

Ways to call it:
  1. check(..., disturbed=from_and_to_squares), strict default (withhold_on_unsure_disturbed=True): 'cannot tell'
     on any listed square withholds. The reader never says "empty", so a vacated square is always 'cannot tell'.
  2. check(..., disturbed=...) with PieceGuard(..., withhold_on_unsure_disturbed=False): only objections and
     failures withhold.
  3. check_after_move(image, corners, believed_before, believed_after): the guard checks that the change is the SHAPE
     of one real move and judges the arrival square itself. Accepted shapes, and nothing else:
       - one piece leaves one square and the same piece (colour and kind) arrives on a square that was empty or held
         an enemy piece other than a king, along a line that kind can move on an empty board (knight L, bishop
         diagonal, rook straight line; a pawn one square forward to an empty square, two forward from its start rank
         to an empty square, or one square diagonally forward onto an enemy piece);
       - promotion: a pawn leaves the 7th rank (white) or 2nd rank (black) and a queen, rook, bishop or knight of its
         colour arrives on the last rank, straight onto an empty square or diagonally onto an enemy piece;
       - en passant: a pawn moves diagonally forward onto an empty square of the 6th (white) or 3rd (black) rank and
         the enemy pawn beside its origin square is removed.
     Everything else withholds: castling, two movers, a piece vanishing or appearing, in-place kind or colour changes,
     teleports, identical positions, any move whose vacated square held a king or queen and any arriving king or
     queen (the reader never names kings or queens). Blockers, checks and whose turn it is are NOT checked: move
     legality is the tracker's job; the guard checks shape only. 'cannot tell' on the arrival square withholds
     whatever the strict setting; vacated squares withhold only on an objection.
     The guard keeps a baseline: the position it last accepted. It starts as the reviewed start position and becomes
     believed_after only when check_after_move decides no objection while no later call has started (see its
     docstring for the one case where the caller then reads withhold because a later call started afterwards).
     believed_before must equal the baseline, else the call withholds. A withhold decided by the call leaves the
     baseline where it was: the same move can be checked again on the
     next picture (the first picture after a move cannot confirm the arrival square), but a later move withholds
     until the caller calls rebaseline_after_human_review(...), which sets the baseline to the reviewed position
     only when a full check of it answers no objection and the reader names enough of its pieces (a picture that
     shows nothing is refused). Call it ONLY after a person has reviewed the full position:
     calling it automatically after a withhold defeats the guard, because the guard cannot see wrong kings or
     queens or pieces invented on empty squares.
     The first picture after a move always withholds: the reader names a piece only when the previous picture's
     best match on that square was the same kind (its mid-move rule), so the arrival square is 'cannot tell' until
     a second picture of the new position confirms it.
The default of `check` stays 1 until the owner decides.

Use: one PieceGuard per game. Call it on every settled picture, in order, with the FULL believed position
({square: piece}, absent = empty); the guard keeps the previous reading itself (the reader's confirmation rule needs
it). Runtime inputs only.

    guard = PieceGuard(start_pictures, start_fen)              # [(image, corners a8,h8,h1,a1)], reviewed FEN
    out = guard.check_after_move(image, corners, believed_before, believed_after)
    if out.must_withhold(): ...                                 # pause advice, ask for review
"""
import contextlib
import threading

import piece_classifier_v2 as reader

WITHHOLD = 'withhold'
# rebaseline_after_human_review: the share of nameable pieces in the reviewed position the reader must name
# consistently (chosen from the honest re-baselines of the legal-play run; see docs/PIECE_CLASSIFIER.md)
REBASELINE_NAMED_SHARE = 0.75
_UNCONFIRMED = 'unconfirmed'       # piece_classifier_v2.read_tiles: previous picture's best match here was another kind
_REENTRANT = 're-entrant-call: a call on this guard was made from inside another call on it'
NO_OBJECTION = 'no objection'
OUTCOMES = (WITHHOLD, NO_OBJECTION)
# compare() reasons that mean the believed position or the reading cannot be judged at all
_JUDGE_FAILED = ('malformed-result', 'malformed-belief', 'partial-belief', 'reading-refused')
_VERDICTS = ('objection', 'consistent', 'cannot-tell')
_SQUARE_LISTS = (tuple, list, set, frozenset)          # concrete containers only: no one-pass iterators
_GENUINE = object()                                    # marks no-objection outcomes made by the guard itself
_FILES = 'abcdefgh'


class GuardOutcome:
    """The guard's answer. Use `out.must_withhold()` (a plain bool) at once. `reasons`: why advice is withheld; a
    withhold always has at least one reason and 'no objection' has none.
    'no objection' is no information and must never restore or grant advice.
    must_withhold() is True for any outcome that is not the most recent one made by its guard.
    `out == WITHHOLD` / `out == NO_OBJECTION` follow must_withhold(); any other comparison, ordering, hashing,
    truth-testing, str(), format(), unknown attribute, pickling or copying raises TypeError."""
    __slots__ = ('_outcome', '_reasons', '_genuine', '_issuer', '_seq')

    def __init__(self, outcome, reasons=(), *, _genuine=None, _issuer=None, _seq=None):
        if type(outcome) is not str or outcome not in OUTCOMES:
            raise ValueError(f'outcome must be one of {OUTCOMES}')
        if not isinstance(reasons, tuple) or not all(isinstance(r, str) and r for r in reasons):
            raise ValueError('reasons must be a tuple of non-empty strings')
        if (outcome == WITHHOLD) != bool(reasons):
            raise ValueError('a withhold needs at least one reason; no objection has none')
        genuine = _genuine is _GENUINE and outcome == NO_OBJECTION and isinstance(_issuer, PieceGuard)
        object.__setattr__(self, '_outcome', outcome)
        object.__setattr__(self, '_reasons', tuple(str.__str__(r) for r in reasons))
        object.__setattr__(self, '_genuine', genuine)
        object.__setattr__(self, '_issuer', _issuer if genuine else None)
        object.__setattr__(self, '_seq', _seq if genuine else None)

    def must_withhold(self):
        """True unless this is a genuine no-objection outcome made by the guard and still its latest outcome."""
        return not (self._genuine is True and self._outcome == NO_OBJECTION
                    and self._issuer is not None and self._issuer._seq == self._seq)

    @property
    def reasons(self):
        return self._reasons

    @property
    def outcome(self):
        raise TypeError('use out.must_withhold()')

    def __getattr__(self, name):
        raise TypeError(f'GuardOutcome has no attribute {name!r}; use out.must_withhold()')

    def __setattr__(self, name, value):
        raise AttributeError('GuardOutcome is read-only')

    __delattr__ = __setattr__

    def _side(self, other):
        if type(other) is str and other in OUTCOMES:
            return other == WITHHOLD
        raise TypeError('compare a GuardOutcome only with WITHHOLD or NO_OBJECTION, or use out.must_withhold()')

    def __eq__(self, other):
        return self._side(other) == self.must_withhold()

    def __ne__(self, other):
        return self._side(other) != self.must_withhold()

    def __bool__(self):
        raise TypeError("use out.must_withhold(); 'no objection' is not a confirmation")

    def _refuse(self, *args):
        raise TypeError('use out.must_withhold()')

    __lt__ = __le__ = __gt__ = __ge__ = __str__ = __format__ = __reduce__ = __reduce_ex__ = _refuse
    __copy__ = __deepcopy__ = __getstate__ = _refuse
    __hash__ = None

    def __repr__(self):
        return f"<GuardOutcome {'MUST-WITHHOLD' if self.must_withhold() else 'no-objection (no information)'}" \
               f" reasons={self._reasons!r}>"


class _Malformed(Exception):
    pass


def _plain_str(x):
    """An exact str copy of a str (or str subclass) without calling any of the subclass's methods; None otherwise."""
    return str.__str__(x) if isinstance(x, str) else None


def _believed(believed):
    """-> plain {square: piece} copy of a possible full position; _Malformed otherwise. Reads a dict's own storage
    (dict.items), so a subclass that overrides get() or items() cannot show the guard something else."""
    if not isinstance(believed, dict):
        raise _Malformed('malformed-belief')
    out = {}
    for s, p in list(dict.items(believed)):
        s, p = _plain_str(s), _plain_str(p)
        if s is None or p is None or s not in reader.SQUARES or len(p) != 1 or p not in reader.PIECES:
            raise _Malformed('malformed-belief')
        out[s] = p
    pieces = list(out.values())
    if pieces.count('K') != 1 or pieces.count('k') != 1:
        raise _Malformed('impossible-position: not one king of each colour')
    if any(p in 'Pp' and s[1] in '18' for s, p in out.items()):
        raise _Malformed('impossible-position: pawn on rank 1 or 8')
    for colour, is_white in (('white', True), ('black', False)):
        mine = [p for p in pieces if p.isupper() == is_white]
        if len(mine) > 16 or sum(p in 'Pp' for p in mine) > 8:
            raise _Malformed(f'impossible-position: too many {colour} pieces or pawns')
    return out


def _squares(value, what):
    """-> tuple of square names; None or an empty container = no squares; a single square name is allowed.
    Anything else (one-pass iterators, other objects, unknown names) is _Malformed."""
    if value is None:
        return ()
    if type(value) is str:
        value = (value,)
    if type(value) not in _SQUARE_LISTS:
        raise _Malformed(f'malformed-{what}-squares')
    out = tuple(value)
    if not all(type(s) is str and s in reader.SQUARES for s in out):
        raise _Malformed(f'malformed-{what}-squares')
    return out


def _xy(square):
    return _FILES.index(square[0]), int(square[1])


def _white(piece):
    return piece.isupper()


def _enemy(target, piece):
    """True when target (a piece letter or None) is an enemy of piece that may be captured (not a king)."""
    return target is not None and _white(target) != _white(piece) and target not in 'Kk'


def _line_ok(kind, a, b):
    (fa, ra), (fb, rb) = _xy(a), _xy(b)
    df, dr = abs(fb - fa), abs(rb - ra)
    if kind == 'n':
        return {df, dr} == {1, 2}
    if kind == 'b':
        return df == dr > 0
    if kind == 'r':
        return (df == 0) != (dr == 0)
    return False                                            # kings and queens are refused before this point


def _pawn_ok(piece, a, b, target):
    (fa, ra), (fb, rb) = _xy(a), _xy(b)
    step = 1 if _white(piece) else -1
    if fb == fa and target is None:
        return rb - ra == step or (rb - ra == 2 * step and ra == (2 if step == 1 else 7))
    return abs(fb - fa) == 1 and rb - ra == step and _enemy(target, piece)


def _move_arrival(before, after):
    """Two validated positions -> the single arrival square of a real single-move shape; _Malformed otherwise.
    Shape only: blockers, checks and turn order are the tracker's job."""
    changed = [s for s in reader.SQUARES if before.get(s) != after.get(s)]
    if not changed:
        raise _Malformed('no-move: positions identical')
    arrivals = [s for s in changed if s in after]
    vacated = [s for s in changed if s not in after]
    if any(before.get(s) in ('K', 'Q', 'k', 'q') for s in vacated):
        raise _Malformed('king-or-queen-moved: never checkable')
    if len(arrivals) != 1 or len(vacated) not in (1, 2):
        raise _Malformed(f'not-a-single-move: {len(arrivals)} arrivals, {len(vacated)} vacated')
    b = arrivals[0]
    piece, target = after[b], before.get(b)
    if piece in 'KQkq':
        raise _Malformed('king-or-queen-moved: never checkable')
    if len(vacated) == 1:
        a = vacated[0]
        mover = before[a]
        if _white(mover) != _white(piece) or (target is not None and not _enemy(target, piece)):
            raise _Malformed('not-a-single-move: colour or capture does not fit')
        if mover == piece:
            if piece in 'Pp':
                ok = _pawn_ok(piece, a, b, target)
            else:
                ok = _line_ok(piece.lower(), a, b)
            if ok:
                return b
            raise _Malformed(f'not-a-single-move: {piece} cannot go {a}-{b}')
        if mover in 'Pp' and piece.lower() in 'rbn' and a[1] == ('7' if _white(mover) else '2') \
                and b[1] == ('8' if _white(mover) else '1') and _pawn_ok(mover, a, b, target):
            return b                                            # promotion (a queen arrival was refused above)
        raise _Malformed(f'not-a-single-move: {mover} on {a} cannot become {piece} on {b}')
    # two vacated squares: only en passant
    pawn = 'P' if _white(piece) else 'p'
    enemy = 'p' if pawn == 'P' else 'P'
    for a in vacated:
        c = b[0] + a[1]                                     # beside the origin square, on the arrival file
        if piece == pawn and before.get(a) == pawn and c in vacated and before.get(c) == enemy and target is None \
                and a[1] == ('5' if pawn == 'P' else '4') and b[1] == ('6' if pawn == 'P' else '3') \
                and abs(_FILES.index(b[0]) - _FILES.index(a[0])) == 1:
            return b
    raise _Malformed('not-a-single-move: two squares vacated and not en passant')


def _nameable(cal):
    """Piece letters the reader can name after this start: kinds it learned from at least EVIDENCE_MIN start squares,
    of a colour whose six kinds were all learned, never kings or queens (the reader's own rules in read_tiles)."""
    kinds, evidence = list(cal.get('kinds') or ()), dict(cal.get('evidence') or {})
    out = set()
    for colour in ('PNBRQK', 'pnbrqk'):
        if all(p in kinds for p in colour):
            out |= {p for p in colour if p not in 'KQkq' and evidence.get(p, 0) >= reader.POLICY['EVIDENCE_MIN']}
    return frozenset(out)


def _compare_ok(cmp):
    return (isinstance(cmp, dict) and cmp.get('verdict') in _VERDICTS and type(cmp.get('reason')) is str
            and isinstance(cmp.get('squares'), dict)
            and all(cmp['squares'].get(s) in _VERDICTS for s in reader.SQUARES))


class PieceGuard:
    def __init__(self, start_pictures, start_fen, withhold_on_unsure_disturbed=True):
        """start_pictures: [(image, corners)] of the human-reviewed start, or None when no start was reviewed (the
        guard then always withholds). withhold_on_unsure_disturbed (read-only after creation): True (default, the
        stricter choice) = 'cannot tell' on any square passed as `disturbed` to check() withholds; only the value
        False itself turns it off (anything else counts as True). Never raises (other than interrupt-type
        exceptions); a start it cannot use makes every answer withhold.
        Calls on one guard are serialised by a lock. Each call takes its sequence number when it STARTS; an outcome is
        valid only if no later call on the same guard has started, so an older call that finishes after a newer one
        has started reads as withhold."""
        self._lock = threading.Lock()                      # one call at a time: reading, judging and the baseline
        self._seq_lock = threading.Lock()                  # sequence numbers are taken at entry, before waiting
        self._strict = withhold_on_unsure_disturbed is not False
        self._previous = None
        self._cal = None
        self._baseline = None
        self._seq = 0
        self._owner = None                                 # id of the thread inside a call (re-entrancy check)
        self._nameable = frozenset()                       # piece letters the reader can name in this game
        self._start_problem = None
        if start_pictures is None:
            self._start_problem = 'no-start'
            return
        try:
            cal = reader.calibrate(start_pictures, start_fen)
            if not isinstance(cal, dict) or cal.get('state') != 'ok':
                self._start_problem = 'start-refused'
            else:
                self._baseline = _believed(reader.placement(start_fen))
                self._nameable = _nameable(cal)
                self._cal = cal
        except Exception as e:  # fail closed
            self._start_problem = f'start-refused: {type(e).__name__}'

    @property
    def withhold_on_unsure_disturbed(self):
        return self._strict

    def _enter(self):
        with self._seq_lock:
            self._seq += 1
            return self._seq

    def check(self, image, corners, believed, disturbed=()):
        """One settled picture -> GuardOutcome. believed: the FULL believed position {square: piece}.
        disturbed: squares the caller considers changed since the last confirmed state (e.g. the last move); with
        the strict setting 'cannot tell' on any of them withholds. Never moves the baseline."""
        seq = self._enter()
        if self._reentrant():
            return self._withhold(_REENTRANT)
        with self._serial():
            return self._check(image, corners, believed, disturbed, seq)[0]

    def rebaseline_after_human_review(self, image, corners, reviewed_position):
        """Call ONLY after a person has reviewed the full position on the board. Sets the baseline for
        check_after_move to reviewed_position when a full check of it on this picture answers no objection AND the
        picture gives real evidence for it: the reader must name, consistently with reviewed_position, at least
        REBASELINE_NAMED_SHARE of the pieces it is able to name (pawns, knights, bishops and rooks of the kinds it
        learned well enough at the start), and at least one, and no square may be 'unconfirmed' by the reader (its
        previous picture showed another kind there: the picture changed, so a changed square could hide a piece the
        reviewed position lacks; call it on a picture the guard has just seen). On any objection, refused reading,
        invalid position, too little evidence (for example degenerate corners, or the first picture of a new guard,
        which the reader never confirms) or an unconfirmed square it withholds and leaves the baseline unchanged.
        Calling it automatically after a withhold defeats the guard: the guard cannot see wrong kings or queens, or
        pieces invented on empty squares (the reader never names kings or queens and never says "empty"), so an
        unreviewed position with such errors is accepted and becomes the base for every later move."""
        seq = self._enter()
        if self._reentrant():
            return self._withhold(_REENTRANT)
        with self._serial():
            out, bel = self._check(image, corners, reviewed_position, (), seq, need_evidence=True)
            with self._seq_lock:                           # decided atomically with the sequence (see check_after_move)
                if bel is not None and not out.must_withhold():
                    self._baseline = bel
            return out

    def _check(self, image, corners, believed, disturbed, seq, need_evidence=False):
        try:
            squares = _squares(disturbed, 'disturbed')
            bel = _believed(believed)
        except _Malformed as e:
            return self._run(image, corners, None, (), seq, str(e)), None
        except Exception as e:  # fail closed (hostile input)
            return self._run(image, corners, None, (), seq, f'malformed-input: {type(e).__name__}'), None
        return self._run(image, corners, bel, squares if self._strict else (), seq, need_evidence=need_evidence), bel

    def check_after_move(self, image, corners, believed_before, believed_after):
        """One settled picture after a move -> GuardOutcome. believed_before / believed_after: the FULL believed
        positions before and after the move; both are validated and copied before anything else, and the copy of
        believed_before must equal the guard's baseline. Accepts only the shape of one real move (see the module
        docstring); 'cannot tell' on the arrival square withholds (whatever the strict setting). The baseline moves
        to believed_after only on a no-objection answer, at the moment that answer is decided (inside the call) and
        only if no later call on this guard has started by then. If a later call starts after that moment, the
        caller reads withhold (the outcome is stale) although the baseline has already moved to believed_after.
        That fails safe: believed_after was checked with no objection on this picture; repeating the same move then
        withholds ('before-differs-from-baseline') until a re-baseline after human review, and a next move from
        believed_after is checked as usual, so the stale case can only add withholds, never remove one."""
        seq = self._enter()
        if self._reentrant():
            return self._withhold(_REENTRANT)
        with self._serial():
            try:
                before, after = _believed(believed_before), _believed(believed_after)
                if self._baseline is not None and before != self._baseline:
                    raise _Malformed('before-differs-from-baseline')
                arrival = _move_arrival(before, after)
            except _Malformed as e:
                return self._run(image, corners, None, (), seq, str(e))
            except Exception as e:  # fail closed (hostile input)
                return self._run(image, corners, None, (), seq, f'malformed-input: {type(e).__name__}')
            out = self._run(image, corners, after, (arrival,), seq)
            with self._seq_lock:                           # no later call can take a sequence number in between
                if not out.must_withhold():
                    self._baseline = after
            return out

    def _reentrant(self):
        """True when this thread is already inside a call on this guard (a call made from inside a call, for example
        from a hook in the reader). Only the thread holding the lock writes its own id into _owner, so comparing
        with this thread's id needs no lock."""
        return self._owner == threading.get_ident()

    @contextlib.contextmanager
    def _serial(self):
        with self._lock:
            self._owner = threading.get_ident()
            try:
                yield
            finally:
                self._owner = None

    def _run(self, image, corners, bel, unsure_squares, seq, problem=None, need_evidence=False):
        """Read the picture (always, so the previous reading stays in step), then judge it. bel and unsure_squares
        are the entry copies; the caller's objects are not read again."""
        if self._cal is None:
            return self._withhold(self._start_problem or 'no-start')
        previous, self._previous = self._previous, None    # a failed read leaves nothing to confirm the next picture
        try:
            result = reader.read(image, corners, self._cal, previous=previous)
        except Exception as e:  # fail closed
            return self._withhold(f'reader-error: {type(e).__name__}')
        self._previous = result
        if problem:
            return self._withhold(problem)
        try:
            return self._judge(result, bel, unsure_squares, seq, need_evidence)
        except Exception as e:  # fail closed
            return self._withhold(f'guard-error: {type(e).__name__}')

    def _withhold(self, *reasons):
        return GuardOutcome(WITHHOLD, tuple(reasons))

    def _judge(self, result, bel, unsure_squares, seq, need_evidence=False):
        cmp = reader.compare(result, dict(bel))
        if not _compare_ok(cmp):
            return self._withhold('malformed-compare')
        verdict, why = cmp['verdict'], cmp['reason']
        if verdict == 'objection':
            objecting = ['objection: ' + s for s in reader.SQUARES if cmp['squares'][s] == 'objection']
            return self._withhold(*(objecting or ['objection']))
        if any(why.startswith(r) for r in _JUDGE_FAILED):
            return self._withhold(why)
        if verdict not in ('consistent', 'cannot-tell'):
            return self._withhold(f'unexpected-verdict: {verdict}')
        unsure = [s for s in unsure_squares if cmp['squares'][s] != 'consistent']
        if unsure:
            return self._withhold(*('cannot-tell on disturbed square: ' + s for s in unsure))
        if need_evidence:                                  # the picture must show the position, not just fail to object
            nameable = [s for s, p in bel.items() if p in self._nameable]
            named = sum(cmp['squares'][s] == 'consistent' for s in nameable)
            if named == 0 or named < REBASELINE_NAMED_SHARE * len(nameable):
                return self._withhold(f'too-little-evidence: {named} of {len(nameable)} nameable pieces named')
            # a square whose piece the previous picture did not show (the reader's 'unconfirmed') means the picture
            # changed: a changed square is 'cannot tell', so it could hide a piece the reviewed position lacks
            changed = [s for s in reader.SQUARES if result[s].get('reason') == _UNCONFIRMED]
            if changed:
                return self._withhold(*('unconfirmed square (picture changed since the previous one): ' + s
                                        for s in changed))
        return GuardOutcome(NO_OBJECTION, _genuine=_GENUINE, _issuer=self, _seq=seq)
