/** Browser geometry drafts never establish piece identity or historical state. */
const HASH = /^[a-f0-9]{64}$/;
const ORIENTATIONS = new Set(['a8', 'h8', 'h1', 'a1']);
const SQUARES = new Set(Array.from({length:64}, (_,i) => 'abcdefgh'[i%8] + (8-Math.floor(i/8))));
const same = (a,b) => JSON.stringify(a) === JSON.stringify(b);

function dimensions(size) {
  if (!Array.isArray(size) || size.length !== 2 || size.some(n => !Number.isSafeInteger(n) || n < 1 || n > 8192) || size[0]*size[1] > 25_000_000) throw new Error('Wait for a supported photo to finish loading.');
  return [...size];
}

function points(value, size, tolerance=0) {
  if (!Array.isArray(value) || value.length !== 4 || value.some(p => !Array.isArray(p) || p.length !== 2 || p.some(n => !Number.isFinite(n)) || p[0] < -tolerance || p[1] < -tolerance || p[0] > size[0]+tolerance || p[1] > size[1]+tolerance)) throw new Error('Set all four corners inside the photo.');
  return value.map(p => [...p]);
}

export function calibrationRequest({sourceSha256,imageSize,corners,topLeftSquare}) {
  if (typeof sourceSha256 !== 'string' || !HASH.test(sourceSha256)) throw new Error('Load and verify a source photo first.');
  const size=dimensions(imageSize), selected=points(corners,size);
  for (let i=0;i<4;i++) {
    const a=selected[i],b=selected[(i+1)%4],c=selected[(i+2)%4];
    if ((b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0]) <= 1) throw new Error('Corners must form a clockwise, noncrossing board: TL, TR, BR, BL.');
  }
  if ((selected[0][1]+selected[1][1])/2 >= (selected[2][1]+selected[3][1])/2 ||
      (selected[0][0]+selected[3][0])/2 >= (selected[1][0]+selected[2][0])/2) throw new Error('Use screen-image order TL, TR, BR, BL; choose chess orientation separately.');
  if (!ORIENTATIONS.has(topLeftSquare)) throw new Error('Choose the actual chess square at the photo’s top-left board corner.');
  return {sourceSha256,imageSize:size,corners:selected,topLeftSquare,geometryReviewed:false};
}

export function calibrationHeader(input, calibrationId=null) {
  const metadata=calibrationRequest(input);
  if (calibrationId !== null) {
    if (typeof calibrationId !== 'string' || !HASH.test(calibrationId)) throw new Error('A matching grid preview is required.');
    metadata.geometryReviewed=true;metadata.calibrationId=calibrationId;
  }
  const text=JSON.stringify(metadata);
  if (new TextEncoder().encode(text).length > 4096) throw new Error('Calibration metadata exceeds 4 KB.');
  return text;
}

export function parseCalibrationPreview(result, request) {
  const expected=calibrationRequest(request);
  if (!result || result.schemaVersion!==1 || result.source!=='manual-image-calibration' || result.status!=='needs-geometry-review' || result.fen!==null || result.guidanceAllowed!==false ||
      result.sourceSha256!==expected.sourceSha256 || !same(result.imageSize,expected.imageSize) || !same(result.corners,expected.corners) || result.topLeftSquare!==expected.topLeftSquare || typeof result.calibrationId!=='string' || !HASH.test(result.calibrationId)) throw new Error('Grid preview does not match this photo, its corners and orientation.');
  if (!Array.isArray(result.squares) || result.squares.length!==64) throw new Error('Grid preview must contain all 64 labeled squares.');
  const seen=new Set();
  const squares=result.squares.map(cell=>{
    if (!cell || !SQUARES.has(cell.square) || seen.has(cell.square)) throw new Error('Grid preview has missing or repeated square labels.');
    seen.add(cell.square);
    return {square:cell.square,sourcePolygon:points(cell.sourcePolygon,expected.imageSize,1e-6)};
  });
  return {...expected,schemaVersion:1,source:'manual-image-calibration',status:'needs-geometry-review',calibrationId:result.calibrationId,squares,fen:null,guidanceAllowed:false};
}

export function imagePoint(clientX,clientY,rect,imageSize) {
  const [width,height]=dimensions(imageSize);
  if (![clientX,clientY,rect?.left,rect?.top,rect?.width,rect?.height].every(Number.isFinite) || rect.width<=0 || rect.height<=0 || clientX<rect.left || clientY<rect.top || clientX>rect.left+rect.width || clientY>rect.top+rect.height) throw new Error('Select a point inside the displayed photo.');
  return [Math.min(width,Math.round((clientX-rect.left)*width/rect.width*100)/100),Math.min(height,Math.round((clientY-rect.top)*height/rect.height*100)/100)];
}
