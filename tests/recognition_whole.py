#!/usr/bin/env python3
"""Offline diagnostic: frozen photos plus published synthetic numerical targets."""
import argparse,hashlib,json,os,subprocess,sys,time
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts/recognition'))
from whole_photo import preprocess,decode,proposal

def expand(fen):
    out=[]
    for c in fen:
        if c!='/':out.extend(['.']*int(c) if c.isdigit() else [c])
    assert len(out)==64
    return out

def finish_report(report, out):
    """Preserve useful diagnostic evidence, then fail the process if its gate failed."""
    serialized = json.dumps(report, indent=2)
    (out / 'report.json').write_text(serialized + '\n')
    print(serialized)
    if report['numericalValidation']['passed'] is not True:
        raise SystemExit(1)

def run_required_gpu(model, cases):
    """Run the required profile and validate every output before scoring it."""
    env = dict(os.environ)
    env.pop('CHESS_COREML_CPU_DIAGNOSTIC', None)
    subprocess.run([str(model/'run-model'), str(model/'cq-vit-s-644-v4-seed2-coreml-fp16-r1.mlpackage')]
                   + [str(path) for pair in cases for path in pair], check=True, env=env)
    outputs = []
    for _, output in cases:
        raw = json.loads(output.read_text())
        if not isinstance(raw, dict) or raw.get('computeUnits') != 'CPU_AND_GPU' or raw.get('allowLowPrecisionAccumulationOnGPU') is not False:
            raise ValueError(f'Native output does not explicitly match the required CPU_AND_GPU profile: {output.name}')
        outputs.append(raw)
    return outputs

def main(root):
    model=root/'models/chessq-lite'; out=root/'results/whole-photo';out.mkdir(parents=True,exist_ok=True)
    manifest=ROOT/'scripts/recognition/real-photos-manifest.json';records=json.loads(manifest.read_text())['records']
    refs=np.load(model/'reference.npz',allow_pickle=False);targets=np.load(model/'targets/logits.npz',allow_pickle=False)
    assert hashlib.sha256((model/'reference.npz').read_bytes()).hexdigest()=='c1f47afa5d0bf903403f932a311969842754802da0ebfc658f043cd705f643ee'
    assert hashlib.sha256((model/'targets/logits.npz').read_bytes()).hexdigest()==json.loads((model/'targets/targets.json').read_text())['arrays_sha256']
    cases=[]
    for i,x in enumerate(refs['inputs']):
        path=out/f'reference-{i}.f32';x.astype('<f4').tofile(path);cases.append((path,out/f'reference-{i}.json'))
    pre=[]
    for item in records:
        source=root/'input'/item['image'];assert hashlib.sha256(source.read_bytes()).hexdigest()==item['sourceSha256']
        # Only the image path enters preprocessing. No corners, labels, or orientation annotation.
        x,ms=preprocess(source);pre.append(ms);path=out/(item['id']+'.f32');x.astype('<f4').tofile(path);cases.append((path,out/(item['id']+'-logits.json')))
    outputs=run_required_gpu(model,cases)
    observed=np.stack([np.array(outputs[i]['logits']).reshape(1,64,13) for i in range(3)])
    expected=targets['fp16'];err=np.abs(observed-expected);limit=.01+.001*np.abs(expected)
    numerical={'cases':3,'squaresMatched':int((observed.argmax(-1)==expected.argmax(-1)).sum()),'totalSquares':192,'maxAbsoluteLogitError':float(err.max()),'logitsOutsideTolerance':int((err>limit).sum()),'totalLogits':2496,'atol':.01,'rtol':.001,'passed':bool((err<=limit).all() and (observed.argmax(-1)==expected.argmax(-1)).all())}
    results=[]
    for i,item in enumerate(records):
        raw=outputs[i+3];prediction=proposal(root/'input'/item['image'],raw['logits']);(out/(item['id']+'-prediction.json')).write_text(json.dumps(prediction,indent=2)+'\n')
        squares=list(prediction['squares'].values());truth=expand(item['placement']);correct=[s['rawLabel']==t for s,t in zip(squares,truth)];accepted=[s['label']!='unknown' for s in squares];occupied=[t!='.' for t in truth]
        metrics={'rawExactBoard':all(correct),'acceptedExactBoard':all(correct) and all(accepted),'correctSquares':sum(correct),'totalSquares':64,'squareAccuracy':sum(correct)/64,'correctOccupiedSquares':sum(c and o for c,o in zip(correct,occupied)),'occupiedSquares':sum(occupied),'occupiedAccuracy':sum(c and o for c,o in zip(correct,occupied))/sum(occupied),'acceptedWrong':sum(a and not c for a,c in zip(accepted,correct)),'acceptedSquares':sum(accepted),'coverage':sum(accepted)/64}
        results.append({'id':item['id'],'sourceSha256':item['sourceSha256'],'split':item['split'],'metrics':metrics,'preprocessMs':pre[i],'inferenceMs':raw['inferenceMs'],'compileAndLoadMs':raw['compileAndLoadMs']})
    report={'modelRevision':'7b33e1d47be02ce67b8e30ff7f09418166037d99','modelSha256':'091e8a9f22a517322eccd7bf8292a76fd653f9f913ff15d2eb9e8d914e959016','manifestSha256':hashlib.sha256(manifest.read_bytes()).hexdigest(),'computeUnits':'CPU_AND_GPU','allowLowPrecisionAccumulationOnGPU':False,'threshold':.95,'numericalValidation':numerical,'results':results,'limitations':['Three starting-position photographs only, already used for another model: cross-model diagnostic, not pristine holdout or a general accuracy estimate.','No label tuning, king repair, inferred historical state, crop, padding, or annotated orientation transformation.','Whole-image EXIF-aware RGB preprocessing with per-channel Pillow float-mode antialiased bilinear; not independently compared to training preprocessing.','Fixed softmax threshold is uncalibrated. Mac latency is not glasses or phone latency.','Upstream training-image overlap is unknown. Noncommercial private evaluation only; weights are not redistributed.']}
    finish_report(report, out)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);main(p.parse_args().root)
