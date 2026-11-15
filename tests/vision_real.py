#!/usr/bin/env python3
"""Evaluate frozen automatic calibration against separately supplied annotations.

Annotations never enter detector arguments. Failure/abstention is a result,
not a reason to silently switch to the ground-truth manual fallback.
"""
import argparse, hashlib, importlib.util, json
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('calibrate',ROOT/'scripts/vision/calibrate.py')
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--image',required=True);p.add_argument('--annotation',required=True)
p.add_argument('--detector',required=True);p.add_argument('--output',required=True)
a=p.parse_args()
annotation=json.loads(Path(a.annotation).read_text())
sha=hashlib.sha256(Path(a.image).read_bytes()).hexdigest()
if sha!=annotation['sourceSha256']: p.error('Annotation belongs to a different image')
report=m.calibrate(a.image,a.output,detector=a.detector)
if report['imageSize']!=annotation['imageSize']: p.error('Annotation dimensions differ from oriented image dimensions')
result={'sourceSha256':sha,'algorithmSha256':hashlib.sha256((ROOT/'scripts/vision/calibrate.py').read_bytes()).hexdigest(),'split':annotation['split'],'status':report['status'],'annotationUncertaintyPixels':annotation.get('estimatedAnnotationUncertaintyPixels'),'detected':bool(report['squares']),'prediction':report.get('corners'),'meanCornerErrorPixels':None,'maxCornerErrorPixels':None}
if report['squares']:
    delta=np.linalg.norm(np.asarray(report['corners'])-annotation['manualCorners'],axis=1)
    result.update(meanCornerErrorPixels=float(delta.mean()),maxCornerErrorPixels=float(delta.max()))
(Path(a.output)/'evaluation.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
