#!/usr/bin/env python3
"""Frozen partial-label video diagnostic; no accuracy assigned to unknown truth."""
import argparse,hashlib,json,os,subprocess,time
from pathlib import Path
from PIL import Image
from whole_photo import preprocess,decode
ROOT=Path(__file__).resolve().parents[2]
MODES=('raw-whole-photo','manual-annotation-rotation-control')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def ratio(a,b):return a/b if b else None

def score(squares,truth):
    if set(squares)!=set(truth) or len(truth)!=64:raise ValueError('Require identical 64-square keys')
    counts=dict(totalSquares=64,knownLabels=0,correctKnownLabels=0,acceptedKnownLabels=0,acceptedWrongKnownLabels=0,knownOccupiedTypes=0,correctOccupiedTypes=0,acceptedOccupiedTypes=0,acceptedCorrectOccupiedTypes=0,knownOccupancy=0,correctOccupancy=0,knownOccupied=0,detectedOccupied=0,acceptedOccupied=0,knownEmpty=0,falseOccupiedOnEmpty=0,acceptedFalseOccupiedOnEmpty=0,acceptedSquares=0,unknownLabels=0,acceptedUnknownLabels=0,unknownOccupancy=0,acceptedUnknownOccupancy=0)
    unknownScores=[];occludedScores=[]
    for square,t in truth.items():
        p=squares[square];raw=p['rawLabel'];a=p['label']!='unknown';known=t['label']!='unknown';occupied=raw!='.'
        counts['acceptedSquares']+=a
        if known:
            correct=raw==t['label'];counts['knownLabels']+=1;counts['correctKnownLabels']+=correct;counts['acceptedKnownLabels']+=a;counts['acceptedWrongKnownLabels']+=a and not correct
            if t['label']!='.':
                counts['knownOccupiedTypes']+=1;counts['correctOccupiedTypes']+=correct;counts['acceptedOccupiedTypes']+=a;counts['acceptedCorrectOccupiedTypes']+=a and correct
        else:
            counts['unknownLabels']+=1;counts['acceptedUnknownLabels']+=a;unknownScores.append(p['confidence'])
        if t['occupancy']!='unknown':
            truthOccupied=t['occupancy']=='occupied';counts['knownOccupancy']+=1;counts['correctOccupancy']+=occupied==truthOccupied
            if truthOccupied:counts['knownOccupied']+=1;counts['detectedOccupied']+=occupied;counts['acceptedOccupied']+=a
            else:counts['knownEmpty']+=1;counts['falseOccupiedOnEmpty']+=occupied;counts['acceptedFalseOccupiedOnEmpty']+=a and occupied
        else:counts['unknownOccupancy']+=1;counts['acceptedUnknownOccupancy']+=a;occludedScores.append(p['confidence'])
    return counts|{'knownLabelAccuracy':ratio(counts['correctKnownLabels'],counts['knownLabels']),'acceptedWrongRate':ratio(counts['acceptedWrongKnownLabels'],counts['acceptedKnownLabels']),'occupiedTypeAccuracy':ratio(counts['correctOccupiedTypes'],counts['knownOccupiedTypes']),'occupiedTypeAcceptedCoverage':ratio(counts['acceptedOccupiedTypes'],counts['knownOccupiedTypes']),'occupancyAccuracy':ratio(counts['correctOccupancy'],counts['knownOccupancy']),'knownLabelCoverage':counts['knownLabels']/64,'knownOccupancyCoverage':counts['knownOccupancy']/64,'predictionCoverage':counts['acceptedSquares']/64,'unknownLabelMeanScore':ratio(sum(unknownScores),len(unknownScores)),'unknownOccupancyMeanScore':ratio(sum(occludedScores),len(occludedScores)),'exactBoardAccuracy':None}

def run(root):
    manifest=ROOT/'scripts/recognition/video-manifest.json';doc=json.loads(manifest.read_text());model=root/'models/chessq-lite';out=root/'results/video-whole-photo';out.mkdir(parents=True,exist_ok=True)
    freeze={'manifestSha256':sha(manifest),'preprocessSha256':sha(ROOT/'scripts/recognition/whole_photo.py'),'runnerSha256':sha(ROOT/'native/PhotoRecognition/RunModel.swift'),'evaluatorSha256':sha(__file__),'threshold':.95,'modes':list(MODES),'orientationPolicy':'Raw output interpreted literally as canonical a8..h1. Manual control uses fixed counterclockwise 90-degree whole-image rotation from printed-coordinate annotation; no best-of orientation search.'}
    (out/'pre-inference-freeze.json').write_text(json.dumps(freeze,indent=2)+'\n')
    if sha(root/doc['source']['localMedia'])!=doc['source']['mediaSha256']:raise ValueError('Media hash mismatch')
    cases=[]
    for mode in MODES:
        for item in doc['records']:
            source=root/item['image']
            if sha(source)!=item['sourceSha256']:raise ValueError('Image hash mismatch')
            start=time.perf_counter()
            if mode==MODES[1]:
                rotated=out/(item['id']+'-manual-rotation.png')
                with Image.open(source) as image:image.transpose(Image.Transpose.ROTATE_90).save(rotated)
                source=rotated
            x,preMs=preprocess(source);stem=item['id']+'-'+mode;path=out/(stem+'.f32');x.astype('<f4').tofile(path)
            cases.append({'mode':mode,'record':item,'input':path,'output':out/(stem+'.json'),'preprocessMs':preMs,'preparationMs':(time.perf_counter()-start)*1000})
    env=dict(os.environ);env.pop('CHESS_COREML_CPU_DIAGNOSTIC',None)
    subprocess.run([str(model/'run-model'),str(model/'cq-vit-s-644-v4-seed2-coreml-fp16-r1.mlpackage')]+[str(c[k]) for c in cases for k in ('input','output')],check=True,env=env)
    results=[]
    for c in cases:
        raw=json.loads(c['output'].read_text());pred=decode(raw['logits']);item=c['record'];(out/(item['id']+'-'+c['mode']+'-prediction.json')).write_text(json.dumps(pred,indent=2)+'\n')
        results.append({'id':item['id'],'timestampSeconds':item['timestampSeconds'],'mode':c['mode'],'metrics':score(pred['squares'],item['squares']),'preprocessMs':c['preprocessMs'],'preparationMs':c['preparationMs'],'inferenceMs':raw['inferenceMs'],'compileAndLoadMs':raw['compileAndLoadMs']})
    aggregate={}
    for mode in MODES:
        selected=[r for r in results if r['mode']==mode]
        counts={k:sum(r['metrics'][k] for r in selected) for k,v in selected[0]['metrics'].items() if type(v) is int}
        counts.update(knownLabelAccuracy=ratio(counts['correctKnownLabels'],counts['knownLabels']),acceptedWrongRate=ratio(counts['acceptedWrongKnownLabels'],counts['acceptedKnownLabels']),occupiedTypeAccuracy=ratio(counts['correctOccupiedTypes'],counts['knownOccupiedTypes']),occupiedTypeAcceptedCoverage=ratio(counts['acceptedOccupiedTypes'],counts['knownOccupiedTypes']),occupancyAccuracy=ratio(counts['correctOccupancy'],counts['knownOccupancy']),predictionCoverage=ratio(counts['acceptedSquares'],counts['totalSquares']),exactBoardAccuracy=None)
        aggregate[mode]=counts
    report=freeze|{'schemaVersion':1,'sourcePage':doc['source']['pageUrl'],'independentSources':1,'frames':5,'computeUnits':'CPU_AND_GPU','allowLowPrecisionAccumulationOnGPU':False,'numericalValidationGate':'failed: reproducible one-logit upstream tolerance violation in prior synthetic diagnostic','guidanceAllowed':False,'results':results,'aggregate':aggregate,'limitations':['One correlated staged video, partial independent assistant labels, not user-confirmed.','Exact board and complete FEN unknown; unknown labels never count as empty or correct.','Manual rotation control is annotation-assisted, not automatic performance.','No model tuning, orientation selection, chess-rule repair, historical state inference, or new threshold.','Fixed .95 softmax score is not calibrated confidence.','First inference includes startup; each case has three calls; logits scored from third. No phone/glasses performance or live-video temporal tracking claim.']}
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');(ROOT/'native/PhotoRecognition/video-results.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);run(p.parse_args().root)
