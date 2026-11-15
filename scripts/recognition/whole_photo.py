#!/usr/bin/env python3
"""Local whole-photo tensor preprocessing and raw decoding; no labels/corners enter inference."""
import argparse,hashlib,json,time
from pathlib import Path
import numpy as np
from PIL import Image,ImageOps
SYMBOLS='.PNBRQKpnbrqk'
THRESHOLD=.95

def preprocess(path):
    start=time.perf_counter()
    with Image.open(path) as source:
        rgb=np.asarray(ImageOps.exif_transpose(source).convert('RGB'),dtype=np.float32)
    # Pillow's float-mode bilinear uses a widened triangular antialias filter
    # for downsampling. Each channel stays floating point, with no uint8 roundtrip.
    resized=np.stack([np.asarray(Image.fromarray(rgb[:,:,i]).resize((644,644),Image.Resampling.BILINEAR),dtype=np.float32) for i in range(3)])
    tensor=(resized/np.float32(255)-np.array([.485,.456,.406],np.float32)[:,None,None])/np.array([.229,.224,.225],np.float32)[:,None,None]
    return tensor[None],(time.perf_counter()-start)*1000

def decode(logits):
    x=np.asarray(logits,dtype=np.float32)
    if x.size!=832 or not np.isfinite(x).all():raise ValueError('Expected 832 finite logits')
    x=x.reshape(64,13);p=np.exp(x-x.max(axis=1,keepdims=True));p/=p.sum(axis=1,keepdims=True)
    labels=x.argmax(axis=1); scores=p[np.arange(64),labels]
    return {'threshold':THRESHOLD,'confidenceNote':'Softmax scores; fixed threshold is not calibrated confidence','squares':{'abcdefgh'[i%8]+str(8-i//8):{'rawLabel':SYMBOLS[k],'label':('empty' if k==0 else SYMBOLS[k]) if float(scores[i])>=THRESHOLD else 'unknown','confidence':float(scores[i])} for i,k in enumerate(labels)}}

def proposal(image,logits):
    result=decode(logits)
    rows=[]
    raw=[x['rawLabel'] for x in result['squares'].values()]
    for offset in range(0,64,8):
        row='';empty=0
        for symbol in raw[offset:offset+8]:
            if symbol=='.':empty+=1
            else:
                if empty:row+=str(empty);empty=0
                row+=symbol
        if empty:row+=str(empty)
        rows.append(row)
    with Image.open(image) as im:size=list(ImageOps.exif_transpose(im).size)
    result.update(schemaVersion=1,source='real-image-inference',sourceSha256=hashlib.sha256(Path(image).read_bytes()).hexdigest(),imageSize=size,status='needs-human-review',rawPlacement='/'.join(rows),fen=None,guidanceAllowed=False,model='joelseytre/chessq-lite',modelRevision='7b33e1d47be02ce67b8e30ff7f09418166037d99',numericalValidationStatus='failed-one-logit-tolerance-on-evaluation-mac')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('image');p.add_argument('tensor');a=p.parse_args()
    tensor,ms=preprocess(a.image);tensor.astype('<f4').tofile(a.tensor);print(json.dumps({'preprocessMs':ms,'shape':list(tensor.shape)}))
