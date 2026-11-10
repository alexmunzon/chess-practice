const PIECES = /^[prnbqkPRNBQK]$/;
export function createDraft(fen) {
  if (typeof fen !== 'string') throw new Error('FEN required.');
  const parts=fen.trim().split(/\s+/), ranks=parts[0]?.split('/');
  if(parts.length!==6 || ranks.length!==8)throw new Error('Complete FEN required.');
  const board=ranks.map(rank=>{const cells=[];for(const char of rank){if(/^[1-8]$/.test(char))cells.push(...Array(Number(char)).fill(null));else if(PIECES.test(char))cells.push(char);else throw new Error('Invalid piece.');}if(cells.length!==8)throw new Error('Each rank needs eight squares.');return cells;});
  return {board,turn:parts[1],castling:parts[2],ep:parts[3],halfmove:Number(parts[4]),fullmove:Number(parts[5])};
}
export function emptyDraft(){return {board:Array.from({length:8},()=>Array(8).fill(null)),turn:'w',castling:'-',ep:'-',halfmove:0,fullmove:1};}
export function setDraftPiece(draft,square,piece){
  if(!/^[a-h][1-8]$/.test(square)||piece!==null&&!PIECES.test(piece))throw new Error('Invalid square or piece.');
  draft.board[8-Number(square[1])]['abcdefgh'.indexOf(square[0])]=piece;
}
export function draftFen(draft){
  if(!['w','b'].includes(draft.turn))throw new Error('Choose whose turn it is.');
  if(!/^(?:-|K?Q?k?q?)$/.test(draft.castling)||!draft.castling)throw new Error('Invalid castling rights.');
  if(!/^(?:-|[a-h][36])$/.test(draft.ep))throw new Error('Choose a valid en passant target or none.');
  if(!Number.isSafeInteger(draft.halfmove)||draft.halfmove<0||!Number.isSafeInteger(draft.fullmove)||draft.fullmove<1)throw new Error('Move counters must be whole numbers (halfmove ≥ 0, fullmove ≥ 1).');
  if(!Array.isArray(draft.board)||draft.board.length!==8)throw new Error('Eight ranks required.');
  const placement=draft.board.map(rank=>{if(!Array.isArray(rank)||rank.length!==8)throw new Error('Eight files required.');let text='',empty=0;for(const piece of rank){if(piece===null){empty++;continue;}if(typeof piece!=='string'||!PIECES.test(piece))throw new Error('Invalid piece.');if(empty){text+=empty;empty=0;}text+=piece;}return text+(empty||'');}).join('/');
  return `${placement} ${draft.turn} ${draft.castling} ${draft.ep} ${draft.halfmove} ${draft.fullmove}`;
}
