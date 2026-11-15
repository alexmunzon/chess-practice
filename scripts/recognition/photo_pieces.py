#!/usr/bin/env python3
"""Local experimental real-photo classifier. Calibration and complete game state remain human reviewed."""
import argparse,hashlib,json,time
from pathlib import Path
import numpy as np
from PIL import Image,ImageOps

# Compatible crop geometry from chesscog/CrispChess (MIT); see MODEL_NOTICES.md.
CLASSES='bknpqrBKNPQR'; MEAN=np.array([.485,.456,.406],np.float32); STD=np.array([.229,.224,.225],np.float32)
MODEL_HASHES={'board_photo_occupancy.onnx':'dcafa86708036f1c50d2471bcfef838a3973e63bc6e3eef08dd3adccf6e0067d','board_photo_pieces.onnx':'79f7833e4fd802eb10de4d2765bb243ec51c40bb5097989af9ff4db789f2a8af'}
def perspective(corners):
 p=np.asarray(corners,float)
 if p.shape!=(4,2) or not np.isfinite(p).all():raise ValueError('Four finite image-order corners required')
 edges=np.roll(p,-1,axis=0)-p
 if not (edges[:,0]*np.roll(edges[:,1],-1)-edges[:,1]*np.roll(edges[:,0],-1)>1).all():raise ValueError('Convex clockwise corners required')
 rows=[];rhs=[]
 for (u,v),(x,y) in zip([(0,0),(1,0),(1,1),(0,1)],p):rows += [[u,v,1,0,0,0,-u*x,-v*x],[0,0,0,u,v,1,-u*y,-v*y]];rhs += [x,y]
 return np.append(np.linalg.solve(rows,rhs),1).reshape(3,3)
def warp(image,corners,margin,size):
 h=perspective(corners)@np.array([[1/400,0,-margin/400],[0,1/400,-margin/400],[0,0,1]])
 h/=h[2,2]
 return np.asarray(image.transform((size,size),Image.Transform.PERSPECTIVE,tuple(h.flatten()[:8]),Image.Resampling.BILINEAR,fillcolor=(0,0,0)))
def crops(image,corners):
 occupancy=warp(image,corners,50,500);pieces=warp(image,corners,200,800);oc=[];pc=[]
 for r in range(8):
  for c in range(8):
   oc.append(occupancy[int(50*(r+.5)):int(50*(r+2.5)),int(50*(c+.5)):int(50*(c+2.5))])
   hi=1+2*(7-r)/7;left=0 if c>=4 else .25+.75*(3-c)/3;right=0 if c<4 else .25+.75*(c-4)/3
   x1,x2=int(200+50*(c-left)),int(200+50*(c+1+right));y1,y2=int(200+50*(r-hi)),int(200+50*(r+1))
   patch=pieces[y1:y2,x1:x2];patch=patch[:,::-1] if c<4 else patch
   out=np.zeros((200,100,3),np.uint8);out[200-(y2-y1):,:x2-x1]=patch;pc.append(out)
 return np.array(oc),np.array(pc)
def tensor(c):return np.ascontiguousarray(((c.astype(np.float32)/255-MEAN)/STD).transpose(0,3,1,2))
def softmax(logits,columns):
 logits=np.asarray(logits)
 if logits.shape!=(64,columns) or not np.isfinite(logits).all():raise ValueError('Unexpected or non-finite model output')
 z=np.exp(logits-logits.max(axis=1,keepdims=True));return z/z.sum(axis=1,keepdims=True)
def placement(labels):
 if len(labels)!=64 or any(x not in CLASSES+'.' for x in labels):raise ValueError('64 concrete labels required')
 rows=[]
 for r in range(8):
  line='';empty=0
  for x in labels[r*8:r*8+8]:
   if x=='.':empty+=1
   else:
    if empty:line+=str(empty);empty=0
    line+=x
  rows.append(line+(str(empty) if empty else ''))
 return '/'.join(rows)
class Classifier:
 def __init__(self,model_dir):
  import onnxruntime as ort
  self.sessions=[]
  for name in MODEL_HASHES:
   data=(Path(model_dir)/name).read_bytes()
   if hashlib.sha256(data).hexdigest()!=MODEL_HASHES[name]:raise ValueError('Unrecognized model weights: '+name)
   options=ort.SessionOptions();options.intra_op_num_threads=1;options.inter_op_num_threads=1
   session=ort.InferenceSession(data,sess_options=options,providers=['CPUExecutionProvider'])
   expected=['batch',3,100 if 'occupancy' in name else 200,100]
   if session.get_inputs()[0].shape!=expected:raise ValueError('Unexpected input tensor')
   self.sessions.append(session)
 def recognize(self,image_path,calibration,threshold=.95):
  if not np.isfinite(threshold) or not .5<=threshold<=1:raise ValueError('Threshold must be between .5 and 1')
  path=Path(image_path);data=path.read_bytes();sha=hashlib.sha256(data).hexdigest()
  if calibration.get('sourceSha256')!=sha:raise ValueError('Calibration does not match source image hash')
  orientation=calibration.get('orientation')
  if orientation not in ['white-bottom','black-bottom']:raise ValueError('Explicit reviewed board orientation required')
  image=ImageOps.exif_transpose(Image.open(path)).convert('RGB')
  if list(image.size)!=calibration.get('imageSize'):raise ValueError('Calibration dimensions mismatch')
  corners=calibration.get('corners');p=np.asarray(corners,float)
  if p.shape!=(4,2) or (p<0).any() or (p[:,0]>image.width).any() or (p[:,1]>image.height).any():raise ValueError('Invalid image corners')
  started=time.perf_counter();oc,pc=crops(image,corners)
  o=softmax(self.sessions[0].run(['logits'],{'input':tensor(oc)})[0],2)
  q=softmax(self.sessions[1].run(['logits'],{'input':tensor(pc)})[0],12)
  labels=[];squares={}
  for canonical in range(64):
   i=canonical if orientation=='white-bottom' else 63-canonical
   full=np.concatenate(([o[i,0]],o[i,1]*q[i]));j=int(full.argmax());label=('.'+CLASSES)[j];score=float(full[j]);labels.append(label)
   square='abcdefgh'[canonical%8]+str(8-canonical//8)
   squares[square]={'label':('empty' if label=='.' else label) if score>=threshold else 'unknown','confidence':score,'rawLabel':label,'occupancyScore':float(o[i,1]),'classScores':{k:float(v) for k,v in zip('.'+CLASSES,full)}}
  unknown=sum(x['label']=='unknown' for x in squares.values())
  return {'schemaVersion':1,'source':'real-image-inference','sourceSha256':sha,'imageSize':list(image.size),'calibrationMode':calibration.get('mode','unspecified'),'calibrationHumanConfirmed':calibration.get('humanConfirmed',False),'orientation':orientation,'status':'needs-human-review','squares':squares,'rawPlacement':placement(labels),'completeAcceptedPlacement':placement(labels) if unknown==0 else None,'unknownSquares':unknown,'fen':None,'guidanceAllowed':False,'elapsedMs':round((time.perf_counter()-started)*1000,2),'threshold':threshold,'modelHashes':MODEL_HASHES,'limitations':['Scores are uncalibrated model probabilities, not evidence of correctness.','This image supplies no side-to-move or historical rights.','No king or piece-count repair is applied.','Manual calibration is not automatic board detection.']}
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('image');p.add_argument('--calibration',required=True);p.add_argument('--models',required=True);p.add_argument('--output',required=True);p.add_argument('--threshold',type=float,default=.95);a=p.parse_args()
 try:
  result=Classifier(a.models).recognize(a.image,json.loads(Path(a.calibration).read_text()),a.threshold);Path(a.output).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='squares'}))
 except Exception as e:p.exit(1,f'Recognition failed: {e}\n')
