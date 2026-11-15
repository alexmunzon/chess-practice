#!/usr/bin/env python3
"""Annotation-assisted controls only: fixed box/margin/rotation and canonical cstr crops."""
import argparse,json,math,os,subprocess,time
from pathlib import Path
from PIL import Image
from whole_photo import preprocess,decode
from photo_pieces import Classifier
from evaluate_video import ROOT,sha,score,ratio
MODES=('manual-box-10pct-ccw90-coreml','manual-canonical-corners-cstr')
def box(corners,size):
    xs,ys=zip(*corners);w=max(xs)-min(xs);h=max(ys)-min(ys)
    return [max(0,math.floor(min(xs)-.1*w)),max(0,math.floor(min(ys)-.1*h)),min(size[0],math.ceil(max(xs)+.1*w)),min(size[1],math.ceil(max(ys)+.1*h))]
def run(root):
    manifest=ROOT/'scripts/recognition/video-manifest.json';doc=json.loads(manifest.read_text());out=root/'results/video-manual-controls';out.mkdir(parents=True,exist_ok=True);model=root/'models/chessq-lite'
    freeze={'manifestSha256':sha(manifest),'evaluatorSha256':sha(__file__),'preprocessSha256':sha(ROOT/'scripts/recognition/whole_photo.py'),'classifierSha256':sha(ROOT/'scripts/recognition/photo_pieces.py'),'threshold':.95,'modes':list(MODES),'fixedPolicy':'Axis-aligned bounding box of annotated screen corners expanded by 10% width/height on EACH side, clipped to image, then 90 degrees CCW. Cstr receives annotated canonical a8,h8,h1,a1 corners and white-bottom meaning no output index inversion. No variant selection.'}
    (out/'pre-inference-freeze.json').write_text(json.dumps(freeze,indent=2)+'\n');cases=[]
    for item in doc['records']:
        source=root/item['image']
        if sha(source)!=item['sourceSha256']:raise ValueError('Image hash mismatch')
        start=time.perf_counter();target=out/(item['id']+'-crop.png')
        with Image.open(source) as im:
            bbox=box(item['screenCornersTLTRBRBL'],im.size);im.crop(bbox).transpose(Image.Transpose.ROTATE_90).save(target)
        tensor,ms=preprocess(target);inp=out/(item['id']+'.f32');tensor.astype('<f4').tofile(inp);cases.append((item,inp,out/(item['id']+'-logits.json'),bbox,ms,(time.perf_counter()-start)*1000))
    env=dict(os.environ);env.pop('CHESS_COREML_CPU_DIAGNOSTIC',None)
    subprocess.run([str(model/'run-model'),str(model/'cq-vit-s-644-v4-seed2-coreml-fp16-r1.mlpackage')]+[str(p) for c in cases for p in c[1:3]],check=True,env=env)
    results=[]
    for item,inp,output,bbox,ms,prep in cases:
        raw=json.loads(output.read_text());pred=decode(raw['logits']);(out/(item['id']+'-coreml-prediction.json')).write_text(json.dumps(pred,indent=2)+'\n')
        results.append({'id':item['id'],'mode':MODES[0],'box':bbox,'metrics':score(pred['squares'],item['squares']),'preprocessMs':ms,'preparationMs':prep,'inferenceMs':raw['inferenceMs'],'compileAndLoadMs':raw['compileAndLoadMs']})
    start=time.perf_counter();classifier=Classifier(root/'models');loadMs=(time.perf_counter()-start)*1000
    for item in doc['records']:
        calibration={'sourceSha256':item['sourceSha256'],'imageSize':item['imageSize'],'orientation':'white-bottom','corners':item['canonicalCornersA8H8H1A1'],'mode':MODES[1],'humanConfirmed':False}
        pred=classifier.recognize(root/item['image'],calibration,.95);(out/(item['id']+'-cstr-prediction.json')).write_text(json.dumps(pred,indent=2)+'\n')
        results.append({'id':item['id'],'mode':MODES[1],'metrics':score(pred['squares'],item['squares']),'cropAndInferenceMs':pred['elapsedMs'],'modelLoadMs':loadMs})
    aggregate={}
    for mode in MODES:
        selected=[r for r in results if r['mode']==mode];c={k:sum(r['metrics'][k] for r in selected) for k,v in selected[0]['metrics'].items() if type(v)is int};c.update(knownLabelAccuracy=ratio(c['correctKnownLabels'],c['knownLabels']),occupiedTypeAccuracy=ratio(c['correctOccupiedTypes'],c['knownOccupiedTypes']),occupiedTypeAcceptedCoverage=ratio(c['acceptedOccupiedTypes'],c['knownOccupiedTypes']),acceptedWrongRate=ratio(c['acceptedWrongKnownLabels'],c['acceptedKnownLabels']),exactBoardAccuracy=None);aggregate[mode]=c
    report=freeze|{'results':results,'aggregate':aggregate,'automaticPerformance':False,'guidanceAllowed':False,'limitations':['These controls deliberately consume annotation and are not automatic localization or end-to-end performance.','Same five correlated frames, frozen partial labels and fixed uncalibrated .95 score threshold. No exact-board accuracy available.','Canonical printed-coordinate mapping may differ from model orientation assumptions. No post-hoc remapping or repair.','Prior CoreML numerical-validation failure remains unresolved. No live hardware tested.']}
    for p in [out/'report.json',ROOT/'native/PhotoRecognition/video-control-results.json']:p.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(aggregate,indent=2))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);run(p.parse_args().root)
