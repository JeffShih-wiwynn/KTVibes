import {$,api,el} from './shared.js';

export function createInvite(){
 let url='',plain='',pending=false;
 const container=$('remote-url'),link=el('a'),actions=el('span',undefined,'invite-actions'),notice=el('span',undefined,'invite-notice');
 link.target='_blank';link.rel='noopener noreferrer';container.replaceChildren(link,actions,notice);notice.setAttribute('role','status');
 const paths={copy:'<rect x="9" y="9" width="11" height="12" rx="2"/><path d="M15 9V4H4v12h5"/>',share:'<path d="M12 15V3m-4 4 4-4 4 4M5 12v8h14v-8"/>'};
 let timer;
 const inform=text=>{notice.textContent=text;clearTimeout(timer);timer=setTimeout(()=>notice.textContent='',3500);};
 async function copy(){
  try{
   if(navigator.clipboard?.writeText)await navigator.clipboard.writeText(url);
   else{
    const text=el('textarea');text.value=url;text.style.cssText='position:fixed;opacity:0';document.body.append(text);text.select();
    try{if(!document.execCommand('copy'))throw new Error('Clipboard unavailable');}finally{text.remove();}
   }
   inform('Link copied');
  }catch{inform('Could not copy. Open the link to share it.');}
 }
 for(const action of ['copy','share']){
  const button=el('button');button.type='button';button.title=action==='copy'?'Copy invite link':'Share invite link';button.setAttribute('aria-label',button.title);
  button.innerHTML=`<svg viewBox="0 0 24 24" aria-hidden="true">${paths[action]}</svg>`;
  button.onclick=async()=>{
   if(action==='copy'||!navigator.share){await copy();return;}
   try{await navigator.share({title:'KTVibes Remote',url});}catch(error){if(error.name!=='AbortError')await copy();}
  };actions.append(button);
 }
 return async address=>{
  if(pending||url&&plain===address)return;
  pending=true;url='';plain=address;
  link.textContent=plain;
  // Disable the old invite while fetching the new run's credential.
  link.removeAttribute('href');actions.hidden=true;
  try{const invite=await api('/api/invite');if(!invite.url)throw new Error('Invite unavailable');url=invite.url;link.href=url;actions.hidden=false;}
  catch{url='';inform('Invite unavailable');}
  finally{pending=false;}
 };
}
