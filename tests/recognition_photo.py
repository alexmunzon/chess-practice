#!/usr/bin/env python3
import importlib.util,unittest
from pathlib import Path
import numpy as np
from PIL import Image
spec=importlib.util.spec_from_file_location('photo',Path(__file__).resolve().parents[1]/'scripts/recognition/photo_pieces.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class RecognitionTests(unittest.TestCase):
 def test_shapes_dtype_and_geometry(self):
  im=Image.new('RGB',(800,800),(100,120,140));o,p=m.crops(im,[[200,200],[600,200],[600,600],[200,600]])
  self.assertEqual(o.shape,(64,100,100,3));self.assertEqual(p.shape,(64,200,100,3));np.testing.assert_array_equal(o[0,50,50],[100,120,140]);self.assertEqual(m.tensor(o).shape,(64,3,100,100));self.assertEqual(m.tensor(o).dtype,np.float32)
  np.testing.assert_array_equal(p[0,0,0],[100,120,140]);np.testing.assert_array_equal(p[63,0,0],[0,0,0]);np.testing.assert_array_equal(p[63,-1,0],[100,120,140])
 def test_normalization(self):
  np.testing.assert_allclose(m.tensor(np.zeros((1,1,1,3),np.uint8)).reshape(3),-m.MEAN/m.STD,rtol=1e-6)
 def test_probabilities_finite_shape_and_sum(self):
  p=m.softmax(np.ones((64,12)),12);np.testing.assert_allclose(p.sum(axis=1),1)
  for x in [np.ones((63,12)),np.full((64,12),np.nan)]:
   with self.assertRaises(ValueError):m.softmax(x,12)
 def test_geometry_fail_closed(self):
  for c in [[[0,0]]*4,[[0,0],[100,100],[0,100],[100,0]],[[0,0],[100,0],[100,float('nan')],[0,100]]]:
   with self.assertRaises((ValueError,np.linalg.LinAlgError)):m.perspective(c)
 def test_placement_no_history(self):
  labels='rnbqkbnr'+'p'*8+'.'*32+'P'*8+'RNBQKBNR';self.assertEqual(m.placement(labels),'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR')
  with self.assertRaises(ValueError):m.placement('?'*64)
if __name__=='__main__':unittest.main()
