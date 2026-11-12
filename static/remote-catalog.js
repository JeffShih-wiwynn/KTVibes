import {$,el,api,clock,REDUCED} from './shared.js';
import {identityForQueue} from './remote-identities.js';
import {emptyNote} from './classic-remote.js';

// Search and Recent share explicit queue actions and the current queue snapshot.
export function createRemoteCatalog({getState,render,toast,haptic,swipes}){
// Songs already prepared on the server, newest first.
// Rebuilt only when the list itself changes, so a just-tapped song keeps its added/failed icon.
let recentShape;
async function loadRecent(){
 try{
  const songs=await api('/api/recent'),shape=songs.map(song=>song.id).join();
  if(shape===recentShape)return;
  recentShape=shape;$('recent').replaceChildren();
  songs.forEach(song=>showResult({...song,channel:song.artist,parsed:{artist:song.artist,title:song.title}},$('recent'),row=>swipeable(row,song)));
  if(!songs.length)$('recent').append(emptyNote('♪','아직 부른 노래가 없어요','Nothing sung yet.'));
 }catch{}
}
// Search in pages of 10; "More results" appends the next page.
let search={query:'',page:0,seen:new Set()},searchRun=0;
const enqueue=async song=>api('/api/queue',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:song.id,artist:song.artist,title:song.title,identity_id:await identityForQueue()})});
const enqueueNext=async song=>api('/api/queue/next',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:song.id,artist:song.artist,title:song.title,identity_id:await identityForQueue()})});
// Queue-copy counts include the current song and every non-failed upcoming item.
function queueCopies(id){return [getState()?.current,...(getState()?.upcoming||[])].filter(item=>item?.id===id&&item.status!=='error').length;}
function syncResultCard(button){
 if(!button?.dataset.videoId)return;
 const id=button.dataset.videoId,count=queueCopies(id),add=button.querySelector('.result-add'),status=button.querySelector('.result-icon'),note=button.querySelector('.result-note');
 const confirming=button.dataset.confirm==='1';button.dataset.queueCount=String(count);
 if(confirming){icon(status,'confirm');add.setAttribute('aria-label',`Confirm adding ${button.dataset.title} to the queue again`);return;}
 if(count){button.classList.add('added');button.classList.remove('failed');
  if(count===1)icon(status,'added');else{status.className='result-icon count';status.textContent=String(count);}
  note?.replaceChildren(el('em',count===1?'예약됨':`${count}회 예약`),` · ${count===1?'queued':'copies queued'}`);
  add.setAttribute('aria-label',`${button.dataset.title}, ${count} ${count===1?'copy':'copies'} in the queue. Activate to add another copy.`);
 }else{
  button.classList.remove('added');if(!button.classList.contains('failed'))icon(status,'add');
  if(!button.classList.contains('failed'))note?.replaceChildren();
  add.setAttribute('aria-label',`Add ${button.dataset.title} to the queue`);
 }
}
function syncResultCards(){document.querySelectorAll('.result[data-video-id]').forEach(syncResultCard);}
function applyQueueItem(item,front=false){
 if(!getState()||!item?.key)return;
 const existingIndex=getState().upcoming.findIndex(candidate=>candidate.key===item.key);
 if(getState().current?.key===item.key||existingIndex>=0&&(!front||existingIndex===0))return;
 const upcoming=getState().upcoming.filter(candidate=>candidate.key!==item.key);
 if(getState().current?.key!==item.key)upcoming.splice(front?0:upcoming.length,0,item);
 render({...getState(),upcoming});
}
// Result button states: add, queued check/count, confirm another, or failed.
const ICONS={add:'<path d="M12 5v14M5 12h14"/>',added:'<path d="M5 12.5l4.5 4.5L19 7.5"/>',confirm:'<path d="M12 5v14M5 12h14"/>',failed:'<circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5M12 16.5v.01"/>'};
function icon(node,name){node.className=`result-icon ${name}`;node.innerHTML=`<svg viewBox="0 0 24 24" aria-hidden="true">${ICONS[name]}</svg>`;}
// Explicit row actions queue the song or move it to the front of the queue.
function showResult(song,list=$('results'),wrap=row=>row,index=-1){
 const b=el('div',undefined,`result${index>=0?' enter':''}`);b.dataset.videoId=song.id;b.dataset.title=song.title;if(index>=0)b.style.setProperty('--i',index);
 const image=el('img');image.src=song.thumbnail;image.alt='';const info=el('div',undefined,'result-info');const title=el('strong',song.title);if(song.cached)title.append(el('span','READY','tag'));const note=el('small',undefined,'result-note classic-only');info.append(title,el('small',`${song.channel} · ${clock(song.duration)}`),note);
 const actions=el('div',undefined,'result-actions'),add=el('button',undefined,'result-add'),status=el('span');add.type='button';add.setAttribute('aria-label',`Add ${song.title} to the queue`);icon(status,'add');add.append(status);add.onclick=async()=>{
  if(b.parentElement?.classList.contains('open')){swipes.close();return;}
  if(add.disabled)return;
  if(queueCopies(song.id)>0&&b.dataset.confirm!=='1'){
   b.dataset.confirm='1';syncResultCard(b);toast(`Add ${song.title} again? Tap the plus button to confirm.`);
   clearTimeout(b.confirmTimer);b.confirmTimer=setTimeout(()=>{delete b.dataset.confirm;syncResultCard(b);},4500);return;
  }
  clearTimeout(b.confirmTimer);delete b.dataset.confirm;add.disabled=true;
  try{const item=await enqueue({id:song.id,...song.parsed});applyQueueItem(item);haptic([10,40,10]);flyToQueue(image);toast(`Added ${song.parsed.title}`);}
  catch(error){icon(status,'failed');b.classList.add('failed');note.replaceChildren("Couldn't add. Try again");toast(error.message,undefined,'err');}finally{add.disabled=false;syncResultCard(b);}
 };
 const next=el('button',undefined,'recent-next');next.type='button';next.setAttribute('aria-label',`Add ${song.title} to play next`);next.title='Play next';next.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 5v14l9-7-9-7zM19 5v14"/></svg>';next.onclick=()=>queueSongNext({id:song.id,...song.parsed},next,image);
 actions.append(add,next);b.append(image,info,actions);list.append(wrap(b));syncResultCard(b);
}
// The thumbnail arcs into whichever queue count is on screen: the outer box moves across evenly,
// the inner one up or down with an overshooting ease, which together trace a curve.
function flyToQueue(source){
 if(REDUCED.matches)return;
 const from=source.getBoundingClientRect(),count=$('queue-count').getBoundingClientRect();
 const target=(document.body.dataset.theme==='classic'?document.querySelector('#tabs [data-tab=queue]'):count.top>60&&count.bottom<innerHeight-90||$('dock').classList.contains('away')?$('queue-count'):$('dock-count')).getBoundingClientRect();
 const outer=el('div'),inner=source.cloneNode();
 inner.style.cssText=`display:block;width:${from.width}px;height:${from.height}px;border-radius:8px;object-fit:cover;box-shadow:0 10px 30px #000a`;
 outer.style.cssText=`position:fixed;left:${from.left}px;top:${from.top}px;z-index:55;pointer-events:none`;
 outer.append(inner);document.body.append(outer);
 const dx=target.left+target.width/2-(from.left+from.width/2),dy=target.top+target.height/2-(from.top+from.height/2);
 outer.animate([{transform:'none'},{transform:`translateX(${dx}px)`}],{duration:650,easing:'cubic-bezier(.3,0,.7,1)',fill:'forwards'});
 inner.animate([{transform:'none',borderRadius:'8px'},{transform:`translateY(${dy}px) scale(.25) rotate(25deg)`,borderRadius:'50%'}],{duration:650,easing:dy>0?'cubic-bezier(.55,-0.5,.9,.5)':'cubic-bezier(.1,.5,.45,1.4)',fill:'forwards'}).onfinish=()=>outer.remove();
}
async function queueSongNext(song,button,image){
 if(button.disabled)return;button.disabled=true;
 try{
  const result=await enqueueNext({id:song.id,artist:song.artist,title:song.title});
  if(result.added||result.moved)applyQueueItem(result.item,true);
  if(result.already_next)toast(`${song.title} is already next`);
  else if(result.moved)toast(`Moved ${song.title} to next`);
  else{toast(`Added ${song.title} as next`);flyToQueue(image);}
  haptic(10);
 }catch(error){toast(error.message,undefined,'err');}
 finally{button.disabled=false;}
}
function swipeable(row,song){
 const wrap=el('div',undefined,'swipe'),del=el('button','Delete','swipe-delete');del.setAttribute('aria-label',`Delete ${song.title} from this device`);
 wrap.append(row,del);
 let start=null,dx=0,dragging=false;
 const swipeStart=8;
 row.addEventListener('pointerdown',e=>{delete row.dataset.dragged;if(e.pointerType==='mouse'&&e.button)return;start={x:e.clientX,y:e.clientY,base:wrap.classList.contains('open')?-swipes.distance:0};dx=start.base;dragging=false;});
 row.addEventListener('pointermove',e=>{
  if(!start)return;const mx=e.clientX-start.x,my=e.clientY-start.y;
  if(!dragging){if(Math.abs(my)>8&&Math.abs(my)>Math.abs(mx)){start=null;return;}if(Math.abs(mx)<swipeStart||Math.abs(mx)<Math.abs(my)*1.2)return;dragging=true;row.setPointerCapture(e.pointerId);wrap.classList.add('dragging');if(swipes.current!==wrap)swipes.close();}
  dx=Math.max(-swipes.distance*1.3,Math.min(0,start.base+mx));row.style.transform=`translateX(${dx}px)`;
 });
 const end=()=>{
  if(!start)return;start=null;wrap.classList.remove('dragging');if(!dragging)return;
  row.dataset.dragged='1';
  if(dx<-swipes.distance/2){wrap.classList.add('open');row.style.transform=`translateX(${-swipes.distance}px)`;swipes.current=wrap;}
  else{wrap.classList.remove('open');row.style.transform='';if(swipes.current===wrap)swipes.current=null;}
 };
 row.addEventListener('pointerup',end);row.addEventListener('pointercancel',end);
 del.onclick=async()=>{
  del.disabled=true;
  try{
   await api(`/api/songs/${song.id}`,{method:'DELETE'});
   if(swipes.current===wrap)swipes.current=null;
   if(!REDUCED.matches)await wrap.animate([{height:`${wrap.offsetHeight}px`,opacity:1},{height:'0px',opacity:0,marginBottom:'-8px'}],{duration:300,easing:'cubic-bezier(.3,0,.8,.15)'}).finished;
   wrap.remove();recentShape=null;toast(`Deleted ${song.title}`);
   if(!$('recent').children.length)loadRecent();
  }catch(error){toast(error.message,undefined,'err');swipes.close();}finally{del.disabled=false;}
 };
 return wrap;
}
async function loadPage(){
 const run=++searchRun,first=!search.page;
 $('more').disabled=true;if(first){$('results').dataset.state='loading';$('results-end').hidden=true;}
 // Placeholder rows hold the space while YouTube answers.
 if(first)$('results').replaceChildren(...Array.from({length:5},()=>{const row=el('div',undefined,'skeleton');row.setAttribute('aria-hidden','true');row.innerHTML='<i></i><div><i></i><i></i></div>';return row;}));
 try{
  const results=(await api(`/api/search?q=${encodeURIComponent(search.query)}&page=${search.page}`)).filter(s=>!search.seen.has(s.id));
  if(run!==searchRun)return;
  if(first)$('results').replaceChildren();
  results.forEach((s,i)=>{search.seen.add(s.id);showResult(s,$('results'),row=>row,i);});
  $('more').hidden=results.length===0||search.page>=9;$('results').dataset.state=search.seen.size?'':'none';
  $('results-end').hidden=!$('more').hidden||!search.seen.size;
  if(!search.seen.size)$('results').append(emptyNote('없음','검색 결과가 없어요','No songs found. Try the title in its original language, or just the artist.'));
  if(first)showResults();
 }catch(error){if(run!==searchRun)return;if(first){$('results').replaceChildren();$('results').dataset.state='';}toast(error.message,undefined,'err');}finally{$('more').disabled=false;}
}
// Autocomplete from YouTube's search box: type to see completions, tap or arrow+Enter to search one.
let suggestTimer,suggestRun=0,suggestIndex=-1;
function hideSuggestions(){$('suggestions').hidden=true;$('query').setAttribute('aria-expanded','false');suggestIndex=-1;}
function pickSuggestion(text){$('query').value=text;hideSuggestions();$('search-form').requestSubmit();}
function markSuggestion(index){const items=[...$('suggestions').children];suggestIndex=(index+items.length+1)%(items.length+1)-1;items.forEach((li,i)=>li.setAttribute('aria-selected',i===suggestIndex));}
$('query').oninput=()=>{
 clearTimeout(suggestTimer);const q=$('query').value.trim(),run=++suggestRun;$('clear').hidden=!$('query').value;
 if(!q)return hideSuggestions();
 suggestTimer=setTimeout(async()=>{
  const list=await api(`/api/suggest?q=${encodeURIComponent(q)}`).catch(()=>[]);
  if(run!==suggestRun||document.activeElement!==$('query'))return;
  $('suggestions').replaceChildren(...list.map(text=>{const li=el('li'),typed=text.toLowerCase().startsWith(q.toLowerCase())?text.slice(0,q.length):'';li.append(typed,el('b',text.slice(typed.length)));li.setAttribute('role','option');li.onpointerdown=e=>{e.preventDefault();pickSuggestion(text);};return li;}));
  suggestIndex=-1;$('suggestions').hidden=!list.length;$('query').setAttribute('aria-expanded',String(!!list.length));
 },150);
};
$('query').onkeydown=e=>{
 if($('suggestions').hidden)return;
 if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();markSuggestion(suggestIndex+(e.key==='ArrowDown'?1:-1));}
 else if(e.key==='Enter'&&suggestIndex>=0){e.preventDefault();pickSuggestion($('suggestions').children[suggestIndex].textContent);}
 else if(e.key==='Escape')hideSuggestions();
};
$('query').onblur=()=>setTimeout(hideSuggestions,100);
$('clear').onclick=()=>{$('query').value='';$('clear').hidden=true;searchRun++;$('results').replaceChildren();$('more').hidden=$('results-end').hidden=true;$('query').focus();};
$('search-form').onsubmit=e=>{
 e.preventDefault();suggestRun++;hideSuggestions();search={query:$('query').value.trim(),page:0,seen:new Set()};$('more').hidden=true;loadPage();
 $('query').blur();showResults();  // drop the keyboard so results have the screen
};
// Search stays pinned but results don't: from further down, bring them up under the bar.
function showResults(){
 const gap=$('results').getBoundingClientRect().top-($('search-form').getBoundingClientRect().bottom+12);
 if(gap<0)scrollBy({top:gap,behavior:REDUCED.matches?'auto':'smooth'});
}
$('more').onclick=()=>{search.page++;loadPage();};

return {loadRecent,syncResultCards,swipeable};
}
