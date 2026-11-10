/** Game-neutral review/revocation pattern adapted from Blackjack Practice's confirmed-state boundary. */
export function createReviewState() {
  let revision=0, sequence=0, fen='', confirmed=false, current=null, analysis=null;
  const invalidate=()=>{revision++;confirmed=false;current=null;analysis=null;};
  return Object.freeze({
    setPosition(value){invalidate();fen=value;},
    invalidate,
    confirm(value){current=null;analysis=null;confirmed=value===true;},
    begin(){if(!confirmed||!fen)throw new Error('Confirm a valid position first.');const token=Object.freeze({revision,id:++sequence,fen});current=token;analysis=null;return token;},
    accept(token,result){if(token!==current||token.revision!==revision||!confirmed||result.fen!==fen)return false;analysis=result;current=null;return true;},
    fail(token){if(token!==current)return false;current=null;return true;},
    get(){return {revision,fen,confirmed,pending:current!==null,analysis};}
  });
}
