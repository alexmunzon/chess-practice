#!/usr/bin/env python3
import sys,unittest
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/recognition'))
from evaluate_video_controls import box
from photo_pieces import perspective
class ControlTests(unittest.TestCase):
 def test_fixed_margin(self):self.assertEqual(box([[100,200],[300,200],[300,400],[100,400]],(1000,1000)),[80,180,320,420])
 def test_clip(self):self.assertEqual(box([[0,0],[100,0],[100,100],[0,100]],(100,100)),[0,0,100,100])
 def test_canonical_corner_mapping(self):
  corners=[[30,10],[30,40],[10,40],[10,10]];h=perspective(corners)
  for uv,expected in zip([(0,0),(1,0),(1,1),(0,1)],corners):
   p=h@np.array([*uv,1]);np.testing.assert_allclose(p[:2]/p[2],expected)
 def test_ccw_rotation_puts_source_top_right_at_output_top_left(self):
  a=np.array([[1,2],[3,4]],np.uint8);out=np.asarray(Image.fromarray(a).transpose(Image.Transpose.ROTATE_90));self.assertEqual(out.tolist(),[[2,4],[1,3]])
if __name__=='__main__':unittest.main()
