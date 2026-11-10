#!/usr/bin/env python3
"""Offline calibration only: rectangle proposals + checker-pattern heuristic, never FEN."""
import argparse, json, subprocess
from pathlib import Path
import numpy as np
from PIL import Image, ImageOps, ImageDraw

SIZE = 512

def homography(corners):
    target = [(0,0),(1,0),(1,1),(0,1)]
    a, b = [], []
    for (u,v),(x,y) in zip(target,corners):
        a.extend([[u,v,1,0,0,0,-u*x,-v*x],[0,0,0,u,v,1,-u*y,-v*y]])
        b.extend([x,y])
    h = np.append(np.linalg.solve(np.array(a),np.array(b)),1).reshape(3,3)
    return h

def project(h,u,v):
    p=h @ [u,v,1]; return [float(p[0]/p[2]),float(p[1]/p[2])]

def validate(corners,w,h):
    p=np.asarray(corners,dtype=float)
    if p.shape != (4,2) or not np.isfinite(p).all(): raise ValueError('Four finite [x,y] corners required')
    if (p[:,0]<0).any() or (p[:,0]>w).any() or (p[:,1]<0).any() or (p[:,1]>h).any(): raise ValueError('Corners outside image')
    d=np.roll(p,-1,axis=0)-p
    cross=d[:,0]*np.roll(d[:,1],-1)-d[:,1]*np.roll(d[:,0],-1)
    if not (cross>1).all(): raise ValueError('Corners must be convex clockwise TL,TR,BR,BL with nonzero area')
    return p.tolist()

def normalize(image,h):
    # Pillow needs output-pixel -> source-pixel projective coefficients.
    q=h.copy(); q[:,0:2] /= SIZE
    return image.transform((SIZE,SIZE),Image.Transform.PERSPECTIVE,tuple(q.flatten()[:8]),Image.Resampling.BICUBIC)

def checker_score(image):
    gray=np.asarray(image.convert('L').resize((SIZE,SIZE)),dtype=float)
    # Inner-square medians reduce grid-line/border influence. Only a heuristic.
    values=np.array([[np.median(gray[r*64+16:r*64+48,c*64+16:c*64+48]) for c in range(8)] for r in range(8)])
    signs=np.fromfunction(lambda r,c: ((r+c)%2)*2-1,(8,8))
    centered=values-values.mean()
    denom=np.linalg.norm(centered)*8
    correlation=abs(float((centered*signs).sum()/denom)) if denom else 0.0
    contrast=abs(float(values[signs==1].mean()-values[signs==-1].mean()))
    return {'alternationCorrelation':correlation,'contrast':contrast,'passesHeuristic':bool(correlation>=0.75 and contrast>=25)}

def calibrate(image_path,out,corners=None,detector=None,orientation=None,confirmed=False):
    if (corners is None) == (detector is None): raise ValueError('Choose exactly one: manual corners or detector')
    if orientation not in (None,'white-bottom','black-bottom'): raise ValueError('Unsupported orientation')
    out=Path(out); out.mkdir(parents=True,exist_ok=True)
    image=ImageOps.exif_transpose(Image.open(image_path)).convert('RGB')
    # Feed exactly the same oriented pixels to Vision and the manual path.
    prepared=out/'input-oriented.png'; image.save(prepared)
    proposals=[]
    if corners is None:
        if not detector: raise ValueError('Automatic mode requires --detector compiled BoardCandidates.swift')
        result=json.loads(subprocess.run([str(Path(detector).resolve()),str(prepared.resolve()),str((out/'candidates').resolve())],capture_output=True,text=True,check=True,timeout=45).stdout)
        for candidate in result['candidates']:
            points=[[p['x'],p['y']] for p in candidate['corners']]
            try:
                points=validate(points,*image.size); h=homography(points)
                score=checker_score(normalize(image,h))
                proposals.append(dict(corners=points,rectangleConfidence=candidate['rectangleConfidence'],**score))
            except (ValueError,np.linalg.LinAlgError): pass
        proposals.sort(key=lambda x:x['alternationCorrelation'],reverse=True)
        valid=[x for x in proposals if x['passesHeuristic']]
        corners=valid[0]['corners'] if valid else None
    mode='manual-four-corner' if detector is None else 'automatic-rectangle-and-checker-heuristic'
    report={'schemaVersion':1,'source':'prerecorded-image','imageSize':list(image.size),'mode':mode,'status':'abstained','proposals':proposals,'squares':[], 'orientation':orientation,'humanConfirmed':confirmed,'fen':None,'gameState':{'sideToMove':None,'castlingRights':None,'enPassant':None,'halfmoveClock':None,'fullmoveNumber':None},'limitations':['No piece recognition or chess FEN from pixels.','Rectangle confidence and checker score are not calibrated probabilities.','Human corner review and orientation required; game history cannot be recovered from an image.','Synthetic performance does not establish physical-board accuracy.']}
    if corners is not None:
        corners=validate(corners,*image.size); h=homography(corners)
        normalized=normalize(image,h); normalized.save(out/'board-normalized.png')
        overlay=image.copy(); draw=ImageDraw.Draw(overlay)
        for i in range(9):
            for line in [(project(h,i/8,0),project(h,i/8,1)),(project(h,0,i/8),project(h,1,i/8))]:
                draw.line([tuple(x) for x in line],fill=(255,0,40),width=max(1,image.width//400))
        overlay.save(out/'grid-review.png')
        report.update(corners=corners,normalizedImage=str((out/'board-normalized.png').resolve()),gridReviewImage=str((out/'grid-review.png').resolve()),checkerScore=checker_score(normalized),status='calibration-confirmed' if confirmed and orientation else 'needs-human-confirmation')
        for r in range(8):
            for c in range(8):
                label=None
                if orientation=='white-bottom': label=chr(97+c)+str(8-r)
                if orientation=='black-bottom': label=chr(104-c)+str(r+1)
                report['squares'].append({'row':r,'column':c,'square':label,'sourcePolygon':[project(h,u/8,v/8) for u,v in [(c,r),(c+1,r),(c+1,r+1),(c,r+1)]]})
    (out/'calibration.json').write_text(json.dumps(report,indent=2)+'\n')
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('image'); p.add_argument('--output',required=True)
    g=p.add_mutually_exclusive_group(required=True); g.add_argument('--corners',help='JSON [[x,y],...] in oriented image pixels: TL,TR,BR,BL'); g.add_argument('--detector')
    p.add_argument('--orientation',choices=['white-bottom','black-bottom']); p.add_argument('--confirm-calibration',action='store_true',help='Use only after personally reviewing corners and orientation; never confirms pieces/game state')
    a=p.parse_args()
    try: print(json.dumps(calibrate(a.image,a.output,json.loads(a.corners) if a.corners else None,a.detector,a.orientation,a.confirm_calibration)))
    except Exception as e: p.exit(1,f'Calibration failed: {e}\n')
