"""Pure scoring for replayed geometry arms; no image, model, or state inference."""
import math

SQUARES = tuple(f + r for r in '87654321' for f in 'abcdefgh')
LABELS = frozenset('.PNBRQKpnbrqk')
BIN_EDGES = (0.0, 0.5, 0.8, 0.95, 1.0)
COUNT_NAMES = (
    'frames', 'inferenceFrames', 'geometryAbstentionFrames', 'totalSquares',
    'knownLabels', 'knownOccupiedTypes', 'knownOccupancy', 'knownOccupied',
    'knownEmpty', 'unknownLabels', 'unknownOccupancy', 'predictedSquares',
    'predictedKnownLabels', 'predictedKnownOccupiedTypes', 'predictedKnownOccupancy',
    'correctKnownLabels', 'correctOccupiedTypes', 'correctOccupancy',
    'acceptedSquares', 'acceptedKnownLabels', 'acceptedCorrectKnownLabels',
    'acceptedWrongKnownLabels', 'acceptedKnownOccupiedTypes',
    'acceptedCorrectOccupiedTypes', 'acceptedWrongOccupiedTypes',
    'acceptedKnownOccupancy', 'acceptedCorrectOccupancy',
    'acceptedFalseOccupiedOnEmpty', 'acceptedFalseEmptyOnOccupied',
    'acceptedTrueOccupied', 'acceptedUnknownLabels', 'acceptedUnknownOccupancy',
    'predictedUnknownOccupancy', 'fullyKnownFrames', 'predictedFullyKnownFrames',
    'rawExactBoards', 'acceptedExactBoards',
)


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _validate(frame):
    required = {'id', 'group', 'timestampSeconds', 'truth', 'squares'}
    if not isinstance(frame, dict) or not required.issubset(frame):
        raise ValueError('Each frame requires id, group, timestampSeconds, truth and squares')
    if any(not isinstance(frame[k], str) or not frame[k] for k in ('id', 'group')):
        raise ValueError('Frame id and group must be nonempty strings')
    if not _number(frame['timestampSeconds']) or frame['timestampSeconds'] < 0:
        raise ValueError('Frame timestamp must be finite and nonnegative')
    truth, predictions = frame['truth'], frame['squares']
    if not isinstance(truth, dict) or set(truth) != set(SQUARES):
        raise ValueError('Truth requires exactly 64 canonical square keys')
    if predictions is not None and (not isinstance(predictions, dict) or set(predictions) != set(SQUARES)):
        raise ValueError('Predictions require exactly 64 canonical squares, or None for geometry abstention')
    for square in SQUARES:
        cell = truth[square]
        if not isinstance(cell, dict) or not isinstance(cell.get('label'), str) or cell['label'] not in LABELS | {'unknown'}:
            raise ValueError(f'Invalid truth label at {square}')
        occupancy = cell.get('occupancy')
        if occupancy not in ('empty', 'occupied', 'unknown'):
            raise ValueError(f'Invalid truth occupancy at {square}')
        if cell['label'] != 'unknown' and occupancy != ('empty' if cell['label'] == '.' else 'occupied'):
            raise ValueError(f'Contradictory truth label and occupancy at {square}')
        if predictions is None:
            continue
        cell = predictions[square]
        if not isinstance(cell, dict) or not isinstance(cell.get('rawLabel'), str) or cell['rawLabel'] not in LABELS:
            raise ValueError(f'Invalid prediction rawLabel at {square}')
        expected = 'empty' if cell['rawLabel'] == '.' else cell['rawLabel']
        if cell.get('label') not in (expected, 'unknown'):
            raise ValueError(f'Accepted label must match rawLabel at {square}')
        confidence = cell.get('confidence')
        if not _number(confidence) or not 0 <= confidence <= 1:
            raise ValueError(f'Prediction confidence must be finite in [0,1] at {square}')


def _new_metrics():
    return {**dict.fromkeys(COUNT_NAMES, 0), 'confusion': {},
            'scoreBins': {name: [dict(count=0, correct=0, scoreSum=0.0) for _ in range(4)]
                          for name in ('allKnown', 'knownOccupied')}}


def _bin(metrics, name, confidence, correct):
    index = next((i for i in range(3) if confidence < BIN_EDGES[i + 1]), 3)
    bucket = metrics['scoreBins'][name][index]
    bucket['count'] += 1
    bucket['correct'] += int(correct)
    bucket['scoreSum'] += confidence


def _score(frame):
    metrics = _new_metrics()
    predictions = frame['squares']
    metrics.update(frames=1, inferenceFrames=int(predictions is not None),
                   geometryAbstentionFrames=int(predictions is None), totalSquares=64)
    exact, all_accepted = True, True
    for square in SQUARES:
        truth = frame['truth'][square]
        label, occupancy = truth['label'], truth['occupancy']
        known = label != 'unknown'
        known_piece = known and label != '.'
        known_occupancy = occupancy != 'unknown'
        metrics['knownLabels'] += int(known)
        metrics['knownOccupiedTypes'] += int(known_piece)
        metrics['knownOccupancy'] += int(known_occupancy)
        metrics['knownOccupied'] += int(occupancy == 'occupied')
        metrics['knownEmpty'] += int(occupancy == 'empty')
        metrics['unknownLabels'] += int(not known)
        metrics['unknownOccupancy'] += int(not known_occupancy)
        if predictions is None:
            continue
        prediction = predictions[square]
        raw, confidence = prediction['rawLabel'], prediction['confidence']
        accepted = prediction['label'] != 'unknown'
        occupied = raw != '.'
        correct = known and raw == label
        exact = exact and correct
        all_accepted = all_accepted and accepted
        metrics['predictedSquares'] += 1
        metrics['acceptedSquares'] += int(accepted)
        if known:
            metrics['predictedKnownLabels'] += 1
            metrics['correctKnownLabels'] += int(correct)
            metrics['acceptedKnownLabels'] += int(accepted)
            metrics['acceptedCorrectKnownLabels'] += int(accepted and correct)
            metrics['acceptedWrongKnownLabels'] += int(accepted and not correct)
            row = metrics['confusion'].setdefault(label, {})
            row[raw] = row.get(raw, 0) + 1
            _bin(metrics, 'allKnown', confidence, correct)
            if known_piece:
                metrics['predictedKnownOccupiedTypes'] += 1
                metrics['correctOccupiedTypes'] += int(correct)
                metrics['acceptedKnownOccupiedTypes'] += int(accepted)
                metrics['acceptedCorrectOccupiedTypes'] += int(accepted and correct)
                metrics['acceptedWrongOccupiedTypes'] += int(accepted and not correct)
                _bin(metrics, 'knownOccupied', confidence, correct)
        else:
            metrics['acceptedUnknownLabels'] += int(accepted)
        if known_occupancy:
            correct_occupancy = occupied == (occupancy == 'occupied')
            metrics['predictedKnownOccupancy'] += 1
            metrics['correctOccupancy'] += int(correct_occupancy)
            metrics['acceptedKnownOccupancy'] += int(accepted)
            metrics['acceptedCorrectOccupancy'] += int(accepted and correct_occupancy)
            metrics['acceptedFalseOccupiedOnEmpty'] += int(accepted and occupied and occupancy == 'empty')
            metrics['acceptedFalseEmptyOnOccupied'] += int(accepted and not occupied and occupancy == 'occupied')
            metrics['acceptedTrueOccupied'] += int(accepted and occupied and occupancy == 'occupied')
        else:
            metrics['predictedUnknownOccupancy'] += 1
            metrics['acceptedUnknownOccupancy'] += int(accepted)
    fully_known = metrics['knownLabels'] == 64
    metrics['fullyKnownFrames'] = int(fully_known)
    metrics['predictedFullyKnownFrames'] = int(fully_known and predictions is not None)
    metrics['rawExactBoards'] = int(fully_known and predictions is not None and exact)
    metrics['acceptedExactBoards'] = int(fully_known and predictions is not None and exact and all_accepted)
    return metrics


def _merge(total, item):
    for name in COUNT_NAMES:
        total[name] += item[name]
    for label, row in item['confusion'].items():
        target = total['confusion'].setdefault(label, {})
        for raw, count in row.items():
            target[raw] = target.get(raw, 0) + count
    for name, buckets in item['scoreBins'].items():
        for target, bucket in zip(total['scoreBins'][name], buckets):
            for key in ('count', 'correct', 'scoreSum'):
                target[key] += bucket[key]


def _finish(metrics):
    rates = {
        'rawKnownLabelAccuracy': ('correctKnownLabels', 'predictedKnownLabels'),
        'rawOccupiedTypeAccuracy': ('correctOccupiedTypes', 'predictedKnownOccupiedTypes'),
        'rawOccupancyAccuracy': ('correctOccupancy', 'predictedKnownOccupancy'),
        'acceptedCorrectKnownLabelYield': ('acceptedCorrectKnownLabels', 'knownLabels'),
        'acceptedCorrectOccupiedTypeYield': ('acceptedCorrectOccupiedTypes', 'knownOccupiedTypes'),
        'acceptedCorrectOccupancyYield': ('acceptedCorrectOccupancy', 'knownOccupancy'),
        'acceptedWrongKnownLabelRate': ('acceptedWrongKnownLabels', 'acceptedKnownLabels'),
        'acceptedWrongOccupiedTypeRate': ('acceptedWrongOccupiedTypes', 'acceptedKnownOccupiedTypes'),
        'acceptedPredictionCoverage': ('acceptedSquares', 'totalSquares'),
        'acceptedKnownLabelCoverage': ('acceptedKnownLabels', 'knownLabels'),
        'acceptedKnownOccupiedTypeCoverage': ('acceptedKnownOccupiedTypes', 'knownOccupiedTypes'),
        'unknownOccupancyAssertionRate': ('acceptedUnknownOccupancy', 'unknownOccupancy'),
        'rawExactBoardAccuracy': ('rawExactBoards', 'predictedFullyKnownFrames'),
        'rawExactBoardYield': ('rawExactBoards', 'fullyKnownFrames'),
        'acceptedExactBoardYield': ('acceptedExactBoards', 'fullyKnownFrames'),
    }
    metrics.update({name: ratio(metrics[numerator], metrics[denominator])
                    for name, (numerator, denominator) in rates.items()})
    for buckets in metrics['scoreBins'].values():
        for index, bucket in enumerate(buckets):
            bucket.update(lower=BIN_EDGES[index], upper=BIN_EDGES[index + 1],
                          upperInclusive=index == 3,
                          meanScore=ratio(bucket.pop('scoreSum'), bucket['count']),
                          rawAccuracy=ratio(bucket['correct'], bucket['count']))
    return metrics


def _temporal(frames):
    groups = {}
    for frame in frames:
        groups.setdefault(frame['group'], []).append(frame)
    counts = dict(pairs=0, unknownTruthSquares=0, changedTruthSquares=0,
                  knownUnchangedSquares=0, unavailablePredictionSquares=0,
                  comparedKnownUnchangedSquares=0, rawLabelDisagreements=0,
                  bothAcceptedComparisons=0, acceptedLabelDisagreements=0)
    pairs = []
    for group, members in sorted(groups.items()):
        ordered = sorted(members, key=lambda frame: (frame['timestampSeconds'], frame['id']))
        for before, after in zip(ordered, ordered[1:]):
            pair = dict.fromkeys(counts, 0)
            pair.update(pairs=1, group=group, beforeId=before['id'], afterId=after['id'],
                        elapsedSeconds=after['timestampSeconds'] - before['timestampSeconds'])
            for square in SQUARES:
                first, second = before['truth'][square]['label'], after['truth'][square]['label']
                if 'unknown' in (first, second):
                    pair['unknownTruthSquares'] += 1
                elif first != second:
                    pair['changedTruthSquares'] += 1
                else:
                    pair['knownUnchangedSquares'] += 1
                    if before['squares'] is None or after['squares'] is None:
                        pair['unavailablePredictionSquares'] += 1
                        continue
                    first, second = before['squares'][square], after['squares'][square]
                    disagree = first['rawLabel'] != second['rawLabel']
                    pair['comparedKnownUnchangedSquares'] += 1
                    pair['rawLabelDisagreements'] += int(disagree)
                    if first['label'] != 'unknown' and second['label'] != 'unknown':
                        pair['bothAcceptedComparisons'] += 1
                        pair['acceptedLabelDisagreements'] += int(disagree)
            for key in counts:
                counts[key] += pair[key]
            pairs.append(pair)
    return {'totals': counts, 'pairs': pairs,
            'meaning': 'Adjacent sampled frames within a source; only unchanged known truth is compared. Gaps may hide moves. This is not legality, move tracking, or uninterrupted temporal stability.'}


def summarize(frames):
    """Score one arm. None predictions retain truth denominators as abstention.

    Prediction ``label`` controls acceptance; the caller validates its threshold
    and provenance. Score bins are descriptive, not calibrated probabilities.
    Unknown truth is never filled from occupancy, other frames, or chess rules.
    """
    if not isinstance(frames, (list, tuple)):
        raise ValueError('Frames must be a list or tuple')
    seen = set()
    for frame in frames:
        _validate(frame)
        if frame['id'] in seen:
            raise ValueError('Duplicate frame id')
        seen.add(frame['id'])
    totals, per_frame = _new_metrics(), []
    for frame in frames:
        metrics = _score(frame)
        _merge(totals, metrics)
        per_frame.append({key: frame[key] for key in ('id', 'group', 'timestampSeconds')} |
                         {'metrics': _finish(metrics)})
    return {'schemaVersion': 1, 'sourceGroups': len({frame['group'] for frame in frames}),
            'totals': _finish(totals), 'perFrame': per_frame, 'temporal': _temporal(frames),
            'limitations': [
                'Raw accuracy is conditional on available predictions; accepted-correct yields retain geometry abstentions in all-frame denominators.',
                'Unknown truth is unscored. Assertions on unknown occupancy quantify certainty, not correctness or error.',
                'Fixed score bins describe uncalibrated scores; they do not fit or tune a threshold.',
                'Partial labels cannot establish an exact board, FEN, historical state or legal moves.',
                'This scorer establishes no held-out provenance, independent-source count beyond supplied group labels, or hardware validity.',
            ]}
