#!/usr/bin/env python3
"""Frozen, source-separated real-photo recognition evaluation. Ground truth never enters automatic inference."""
import argparse,hashlib,importlib.util,json
from pathlib import Path
import numpy as np
from photo_pieces import Classifier
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('calibration',ROOT/'scripts/vision/calibrate.py');cal=importlib.util.module_from_spec(spec);spec.loader.exec_module(cal)
def expand(placement):
 values=[]
 for c in placement:
  if c=='/':continue
  values.extend(['.']*int(c) if c.isdigit() else [c])
 if len(values)!=64:raise ValueError('Ground truth requires 64 squares')
 return values
def score(result,truth):
 gt=expand(truth);squares=[result['squares']['abcdefgh'[i%8]+str(8-i//8)] for i in range(64)]
 raw=[x['rawLabel'] for x in squares];accepted=[i for i,x in enumerate(squares) if x['label']!='unknown'];correct=sum(a==b for a,b in zip(raw,gt))
 return {'rawCorrectSquares':correct,'totalSquares':64,'rawCorrectOccupiedSquares':sum(raw[i]==gt[i] for i in range(64) if gt[i]!='.'),'occupiedSquares':sum(x!='.' for x in gt),'acceptedSquares':len(accepted),'acceptedCorrectSquares':sum(raw[i]==gt[i] for i in accepted),'acceptedWrongSquares':sum(raw[i]!=gt[i] for i in accepted),'unknownSquares':64-len(accepted),'falseOccupiedSquares':sum(raw[i]!='.' and gt[i]=='.' for i in range(64)),'missedOccupiedSquares':sum(raw[i]=='.' and gt[i]!='.' for i in range(64)),'rawExactBoard':correct==64,'acceptedExactBoard':correct==64 and len(accepted)==64,'errors':[{'square':'abcdefgh'[i%8]+str(8-i//8),'truth':gt[i],'prediction':raw[i],'score':squares[i]['confidence'],'accepted':i in accepted} for i in range(64) if raw[i]!=gt[i]]}
def evaluate(manifest,data_root,model_dir,detector,out):
 doc=json.loads(Path(manifest).read_text());out=Path(out);out.mkdir(parents=True,exist_ok=True);classifier=Classifier(model_dir);results=[]
 for item in doc['records']:
  source=Path(data_root)/item['image'];sha=hashlib.sha256(source.read_bytes()).hexdigest()
  if sha!=item['sourceSha256']:raise ValueError('Source hash mismatch')
  # Manual calibration is a separately named component-control experiment.
  manual=dict(item,mode='manual-ground-truth-corners-control',humanConfirmed=True)
  for mode in ['automatic','manual-control']:
   target=out/item['id']/mode;target.mkdir(parents=True,exist_ok=True)
   geometry=cal.calibrate(source,target,detector=detector,orientation=item['orientation']) if mode=='automatic' else manual
   record={'id':item['id'],'split':item['split'],'group':item['group'],'calibrationMode':mode,'sourceSha256':sha,'geometryDetected':bool(geometry.get('corners')),'modelInferenceRan':False}
   if geometry.get('corners'):
    errors=np.linalg.norm(np.asarray(geometry['corners'])-item['corners'],axis=1);record['meanCornerErrorPixels']=float(errors.mean())
    prediction=classifier.recognize(source,geometry,doc['threshold']);(target/'prediction.json').write_text(json.dumps(prediction,indent=2)+'\n');record.update(modelInferenceRan=True,elapsedMs=prediction['elapsedMs'],metrics=score(prediction,item['placement']))
   results.append(record)
 report={'schemaVersion':1,'manifestSha256':hashlib.sha256(Path(manifest).read_bytes()).hexdigest(),'classifierCodeSha256':hashlib.sha256((ROOT/'scripts/recognition/photo_pieces.py').read_bytes()).hexdigest(),'geometryCodeSha256':hashlib.sha256((ROOT/'scripts/vision/calibrate.py').read_bytes()).hexdigest(),'threshold':doc['threshold'],'results':results,'limitations':['Two held-out photographs are a diagnostic set, not a general accuracy estimate.','Model training provenance is declared by upstream; image non-overlap cannot be exhaustively proven.','Manual-control accuracy is conditional on annotated corners and known orientation.','All positions are initial setups; varied game positions and continuous video remain untested.','Abstention and accepted errors are reported, not hidden in overall square accuracy.']}
 (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');return report
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',required=True);p.add_argument('--data-root',required=True);p.add_argument('--models',required=True);p.add_argument('--detector',required=True);p.add_argument('--output',required=True);a=p.parse_args()
 try:print(json.dumps(evaluate(a.manifest,a.data_root,a.models,a.detector,a.output),indent=2))
 except Exception as e:p.exit(1,f'Evaluation failed: {e}\n')
