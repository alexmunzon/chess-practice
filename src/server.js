import http from 'node:http';
import { readFile } from 'node:fs/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { loadPosition, positionPayload, movePosition } from './core/position.js';
import { analyze } from './core/engine.js';
import {createHash} from 'node:crypto';
import {parseCalibrationHeader,validateCalibrationRequest,validateCalibrationPreview} from './core/photo-calibration.js';
const root = fileURLToPath(new URL('../', import.meta.url));
const assets = new Map([['/',['index.html','text/html']],['/index.html',['index.html','text/html']],['/src/app.js',['src/app.js','text/javascript']],['/src/styles.css',['src/styles.css','text/css']],['/src/review-state.js',['src/review-state.js','text/javascript']],['/src/position-draft.js',['src/position-draft.js','text/javascript']],['/src/recognition-draft.js',['src/recognition-draft.js','text/javascript']]]);
assets.set('/src/calibration-draft.js',['src/calibration-draft.js','text/javascript']);
export function createServer({analyzer = analyze, recognizer = async (...args) => (await import('./core/photo-recognizer.js')).recognizePhoto(...args), calibrator = async (...args) => (await import('./core/photo-recognizer.js')).calibratePhoto(...args), simulationRecognizer = async (...args) => (await import('./core/photo-recognizer.js')).recognizeSimulation(...args)} = {}) {
  let active = null, generation = 0;
  const invalidate = () => { generation++; active?.abort(); active=null; };
  const server = http.createServer(async(req,res)=> {
    const json = (status,payload) => { if (!res.destroyed && !res.writableEnded) { res.writeHead(status,{'Content-Type':'application/json','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}); res.end(JSON.stringify(payload)); } };
    // Bind to loopback and reject cross-origin browser requests and DNS rebinding.
    const host = req.headers.host || '';
    if (!/^(127\.0\.0\.1|localhost)(:\d+)?$/.test(host)) return json(403,{error:'Loopback host required.'});
    if (req.headers.origin && req.headers.origin !== `http://${host}`) return json(403,{error:'Same-origin requests only.'});
    const path = new URL(req.url,'http://'+host).pathname;
    if (req.method==='GET' && path==='/api/health') return json(200,{ok:true,engine:'Stockfish 19.0.1 single-thread WASM',local:true,maxMovetimeMs:3000});
    if (req.method==='GET' && assets.has(path)) {
      try { const [name,type]=assets.get(path); const data=await readFile(root+name); res.writeHead(200,{'Content-Type':type+'; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'self'; connect-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; frame-ancestors 'none'"}); return res.end(data); } catch { return json(404,{error:'Asset not found.'}); }
    }
    if (req.method==='POST' && ['/api/recognize','/api/calibrate','/api/recognize-simulation'].includes(path)) {
      if (!['image/jpeg','image/png','image/webp'].includes(req.headers['content-type'])) return json(415,{error:'JPEG, PNG or WebP image bytes required.'});
      const declared=Number(req.headers['content-length']);
      if (Number.isFinite(declared) && declared>8*1024*1024) return json(413,{error:'Image must be at most 8 MB.'});
      invalidate(); const current=generation, controller=new AbortController(); active=controller;
      const disconnected=()=>{ if(!res.writableEnded) controller.abort(); }; res.on('close',disconnected);
      try {
        const preview=path==='/api/calibrate';
        const synthetic=path==='/api/recognize-simulation';
        const header=req.headers['x-chess-calibration'];
        if (synthetic && header!==undefined) throw new Error('Synthetic recognition accepts image pixels only.');
        let calibration;
        if (preview || header!==undefined) calibration=parseCalibrationHeader(header,{reviewed:!preview});
        let bytes=0; const parts=[];
        for await (const part of req) { bytes+=part.length; if(bytes>8*1024*1024) return json(413,{error:'Image must be at most 8 MB.'}); parts.push(part); }
        if (!bytes) return json(400,{error:'Image bytes required.'});
        if(current!==generation || controller.signal.aborted) return json(409,{error:'Recognition superseded.',code:'ABORTED'});
        const image=Buffer.concat(parts);
        if (calibration) calibration=validateCalibrationRequest(calibration,{digest:createHash('sha256').update(image).digest('hex'),reviewed:!preview});
        const result=await (preview?calibrator:synthetic?simulationRecognizer:recognizer)(image,{signal:controller.signal,...(calibration?{calibration}:{})});
        if(current!==generation || controller.signal.aborted) return json(409,{error:'Recognition superseded.',code:'ABORTED'});
        if (preview) return json(200,validateCalibrationPreview(result,calibration));
        if(result?.source!==(synthetic?'synthetic-pixel-inference':'real-image-inference') || result.status!=='needs-human-review' || result.guidanceAllowed!==false || result.fen!==null) throw new Error('Recognizer must return a review-only proposal.');
        if(calibration && (result.sourceSha256!==calibration.sourceSha256 || result.calibrationId!==calibration.calibrationId)) throw new Error('Recognition does not match the reviewed calibration.');
        return json(200,result);
      } catch(e) { return json(e.code==='ABORTED'?409:e.code==='TIMEOUT'?504:e.code==='MODEL_UNAVAILABLE'?503:400,{error:e.message,code:e.code || 'RECOGNITION_FAILED'}); }
      finally {res.off('close',disconnected); if(active===controller) active=null;}
    }
    if (req.method!=='POST' || !['/api/position','/api/move','/api/analyze','/api/cancel'].includes(path)) return json(404,{error:'Not found.'});
    if (!req.headers['content-type']?.startsWith('application/json')) return json(415,{error:'JSON required.'});
    try {
      let body=''; for await (const part of req) { body += part; if (body.length>8192) { json(413,{error:'Request too large.'}); return; } }
      const input=JSON.parse(body || '{}');
      if (!input || typeof input!=='object' || Array.isArray(input)) throw new Error('JSON object required.');
      if (path==='/api/cancel') { invalidate(); return json(200,{cancelled:true}); }
      if (path==='/api/position') { invalidate(); return json(200,positionPayload(loadPosition(input.fen))); }
      if (path==='/api/move') { invalidate(); return json(200,movePosition(input)); }
      if (typeof input.requestId!=='string' || input.requestId.length<1 || input.requestId.length>100) throw new Error('A short requestId string is required.');
      invalidate(); const current=generation, controller=new AbortController(); active=controller;
      const disconnected=()=> { if (!res.writableEnded) controller.abort(); };
      res.on('close',disconnected);
      try { const result=await analyzer(input,{signal:controller.signal}); if(current!==generation || controller.signal.aborted) return json(409,{error:'Analysis superseded.',code:'ABORTED'}); json(200,result); }
      finally { res.off('close',disconnected); if(active===controller) active=null; }
    } catch(e) { json(e.code==='ABORTED'?409:e.code==='TIMEOUT'?504:e.code?.startsWith('ENGINE')?503:400,{error:e.message,code:e.code || 'INVALID_REQUEST'}); }
  });
  server.on('close',invalidate);
  server.requestTimeout=60000;
  return server;
}
if (process.argv[1] && import.meta.url===pathToFileURL(process.argv[1]).href) {
  const port=Number(process.env.PORT || 4174);
  const server=createServer(); server.listen(port,'127.0.0.1',()=>console.log(`Chess Practice: http://127.0.0.1:${port}`));
  for (const signal of ['SIGTERM','SIGINT']) process.on(signal,()=>server.close(()=>process.exit(0)));
}
