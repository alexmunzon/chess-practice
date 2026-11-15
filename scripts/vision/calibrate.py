#!/usr/bin/env python3
"""Offline calibration only: rectangle proposals + checker-pattern heuristic, never FEN."""
import argparse, hashlib, json, subprocess
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
    # Corners of each tile are less often occupied by pieces than its center.
    edges=np.array([[np.median([np.median(gray[r*64+y:r*64+y+8,c*64+x:c*64+x+8]) for x,y in [(7,7),(49,7),(7,49),(49,49)]]) for c in range(8)] for r in range(8)])
    ec=edges-edges.mean(); ed=np.linalg.norm(ec)*8
    edgeCorrelation=abs(float((ec*signs).sum()/ed)) if ed else 0.0
    edgeContrast=abs(float(edges[signs==1].mean()-edges[signs==-1].mean()))
    return {'alternationCorrelation':correlation,'contrast':contrast,'tileCornerCorrelation':edgeCorrelation,'tileCornerContrast':edgeContrast,'passesHeuristic':bool((correlation>=0.75 and contrast>=25) or (edgeCorrelation>=0.85 and edgeContrast>=25))}

def grid_candidates(image):
    """Bounded near-axis Hough fallback. Derives geometry from image edges only.

    Finds consecutive grid line families, extrapolates missing outer lines and
    enumerates their possible lattice offsets. An independent checker filter
    selects proposals. This intentionally abstains when either family is weak.
    """
    from PIL import ImageFilter
    small=image.convert('L'); small.thumbnail((640,640))
    a=np.asarray(small.filter(ImageFilter.GaussianBlur(1)),dtype=float)
    gy,gx=np.gradient(a); height,width=a.shape
    def family(vertical):
        gradient=gx if vertical else gy
        mask=np.abs(gradient)>max(8,float(np.percentile(np.abs(gradient),90)))
        y,x=np.where(mask); weights=np.abs(gradient[mask])
        if len(x)<100: return []
        candidates=[]
        for slope in np.linspace(-0.5,0.5,101):
            intercept=(x-slope*y) if vertical else (y-slope*x)
            padding=max(width,height)
            bins=np.round(intercept).astype(int)+padding
            votes=np.bincount(bins,weights=weights,minlength=3*padding)
            for i in np.argpartition(votes,-8)[-8:]: candidates.append((float(votes[i]),float(slope),float(i-padding)))
        candidates.sort(reverse=True); selected=[]
        center=height/2 if vertical else width/2
        for score,slope,b in candidates:
            if score<candidates[0][0]*0.45: break
            if any(abs(b+slope*center-(p[2]+p[1]*center))<9 for p in selected): continue
            # Refine Hough quantization from gradient-weighted nearby pixels.
            independent=y if vertical else x; dependent=x if vertical else y
            near=np.abs(dependent-slope*independent-b)<1.6
            if near.sum()>=20:
                design=np.column_stack((independent[near],np.ones(near.sum())))
                coef=np.linalg.lstsq(design*weights[near,None],dependent[near]*weights[near],rcond=None)[0]
                slope,b=map(float,coef)
            selected.append((score,slope,b))
            if len(selected)==9: break
        selected.sort(key=lambda p:p[2]+p[1]*center)
        return selected
    horizontal,vertical=family(False),family(True)
    if not 3<=len(horizontal)<=9 or not 5<=len(vertical)<=9: return []
    # Horizontal intersections vary projectively with rank. Vertical lines
    # are approximately an affine pencil in this restricted camera geometry.
    v=np.array(vertical); n=len(v); idx=np.arange(n)
    fit=np.array([np.polyfit(idx,v[:,j],1) for j in [1,2]])
    fitted=np.column_stack((np.polyval(fit[0],idx),np.polyval(fit[1],idx)))
    residual=np.max(np.abs((fitted[:,0]-v[:,1])*height/2+fitted[:,1]-v[:,2]))
    gaps=np.diff(v[:,1]*height/2+v[:,2])
    if residual>3 or gaps.min()<12 or gaps.max()/gaps.min()>1.5: return []
    hs=np.array(horizontal); positions=hs[:,1]*width/2+hs[:,2]
    gaps=np.diff(positions)
    if gaps.min()<10 or gaps.max()/gaps.min()>1.7: return []
    results=[]
    for voffset in range(10-n):
        left=np.array([np.polyval(fit[0],-voffset),np.polyval(fit[1],-voffset)])
        right=np.array([np.polyval(fit[0],8-voffset),np.polyval(fit[1],8-voffset)])
        for hoffset in range(10-len(hs)):
            ranks=np.arange(len(hs))+hoffset
            design=np.column_stack((ranks,np.ones(len(hs)),-positions*ranks))
            aa,bb,cc=np.linalg.lstsq(design,positions,rcond=None)[0]
            if min(1,1+8*cc)<=0: continue
            prediction=(aa*ranks+bb)/(cc*ranks+1)
            if np.max(np.abs(prediction-positions))>2: continue
            top,bottom=bb,(8*aa+bb)/(8*cc+1)
            slopefit=np.polyfit(ranks,hs[:,1],1)
            def intersection(vline,rank,pos):
                m=float(np.polyval(slopefit,rank)); b=pos-m*width/2
                vm,vb=vline
                yy=(m*vb+b)/(1-m*vm); return [vm*yy+vb,yy]
            points=[intersection(left,0,top),intersection(right,0,top),intersection(right,8,bottom),intersection(left,8,bottom)]
            points=np.array(points)*[image.width/width,image.height/height]
            try: points=validate(points,*image.size)
            except ValueError: continue
            results.append({'corners':points,'rectangleConfidence':None,'geometryMethod':'numpy-grid-line-extrapolation','observedHorizontalLines':len(hs),'observedVerticalLines':n})
    return results

def calibrate(image_path,out,corners=None,detector=None,orientation=None,confirmed=False):
    if (corners is None) == (detector is None): raise ValueError('Choose exactly one: manual corners or detector')
    if orientation not in (None,'white-bottom','black-bottom'): raise ValueError('Unsupported orientation')
    out=Path(out); out.mkdir(parents=True,exist_ok=True)
    image=ImageOps.exif_transpose(Image.open(image_path)).convert('RGB')
    # Feed exactly the same oriented pixels to Vision and the manual path.
    prepared=out/'input-oriented.png'; image.save(prepared)
    proposals=[]
    selectedMethod='manual-four-corner'
    if corners is None:
        if not detector: raise ValueError('Automatic mode requires --detector compiled BoardCandidates.swift')
        result=json.loads(subprocess.run([str(Path(detector).resolve()),str(prepared.resolve()),str((out/'candidates').resolve())],capture_output=True,text=True,check=True,timeout=45).stdout)
        for candidate in result['candidates']:
            points=[[p['x'],p['y']] for p in candidate['corners']]
            try:
                points=validate(points,*image.size); h=homography(points)
                score=checker_score(normalize(image,h))
                proposals.append(dict(corners=points,geometryMethod='apple-vision-rectangle',rectangleConfidence=candidate['rectangleConfidence'],**score))
            except (ValueError,np.linalg.LinAlgError): pass
        if not any(x['passesHeuristic'] for x in proposals):
            for candidate in grid_candidates(image):
                score=checker_score(normalize(image,homography(candidate['corners'])))
                proposals.append(dict(**candidate,**score))
        proposals.sort(key=lambda x:max(x['alternationCorrelation'],x['tileCornerCorrelation']),reverse=True)
        valid=[x for x in proposals if x['passesHeuristic']]
        corners=valid[0]['corners'] if valid else None
        selectedMethod=valid[0]['geometryMethod'] if valid else None
    mode='manual-four-corner' if detector is None else 'automatic-rectangle-or-grid-and-checker-heuristic'
    report={'schemaVersion':2,'sourceSha256':hashlib.sha256(Path(image_path).read_bytes()).hexdigest(),'orientedRgbSha256':hashlib.sha256(image.tobytes()).hexdigest(),'pixelCoordinateSpace':'EXIF-oriented RGB pixels; top-left origin','selectedGeometryMethod':selectedMethod,'source':'prerecorded-image','imageSize':list(image.size),'mode':mode,'status':'abstained','proposals':proposals,'squares':[], 'orientation':orientation,'humanConfirmed':confirmed,'fen':None,'gameState':{'sideToMove':None,'castlingRights':None,'enPassant':None,'halfmoveClock':None,'fullmoveNumber':None},'limitations':['No piece recognition or chess FEN from pixels.','Rectangle confidence and checker score are not calibrated probabilities.','Human corner review and orientation required; game history cannot be recovered from an image.','Synthetic performance does not establish physical-board accuracy.']}
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
