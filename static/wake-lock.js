// Screen ownership belongs to this Player, independently of the server's sleep inhibitor.
export function createScreenWakeLock() {
 let wanted=false, lock=null, pending=false, stopped=false, retry=null;
 const supported=window.isSecureContext && 'wakeLock' in navigator;
 const needed=()=>wanted && !stopped && document.visibilityState==='visible';
 function later(){
  clearTimeout(retry);
  retry=null;
  if(needed())retry=setTimeout(()=>{retry=null;sync();},5000);
 }
 async function sync(){
  if(!supported)return;
  if(!needed()){
   clearTimeout(retry);retry=null;
   const old=lock;lock=null;
   if(old)try{await old.release();}catch{}
   return;
  }
  if(lock||pending||retry!==null)return;
  pending=true;
  try{
   const next=await navigator.wakeLock.request('screen');
   if(!needed()){try{await next.release();}catch{}return;}
   lock=next;
   next.addEventListener('release',()=>{
    if(lock!==next)return;
    lock=null;later();
   });
  }catch{later();}
  finally{pending=false;}
 }
 const visible=()=>sync();
 const hide=()=>{stopped=true;sync();};
 const show=()=>{stopped=false;sync();};
 document.addEventListener('visibilitychange',visible);
 window.addEventListener('pagehide',hide);
 window.addEventListener('pageshow',show);
 return state=>{
  wanted=!!state?.playing && (!!state.current || (state.upcoming||[]).some(item=>item.status!=='error'));
  sync();
 };
}
