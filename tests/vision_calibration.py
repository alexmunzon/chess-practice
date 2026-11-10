#!/usr/bin/env python3
"""Bounded generated-image benchmark; no claim of piece recognition."""
import importlib.util,json,sys,tempfile
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw,ImageFilter
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('calibrate',ROOT/'scripts/vision/calibrate.py'); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

def fixture(corners,variant):
    board=Image.new('RGB',(512,512)); d=ImageDraw.Draw(board)
    for r in range(8):
        for c in range(8): d.rectangle((c*64,r*64,(c+1)*64-1,(r+1)*64-1),fill=(225,220,195) if (r+c)%2==0 else (42,55,48))
    h=m.homography(corners); inv=np.linalg.inv(h); inv/=inv[2,2]; inv[:2,:]*=512
    canvas=board.transform((800,800),Image.Transform.PERSPECTIVE,tuple(inv.flatten()[:8]),Image.Resampling.BICUBIC,fillcolor=(115,118,123))
    if variant=='blur': canvas=canvas.filter(ImageFilter.GaussianBlur(4))
    if variant=='glare': ImageDraw.Draw(canvas).ellipse((275,175,560,405),fill=(255,255,255))
    if variant=='covered': ImageDraw.Draw(canvas).rectangle((150,150,650,650),fill=(128,128,128))
    if variant=='negative':
        canvas=Image.new('RGB',(800,800),(115,118,123)); ImageDraw.Draw(canvas).rectangle((150,150,650,650),fill=(225,220,195))
    return canvas

def main():
    detector=sys.argv[1] if len(sys.argv)>1 else '/tmp/chess-board-candidates'
    directory=Path(sys.argv[2]) if len(sys.argv)>2 else Path(tempfile.mkdtemp(prefix='chess-vision-'))
    directory.mkdir(parents=True,exist_ok=True)
    base=[[150,150],[650,150],[650,650],[150,650]]
    cases=[('front',base),('perspective',[[180,160],[640,200],[690,650],[100,610]]),('rotation',[[260,60],[740,260],[540,740],[60,540]]),('blur',base),('glare',base),('covered',base),('negative',base)]
    results=[]
    for name,corners in cases:
        path=directory/f'{name}.png'; fixture(corners,name).save(path)
        report=m.calibrate(path,directory/name,detector=detector)
        detected=bool(report['squares']); error=None
        if detected:
            error=float(np.mean(np.linalg.norm(np.array(report['corners'])-corners,axis=1)))
            assert error < 20, f'Corner error regression: {error}'
            assert report['fen'] is None and report['status']=='needs-human-confirmation'
            assert len(report['squares'])==64 and all(x['square'] is None for x in report['squares'])
        results.append(dict(case=name,detected=detected,meanCornerErrorPixels=error,proposalCount=len(report['proposals'])))
    manual=m.calibrate(directory/'perspective.png',directory/'manual',corners=cases[1][1],orientation='white-bottom',confirmed=True)
    assert manual['mode']=='manual-four-corner' and manual['status']=='calibration-confirmed'
    assert np.allclose(manual['squares'][0]['sourcePolygon'][0],cases[1][1][0])
    assert np.allclose(manual['squares'][-1]['sourcePolygon'][2],cases[1][1][2])
    assert manual['squares'][0]['square']=='a8' and manual['squares'][-1]['square']=='h1'
    black=m.calibrate(directory/'front.png',directory/'black',corners=base,orientation='black-bottom')
    assert black['squares'][0]['square']=='h1' and black['status']=='needs-human-confirmation'
    for invalid in [[[0,0]]*4,[[0,0],[10,10],[10,0],[0,10]],[[0,0],[900,0],[900,800],[0,800]]]:
        try: m.validate(invalid,800,800)
        except ValueError: pass
        else: raise AssertionError('Invalid corners accepted')
    assert sum(r['detected'] for r in results if r['case'] not in ['covered','negative']) >= 3
    for r in results:
        if r['case'] in ['covered','negative']: assert not r['detected'],r
    output={'results':results,'manualChecks':'passed','artifactDirectory':str(directory),'scope':'board-corner calibration only; seven generated fixtures; not real-world or piece recognition accuracy'}
    (directory/'benchmark.json').write_text(json.dumps(output,indent=2)+'\n'); print(json.dumps(output,indent=2))
if __name__=='__main__': main()
