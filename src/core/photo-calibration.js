import {createHash} from 'node:crypto';

export const MAX_CALIBRATION_HEADER_BYTES = 4096;
export const MANUAL_MODEL_REVISION = '4690fd5418ff7c405a76d1c156077ecd865ac053';
export const MANUAL_MODEL_HASHES = Object.freeze({
  'board_photo_occupancy.onnx':'dcafa86708036f1c50d2471bcfef838a3973e63bc6e3eef08dd3adccf6e0067d',
  'board_photo_pieces.onnx':'79f7833e4fd802eb10de4d2765bb243ec51c40bb5097989af9ff4db789f2a8af',
});
const sha = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const fail = () => { throw Object.assign(new Error('Review four image-order corners and explicit board orientation for this exact image.'),{code:'INVALID_CALIBRATION'}); };

export function calibrationId(request) {
  const values=Buffer.alloc(64);
  request.corners.flat().forEach((n,i)=>values.writeDoubleBE(Object.is(n,-0)?0:n,i*8));
  return createHash('sha256').update(`manual-image-calibration-v1\n${request.sourceSha256}\n${request.imageSize.join(',')}\n${request.topLeftSquare}\n`).update(values).digest('hex');
}

export function validateCalibrationRequest(value, {digest, reviewed=false} = {}) {
  const required=['sourceSha256','imageSize','corners','topLeftSquare','geometryReviewed'];
  if (!record(value) || required.some(k=>!Object.hasOwn(value,k)) || Object.keys(value).some(k=>![...required,'calibrationId'].includes(k))) fail();
  const {sourceSha256,imageSize,corners,topLeftSquare,geometryReviewed}=value;
  if (!sha(sourceSha256) || (digest!==undefined && sourceSha256!==digest) ||
      !Array.isArray(imageSize) || imageSize.length!==2 || !imageSize.every(n=>Number.isInteger(n)&&n>0&&n<=8192) || imageSize[0]*imageSize[1]>25_000_000 ||
      !['a8','h8','h1','a1'].includes(topLeftSquare) || geometryReviewed!==reviewed ||
      !Array.isArray(corners) || corners.length!==4 || corners.some(p=>!Array.isArray(p)||p.length!==2||!p.every(Number.isFinite)||p[0]<0||p[0]>imageSize[0]||p[1]<0||p[1]>imageSize[1])) fail();
  const copy={sourceSha256,imageSize:[...imageSize],corners:corners.map(p=>[...p]),topLeftSquare,geometryReviewed};
  const edges=copy.corners.map((p,i)=>copy.corners[(i+1)%4].map((n,j)=>n-p[j]));
  if (edges.some((e,i)=>e[0]*edges[(i+1)%4][1]-e[1]*edges[(i+1)%4][0]<=1)) fail();
  const [tl,tr,br,bl]=copy.corners;
  if (tl[1]+tr[1]>=bl[1]+br[1] || tl[0]+bl[0]>=tr[0]+br[0]) fail();
  if (reviewed) {
    if (!sha(value.calibrationId) || value.calibrationId!==calibrationId(copy)) fail();
    copy.calibrationId=value.calibrationId;
  } else if (Object.hasOwn(value,'calibrationId')) fail();
  return copy;
}

export function parseCalibrationHeader(header,{reviewed=false}={}) {
  if (typeof header!=='string' || Buffer.byteLength(header)>MAX_CALIBRATION_HEADER_BYTES) fail();
  let value;try { value=JSON.parse(header); } catch { fail(); }
  return validateCalibrationRequest(value,{reviewed});
}

export function validateCalibrationPreview(result, request) {
  if (!record(result) || result.schemaVersion!==1 || result.source!=='manual-image-calibration' ||
      result.status!=='needs-geometry-review' || result.fen!==null || result.guidanceAllowed!==false ||
      result.sourceSha256!==request.sourceSha256 || result.calibrationId!==calibrationId(request) ||
      result.topLeftSquare!==request.topLeftSquare || JSON.stringify(result.imageSize)!==JSON.stringify(request.imageSize) ||
      JSON.stringify(result.corners)!==JSON.stringify(request.corners) || !Array.isArray(result.squares) || result.squares.length!==64 ||
      ['humanReviewed','humanConfirmed','reviewed','confirmed','confirmation'].some(k=>Object.hasOwn(result,k)&&result[k]!==false)) fail();
  const seen=new Set();
  for (const item of result.squares) {
    if (!record(item) || !/^[a-h][1-8]$/.test(item.square) || seen.has(item.square) ||
        !Array.isArray(item.sourcePolygon) || item.sourcePolygon.length!==4 ||
        item.sourcePolygon.some(p=>!Array.isArray(p)||p.length!==2||!p.every(Number.isFinite)||p[0]<-1e-6||p[0]>request.imageSize[0]+1e-6||p[1]<-1e-6||p[1]>request.imageSize[1]+1e-6)) fail();
    seen.add(item.square);
  }
  return result;
}

export function validateManualProvenance(result, request) {
  if (result.model!=='cstr/chess-board-photo-onnx' || result.modelRevision!==MANUAL_MODEL_REVISION ||
      result.pipelineVersion!=='image-order-crops-v1' || result.calibrationId!==request.calibrationId ||
      result.topLeftSquare!==request.topLeftSquare || result.geometryHumanReviewed!==true ||
      JSON.stringify(result.imageSize)!==JSON.stringify(request.imageSize) || !record(result.modelHashes) ||
      Object.keys(result.modelHashes).length!==2 || Object.entries(MANUAL_MODEL_HASHES).some(([k,v])=>result.modelHashes[k]!==v) ||
      !Number.isFinite(result.elapsedMs) || result.elapsedMs<0) fail();
}
