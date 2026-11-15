#!/usr/bin/env python3
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/recognition'))
from evaluate_video import score
KEYS=[f+r for r in '87654321' for f in 'abcdefgh']
class PartialScoreTests(unittest.TestCase):
 def fixture(self):
  return ({k:{'rawLabel':'.','label':'empty','confidence':.99} for k in KEYS},{k:{'label':'.','occupancy':'empty'} for k in KEYS})
 def test_unknown_is_never_empty_truth(self):
  p,t=self.fixture();t['a8']={'label':'unknown','occupancy':'unknown'};r=score(p,t)
  self.assertEqual(r['knownLabels'],63);self.assertEqual(r['correctKnownLabels'],63);self.assertEqual(r['unknownOccupancy'],1);self.assertEqual(r['acceptedUnknownOccupancy'],1);self.assertIsNone(r['exactBoardAccuracy'])
 def test_unknown_type_known_occupancy(self):
  p,t=self.fixture();t['a8']={'label':'unknown','occupancy':'occupied'};p['a8']={'rawLabel':'q','label':'q','confidence':.99};r=score(p,t)
  self.assertEqual(r['knownOccupiedTypes'],0);self.assertEqual(r['detectedOccupied'],1);self.assertEqual(r['correctOccupancy'],64);self.assertEqual(r['acceptedWrongKnownLabels'],0)
 def test_rejected_wrong_does_not_count_as_accepted_wrong(self):
  p,t=self.fixture();t['a8']={'label':'P','occupancy':'occupied'};p['a8']['label']='unknown';r=score(p,t)
  self.assertEqual(r['correctOccupiedTypes'],0);self.assertEqual(r['acceptedOccupiedTypes'],0);self.assertEqual(r['acceptedWrongKnownLabels'],0);self.assertEqual(r['knownOccupiedTypes'],1)
 def test_accepted_wrong_and_empty_false_positive(self):
  p,t=self.fixture();p['a8']={'rawLabel':'Q','label':'Q','confidence':.99};r=score(p,t)
  self.assertEqual(r['acceptedWrongKnownLabels'],1);self.assertEqual(r['acceptedFalseOccupiedOnEmpty'],1);self.assertEqual(r['acceptedWrongRate'],1/64)
 def test_missing_square_rejected(self):
  p,t=self.fixture();del p['a8']
  with self.assertRaises(ValueError):score(p,t)
if __name__=='__main__':unittest.main()
