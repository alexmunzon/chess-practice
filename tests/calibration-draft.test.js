import test from 'node:test';
import assert from 'node:assert/strict';
import {calibrationRequest,calibrationHeader,parseCalibrationPreview,imagePoint} from '../src/calibration-draft.js';
const input=()=>({sourceSha256:'a'.repeat(64),imageSize:[800,600],corners:[[100,100],[500,100],[500,500],[100,500]],topLeftSquare:'a8'});
function preview(request=input()) {
  return {...request,schemaVersion:1,source:'manual-image-calibration',status:'needs-geometry-review',calibrationId:'b'.repeat(64),fen:null,guidanceAllowed:false,
    squares:Array.from({length:64},(_,i)=>{const x=100+i%8*50,y=100+Math.floor(i/8)*50;return {square:'abcdefgh'[i%8]+(8-Math.floor(i/8)),sourcePolygon:[[x,y],[x+50,y],[x+50,y+50],[x,y+50]]};})};
}
test('calibration metadata preserves screen-order corners for every explicit orientation',()=>{
  for(const topLeftSquare of ['a8','h8','h1','a1']) {
    const value={...input(),topLeftSquare},request=calibrationRequest(value);
    assert.deepEqual(request.corners,value.corners);assert.equal(request.geometryReviewed,false);
    assert.deepEqual(JSON.parse(calibrationHeader(value)),request);
    const reviewed=JSON.parse(calibrationHeader(value,'c'.repeat(64)));assert.equal(reviewed.geometryReviewed,true);assert.equal(reviewed.calibrationId,'c'.repeat(64));
    assert.equal(reviewed.topLeftSquare,topLeftSquare);assert.ok(calibrationHeader(value).length<4096);
  }
});
test('missing orientation, malformed image metadata and invalid quadrilaterals fail closed',()=>{
  for(const patch of [{topLeftSquare:''},{topLeftSquare:'white-bottom'},{sourceSha256:'bad'},{imageSize:[0,600]},{imageSize:[8000,8000]},
    {corners:[[0,0],[10,10],[0,10],[10,0]]},{corners:[[0,0],[0,0],[0,0],[0,0]]},{corners:[[0,0],[900,0],[900,500],[0,500]]},
    {corners:[[0,0],[100,0],[100,NaN],[0,100]]},{corners:[[0,0],null,null,null]}]) assert.throws(()=>calibrationRequest({...input(),...patch}));
});
test('cyclically rotated corner lists cannot substitute for explicit chess orientation',()=>{
  const corners=input().corners;
  for(let offset=1;offset<4;offset++)assert.throws(()=>calibrationRequest({...input(),corners:[...corners.slice(offset),...corners.slice(0,offset)]}),/screen-image order/);
});
test('preview binding rejects altered source, dimensions, corners, orientation and trusted-state claims',()=>{
  for(const patch of [{sourceSha256:'c'.repeat(64)},{imageSize:[600,800]},{corners:[[0,0],[500,0],[500,500],[0,500]]},{topLeftSquare:'h8'},
    {status:'confirmed'},{guidanceAllowed:true},{fen:'board state'},{calibrationId:'bad'}]) assert.throws(()=>parseCalibrationPreview({...preview(),...patch},input()));
  const accepted=parseCalibrationPreview(preview(),input());assert.equal(accepted.guidanceAllowed,false);assert.equal(accepted.fen,null);assert.equal(accepted.geometryReviewed,false);
});
test('preview requires complete, unique, finite and in-bounds labeled polygons',()=>{
  for(const change of [p=>p.squares.pop(),p=>p.squares[0].square='z9',p=>p.squares[0].square='b8',p=>p.squares[0].sourcePolygon[0][0]=NaN,p=>p.squares[0].sourcePolygon[0][0]=801]) {
    const p=preview();change(p);assert.throws(()=>parseCalibrationPreview(p,input()));
  }
  const p=preview(),accepted=parseCalibrationPreview(p,input());p.squares[0].sourcePolygon[0][0]=400;
  assert.equal(accepted.squares[0].sourcePolygon[0][0],100);
});
test('display coordinates map to natural image pixels without applying a board rotation',()=>{
  assert.deepEqual(imagePoint(110,95,{left:10,top:20,width:400,height:300},[800,600]),[200,150]);
  assert.deepEqual(imagePoint(410,320,{left:10,top:20,width:400,height:300},[800,600]),[800,600]);
  assert.throws(()=>imagePoint(0,0,{left:10,top:20,width:400,height:300},[800,600]));
  assert.throws(()=>imagePoint(10,20,{left:10,top:20,width:0,height:300},[800,600]));
});
