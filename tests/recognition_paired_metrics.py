#!/usr/bin/env python3
import copy
import json
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/recognition'))
from paired_metrics import SQUARES, summarize


def fixture(name='one', timestamp=0, group='source'):
    return {'id': name, 'group': group, 'timestampSeconds': timestamp,
            'truth': {square: {'label': '.', 'occupancy': 'empty'} for square in SQUARES},
            'squares': {square: {'rawLabel': '.', 'label': 'empty', 'confidence': .99}
                        for square in SQUARES}}


class PairedMetricTests(unittest.TestCase):
    def test_geometry_abstention_retains_denominators_and_no_fabricated_raw_predictions(self):
        frame = fixture()
        frame['truth']['a8'] = {'label': 'P', 'occupancy': 'occupied'}
        frame['squares'] = None
        result = summarize([frame])['totals']
        self.assertEqual(result['geometryAbstentionFrames'], 1)
        self.assertEqual(result['knownLabels'], 64)
        self.assertEqual(result['knownOccupiedTypes'], 1)
        self.assertEqual(result['acceptedCorrectKnownLabelYield'], 0)
        self.assertEqual(result['acceptedCorrectOccupiedTypeYield'], 0)
        self.assertEqual(result['acceptedPredictionCoverage'], 0)
        self.assertIsNone(result['rawKnownLabelAccuracy'])
        self.assertIsNone(result['rawOccupiedTypeAccuracy'])
        self.assertIsNone(result['acceptedWrongKnownLabelRate'])
        self.assertIsNone(result['rawExactBoardAccuracy'])
        self.assertEqual(result['rawExactBoardYield'], 0)
        self.assertEqual(result['confusion'], {})
        self.assertTrue(all(bucket['count'] == 0 and bucket['meanScore'] is None
                            for bucket in result['scoreBins']['allKnown']))

    def test_pooled_denominators_separate_conditional_accuracy_from_yield(self):
        present, absent = fixture(), fixture('two', 4)
        absent['squares'] = None
        result = summarize([present, absent])['totals']
        self.assertEqual(result['knownLabels'], 128)
        self.assertEqual(result['predictedKnownLabels'], 64)
        self.assertEqual(result['rawKnownLabelAccuracy'], 1)
        self.assertEqual(result['acceptedCorrectKnownLabelYield'], .5)
        self.assertEqual(result['acceptedPredictionCoverage'], .5)
        self.assertEqual(result['rawExactBoardAccuracy'], 1)
        self.assertEqual(result['acceptedExactBoardYield'], .5)

    def test_partial_truth_never_becomes_exact_or_empty(self):
        frame = fixture()
        frame['truth']['a8'] = {'label': 'unknown', 'occupancy': 'unknown'}
        frame['truth']['b8'] = {'label': 'unknown', 'occupancy': 'occupied'}
        result = summarize([frame])['totals']
        self.assertEqual(result['knownLabels'], 62)
        self.assertEqual(result['knownOccupancy'], 63)
        self.assertEqual(result['acceptedWrongKnownLabels'], 0)
        self.assertEqual(result['acceptedFalseEmptyOnOccupied'], 1)
        self.assertEqual(result['acceptedUnknownOccupancy'], 1)
        self.assertEqual(result['unknownOccupancyAssertionRate'], 1)
        self.assertEqual(result['fullyKnownFrames'], 0)
        self.assertIsNone(result['rawExactBoardAccuracy'])
        self.assertIsNone(result['acceptedExactBoardYield'])
        self.assertEqual(sum(result['confusion']['.'].values()), 62)

    def test_confusion_preserves_piece_color_and_type_and_accepted_false_empty(self):
        frame = fixture()
        for square, truth, raw in [('a8', 'P', 'p'), ('b8', 'N', 'B'), ('c8', 'Q', '.')]:
            frame['truth'][square] = {'label': truth, 'occupancy': 'occupied'}
            frame['squares'][square] = {'rawLabel': raw, 'label': 'empty' if raw == '.' else raw, 'confidence': .99}
        result = summarize([frame])['totals']
        self.assertEqual(result['confusion']['P'], {'p': 1})
        self.assertEqual(result['confusion']['N'], {'B': 1})
        self.assertEqual(result['confusion']['Q'], {'.': 1})
        self.assertEqual(result['rawOccupiedTypeAccuracy'], 0)
        self.assertEqual(result['acceptedWrongOccupiedTypeRate'], 1)
        self.assertEqual(result['acceptedTrueOccupied'], 2)
        self.assertEqual(result['acceptedFalseEmptyOnOccupied'], 1)

    def test_score_bin_edges_and_means_exclude_unknown_truth(self):
        frame = fixture()
        for index, confidence in enumerate([0, .5, .8, .95, 1]):
            square = SQUARES[index]
            frame['truth'][square] = {'label': 'P', 'occupancy': 'occupied'}
            frame['squares'][square] = {'rawLabel': 'P', 'label': 'unknown', 'confidence': confidence}
        for square in SQUARES[5:]:
            frame['truth'][square] = {'label': 'unknown', 'occupancy': 'unknown'}
        result = summarize([frame])['totals']
        bins = result['scoreBins']['allKnown']
        self.assertEqual([bucket['count'] for bucket in bins], [1, 1, 1, 2])
        self.assertEqual([bucket['correct'] for bucket in bins], [1, 1, 1, 2])
        self.assertEqual([bucket['meanScore'] for bucket in bins], [0, .5, .8, .975])
        self.assertEqual(bins, result['scoreBins']['knownOccupied'])
        self.assertEqual(result['acceptedKnownLabels'], 0)
        self.assertEqual(result['correctOccupiedTypes'], 5)
        json.dumps(result, allow_nan=False)

    def test_exact_board_requires_full_truth_and_acceptance(self):
        frame = fixture()
        frame['squares']['a8']['label'] = 'unknown'
        result = summarize([frame])['totals']
        self.assertEqual(result['rawExactBoards'], 1)
        self.assertEqual(result['acceptedExactBoards'], 0)
        self.assertEqual(result['rawExactBoardAccuracy'], 1)
        self.assertEqual(result['acceptedExactBoardYield'], 0)

    def test_adjacent_temporal_comparison_uses_same_source_known_unchanged_truth_only(self):
        first, second, third = fixture('first', 0), fixture('second', 4), fixture('third', 12)
        second['truth']['a8'] = {'label': 'unknown', 'occupancy': 'unknown'}
        second['truth']['b8'] = {'label': 'P', 'occupancy': 'occupied'}
        second['squares']['c8'] = {'rawLabel': 'Q', 'label': 'Q', 'confidence': .99}
        second['squares']['d8'] = {'rawLabel': 'R', 'label': 'unknown', 'confidence': .4}
        third['squares'] = None
        other = fixture('different-source', 2, 'other')
        temporal = summarize([third, other, second, first])['temporal']
        self.assertEqual(temporal['totals']['pairs'], 2)
        pair = temporal['pairs'][0]
        self.assertEqual((pair['beforeId'], pair['afterId'], pair['elapsedSeconds']), ('first', 'second', 4))
        self.assertEqual(pair['unknownTruthSquares'], 1)
        self.assertEqual(pair['changedTruthSquares'], 1)
        self.assertEqual(pair['comparedKnownUnchangedSquares'], 62)
        self.assertEqual(pair['rawLabelDisagreements'], 2)
        self.assertEqual(pair['acceptedLabelDisagreements'], 1)
        self.assertEqual(temporal['pairs'][1]['elapsedSeconds'], 8)
        self.assertEqual(temporal['pairs'][1]['comparedKnownUnchangedSquares'], 0)
        self.assertEqual(temporal['pairs'][1]['unavailablePredictionSquares'], 62)

    def test_malformed_predictions_and_contradictory_truth_rejected(self):
        mutations = [
            lambda frame: frame['truth'].pop('a8'),
            lambda frame: frame['squares'].pop('a8'),
            lambda frame: frame['truth'].update({'z9': frame['truth'].pop('a8')}),
            lambda frame: frame['truth']['a8'].update(label='P'),
            lambda frame: frame['truth']['a8'].update(label='X'),
            lambda frame: frame['truth']['a8'].update(occupancy='occluded'),
            lambda frame: frame['squares']['a8'].update(rawLabel='unknown'),
            lambda frame: frame['squares']['a8'].update(label='Q'),
            lambda frame: frame['squares']['a8'].update(confidence=math.nan),
            lambda frame: frame['squares']['a8'].update(confidence=math.inf),
            lambda frame: frame['squares']['a8'].update(confidence=-.1),
            lambda frame: frame['squares']['a8'].update(confidence=1.01),
            lambda frame: frame['squares']['a8'].update(confidence=True),
            lambda frame: frame.update(timestampSeconds=math.nan),
            lambda frame: frame.update(timestampSeconds=-1),
            lambda frame: frame.update(group=''),
            lambda frame: frame.pop('squares'),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                frame = fixture()
                mutate(frame)
                with self.assertRaises(ValueError):
                    summarize([frame])
        with self.assertRaises(ValueError):
            summarize([fixture(), fixture()])
        with self.assertRaises(ValueError):
            summarize(None)

    def test_empty_input_and_unknown_empty_truth_do_not_fabricate_labels(self):
        result = summarize([])
        self.assertEqual(result['totals']['frames'], 0)
        self.assertIsNone(result['totals']['acceptedPredictionCoverage'])
        frame = fixture()
        frame['truth']['a8'] = {'label': 'unknown', 'occupancy': 'empty'}
        saved = copy.deepcopy(frame)
        result = summarize([frame])['totals']
        self.assertEqual(result['knownLabels'], 63)
        self.assertEqual(result['knownOccupancy'], 64)
        self.assertEqual(frame, saved)


if __name__ == '__main__':
    unittest.main()
