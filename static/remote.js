import {createRemoteCatalog} from './remote-catalog.js';
import {createSwipeState} from './swipe-state.js';
import {createLyricsPanel} from './remote-lyrics.js';
import {createRemoteQueue} from './remote-queue.js';
import {createRemoteStatus} from './remote-status.js';
import {renderRequester} from './requester.js';
import {classicRemote,toastParts,secondsLeft} from './classic-remote.js';
import {$,el,connect,api,clock,throttle,syncRanges,REDUCED,thumbnail} from './shared.js';
let state,classicUi,seekDrag=null,seekPending=null;
const SPRING='cubic-bezier(.38,1.21,.22,1)';
const haptic=pattern=>{try{navigator.vibrate?.(pattern);}catch{}};
function showImage(img,src){if(img.getAttribute('src')!==src){if(src)img.src=src;else img.removeAttribute('src');}img.hidden=!src;}
const remoteStatus = createRemoteStatus();
const swipes = createSwipeState();
const lyricsPanel = createLyricsPanel({getState: () => state, toast});
// One toast for every message; an action (Undo) keeps it up a little longer.
let toastTimer;
function toast(text,action,kind){
 // Classic dresses the same message as the machine's toast: a label key, the title in bold, a Korean line.
 if(document.body.dataset.theme==='classic'){const parts=toastParts(text,kind);$('toast-key').textContent=parts.key;$('toast-key').className=`toast-key classic-only ${parts.tone}`;$('toast-text').replaceChildren(...parts.body);$('toast').classList.toggle('err',kind==='err');}
 else $('toast-text').textContent=text;
 $('toast').style.setProperty('--toast-ms',`${action?6000:2600}ms`);$('toast-action').hidden=!action;
 if(action){$('toast-action').textContent=action.label;$('toast-action').onclick=()=>{$('toast').classList.remove('on');action.run();};}
 $('toast').classList.add('on');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').classList.remove('on'),action?6000:2600);
}
const send = connect('remote', {
 onState: render,
 onError: message => toast(message, undefined, 'err'),
 onOpen: remoteStatus.onOpen,
 onClose: remoteStatus.onClose
});
const queue = createRemoteQueue({
 getState: () => state, setState: next => { state = next; },
 send, toast, haptic, swipes, pickLyrics: lyricsPanel.open,
 openSongbook: () => classicUi?.setTab('book')
});
const catalog = createRemoteCatalog({getState:()=>state,render,toast,haptic,swipes});
function render(next){
 const before=state;state=next;state.received=Date.now()/1000;if(seekPending&&state.seek_id!==seekPending.seekId)seekPending=null;lyricsPanel.onState(before,state);
 // The header pill reports the TV, since that decides whether anything can play.
 remoteStatus.render(state);
 document.body.dataset.theme=state.theme||'default';showNow(!before);showControls(before);queue.render(before);showClassic();classicUi?.render(state);catalog.syncResultCards();
 const ready=[state.current,...state.upcoming].filter(i=>i?.status==='ready').map(i=>i.key).join();
 if(ready!==readyKeys){readyKeys=ready;catalog.loadRecent();classicUi?.loadBook();}
}
// Now playing: a card at the top, handing over to the dock once scrolled away.
function showNow(first){
 const c=state.current,art=c?thumbnail(c.id):'';
 showHero(!!c,first);$('hero').classList.toggle('paused',!state.playing);$('hero-state').textContent=state.playing?'NOW SINGING':'PAUSED';
 for(const id of ['hero-play','dock-play']){$(id).classList.toggle('playing',!!(c&&state.playing));$(id).setAttribute('aria-label',state.playing?'Pause':'Play');$(id).disabled=!c;}
 $('hero-lyrics').disabled=$('dock-lyrics').disabled=!c;
 $('dock-now').setAttribute('aria-label',c?'Jump to currently playing song':'Open settings');
 // The card keeps its last song while it folds away.
 for(const id of c?['hero-art','hero-glow','dock-art']:['dock-art'])showImage($(id),art);
 if(c){$('hero-title').textContent=c.title;$('hero-artist').textContent=c.artist;}$('hero-length').textContent=clock(c?.duration);
 $('hero-offset').textContent=`${Number(state.offset)>=0?'+':''}${Number(state.offset||0).toFixed(1)}s`;$('hero-offset-earlier').disabled=$('hero-offset-later').disabled=!c;
 $('dock-title').textContent=c?.title||'Nothing playing';$('dock-artist').textContent=c?.artist||'';
 renderRequester($('hero-requester'),c);renderRequester($('dock-requester'),c,true);
 if(c?.requester?.name)$('dock-now').setAttribute('aria-label',`Jump to currently playing song. Requested by ${c.requester.name}`);
 showPosition();
}
// The card unfolds when a song starts on an empty stage and folds away when the stage empties:
// height, padding and margin open with a soft spring while the card fades and scales up.
let heroShown=false;
function showHero(on,first){
 if(on===heroShown)return;heroShown=on;
 const hero=$('hero');for(const animation of hero.getAnimations())animation.cancel();
 if(first||REDUCED.matches){hero.hidden=!on;return;}
 hero.hidden=false;
 const closed={height:'0px',paddingTop:'0px',paddingBottom:'0px',marginTop:'0px',opacity:0,transform:'scale(.94)'},open={height:`${hero.offsetHeight}px`,opacity:1,transform:'none'};
 const animation=on?hero.animate([closed,{opacity:1,offset:.6},open],{duration:600,easing:SPRING}):hero.animate([open,{opacity:0,offset:.5},closed],{duration:400,easing:'cubic-bezier(.4,0,.2,1)'});
 if(!on)animation.onfinish=()=>{if(!heroShown)hero.hidden=true;};
}
// Estimate the TV position between its two-second progress reports.
function showPosition(){
 if(!state)return;
 const live=state.current&&state.playing&&state.position>0?Date.now()/1000-state.received:0;
 let position=Math.min(state.position+live,state.current?.duration||0);
 if(seekDrag?.mode==='horizontal')position=seekDrag.preview;
 else if(seekPending){if(state.current?.key!==seekPending.key||Date.now()>seekPending.expires)seekPending=null;else position=seekPending.position;}
 const section=$('skip'),points=state.sections;
 const intro=!!(points&&position<points.intro),label=intro?'Skip intro':'Next song';
 section.querySelector('span').textContent=label;section.setAttribute('aria-label',label);section.title=label;section.dataset.kind=intro?'intro':'next';
 section.querySelector('path').setAttribute('d',intro?'m4 6 7 6-7 6M12 6l7 6-7 6':'m4 6 7 6-7 6M12 6l7 6-7 6M21 6v12');
 const waiting=(state.transition_until||0)>(state.server_time||0)+(Date.now()/1000-state.received);
 section.disabled=!state.current||waiting||!!state.intro_pending||!!state.next_pending||!state.player_audio;
 const fraction=state.current?.duration?position/state.current.duration:0;
 for(const id of ['hero-bar','dock-bar'])$(id).style.setProperty('--p',fraction);
 $('hero-bar').classList.toggle('scrubbing',seekDrag?.mode==='horizontal');
 $('hero-position').textContent=clock(position);$('hero-bar').setAttribute('aria-valuetext',clock(position));$('hero-bar').setAttribute('aria-valuenow',position);$('hero-bar').setAttribute('aria-valuemax',state.current?.duration||0);
}
setInterval(showPosition,500);
const seekBar=$('hero-bar');
seekBar.onpointerdown=e=>{
 if(!state?.current?.duration||(e.pointerType==='mouse'&&e.button!==0))return;
 const box=seekBar.getBoundingClientRect(),position=Math.min(state.position+(state.playing?Date.now()/1000-state.received:0),state.current.duration),thumb=box.left+(position/state.current.duration)*box.width;
 if(Math.abs(e.clientX-thumb)>22)return;
 seekDrag={id:e.pointerId,key:state.current.key,x:e.clientX,y:e.clientY,mode:'pending',preview:position};seekBar.setPointerCapture(e.pointerId);
};
seekBar.onpointermove=e=>{
 if(!seekDrag||seekDrag.id!==e.pointerId)return;
 const dx=e.clientX-seekDrag.x,dy=e.clientY-seekDrag.y;
 if(seekDrag.mode==='pending'&&Math.max(Math.abs(dx),Math.abs(dy))>=8){
  if(Math.abs(dx)>Math.abs(dy)*1.2)seekDrag.mode='horizontal';
  else if(Math.abs(dy)>Math.abs(dx)*1.2)seekDrag.mode='vertical';
 }
 if(seekDrag.mode==='horizontal'&&state.current?.key===seekDrag.key){const box=seekBar.getBoundingClientRect();seekDrag.preview=Math.max(0,Math.min(1,(e.clientX-box.left)/box.width))*state.current.duration;showPosition();}
};
seekBar.onpointerup=e=>{
 if(!seekDrag||seekDrag.id!==e.pointerId)return;
 const drag=seekDrag;seekDrag=null;
 if(drag.mode==='horizontal'&&state.current?.key===drag.key){seekPending={key:drag.key,position:drag.preview,seekId:state.seek_id,expires:Date.now()+1500};send({action:'seek',position:drag.preview});}
 showPosition();
};
seekBar.onpointercancel=e=>{if(seekDrag?.id===e.pointerId)seekDrag=null;showPosition();};
$('hero-bar').onkeydown=e=>{const step={ArrowLeft:-5,ArrowRight:5}[e.key];if(step&&state?.current){e.preventDefault();send({action:'seek',position:state.position+step});}};
for(const [id,delta] of [['hero-offset-earlier',-.5],['hero-offset-later',.5]])$(id).onclick=()=>{if(state?.current)send({action:'offset',delta});};
const playPause=()=>{haptic(8);send({action:state?.playing?'pause':'play'});};
$('hero-play').onclick=$('dock-play').onclick=playPause;
$('skip').onclick=()=>{if(state?.current){haptic(12);send({action:'skip_'+$('skip').dataset.kind,key:state.current.key});$('skip').disabled=true;}};
// The dock hides while the card is on screen; when the card leaves, the dock rises and its art drops in.
let heroVisible=false;
new IntersectionObserver(([entry])=>{
 const was=heroVisible;heroVisible=entry.isIntersecting;$('dock').classList.toggle('away',heroVisible);
 if(was&&!heroVisible&&!REDUCED.matches){
  $('dock-art').animate([{transform:'translateY(-24px) scale(1.2)',opacity:0},{transform:'none',opacity:1}],{duration:450,delay:120,easing:'cubic-bezier(.34,1.3,.64,1)',fill:'backwards'});
  $('dock').querySelector('.info').animate([{opacity:0,transform:'translateX(-8px)'},{opacity:1,transform:'none'}],{duration:350,delay:200,easing:'ease-out',fill:'backwards'});
 }
},{rootMargin:'0px 0px -40px 0px'}).observe($('hero'));
$('dock-now').onclick=()=>state?.current?$('hero').scrollIntoView({behavior:REDUCED.matches?'auto':'smooth',block:'center'}):openSheet();
$('dock-lyrics').onclick=()=>{if(state?.current)lyricsPanel.open(state.current,{followCurrent:true});};
$('dock-queue').onclick=()=>$('queue').scrollIntoView({behavior:REDUCED.matches?'auto':'smooth',block:'center'});
// Reactions float up on this phone and on the TV. Quick taps add up into one "×3" note.
for(const button of document.querySelectorAll('.react'))button.onclick=()=>{
 const emoji=button.dataset.emoji;send({action:'react',value:emoji});haptic(6);
 const box=button.getBoundingClientRect(),count=REDUCED.matches?1:5;
 for(let i=0;i<count;i++){
  const float=el('span',emoji,'float');float.style.left=`${box.left+box.width/2-15}px`;float.style.top=`${box.top}px`;document.body.append(float);
  const drift=(Math.random()-.5)*90,rise=160+Math.random()*120,spin=(Math.random()-.5)*50;
  float.animate([{transform:'scale(.4)',opacity:0},{transform:`translate(${drift*.3}px,-40px) scale(1.25) rotate(${spin*.3}deg)`,opacity:1,offset:.2},{transform:`translate(${drift}px,-${rise}px) scale(.9) rotate(${spin}deg)`,opacity:0}],
   {duration:REDUCED.matches?300:1100+Math.random()*400,delay:i*70,easing:'cubic-bezier(.2,.7,.3,1)',fill:'both'}).onfinish=()=>float.remove();
 }
 if(!REDUCED.matches)button.animate([{transform:'scale(1)'},{transform:'scale(1.3) rotate(-8deg)'},{transform:'scale(1)'}],{duration:400,easing:'cubic-bezier(.42,1.67,.21,.9)'});
 clearTimeout(button.timer);button.taps=(button.taps||0)+1;
 button.timer=setTimeout(()=>{toast(`Sent ${emoji}${button.taps>1?` ×${button.taps}`:''} to the device`);button.taps=0;},600);
};
// Controls sheet: mix, key, speed and TV display.
function showControls(before){
 for(const id of ['key-down','key-up'])$(id).disabled=!state.current;
 for(const [id,value] of [['vocal',state.vocal],['music',state.music],['speed',state.speed],['lyric-scale',state.lyric_scale]]){
  if(document.activeElement!==$(id)&&!gliding)$(id).value=value;$(`${id}-value`).textContent=`${Math.round(value*100)}%`;
 }
 for(const b of document.querySelectorAll('.presets button'))b.setAttribute('aria-pressed',Math.abs(b.dataset.vocal-state.vocal)<.005&&Math.abs(b.dataset.music-state.music)<.005);
 $('key-down').disabled||=state.key<=-6;$('key-up').disabled||=state.key>=6;
 if(state.key!==before?.key)rollKey(state.key,before?state.key-before.key:0);
 for(const seg of SEGMENTED){
  for(const b of seg.querySelectorAll('button')){b.setAttribute('aria-pressed',b.dataset.value===state[seg.dataset.action]);if(seg.dataset.action==='guide')b.hidden=!(state.guides||[]).includes(b.dataset.value);}
  if(document.body.classList.contains('sheet-open')||state.theme==='classic')placePill(seg);  // openSheet measures the rest; in Classic the settings are a page
 }
 syncRanges();
}
function rollKey(key,direction){
 const roll=$('roll'),old=roll.lastElementChild,next=el('span',key>0?`+${key}`:String(key));
 // Quick taps: drop anything still rolling out, roll the newest number away.
 while(roll.firstElementChild!==old)roll.firstElementChild.remove();
 roll.append(next);
 if(direction&&!REDUCED.matches){
  const d=Math.sign(direction);
  old.animate([{transform:'none',opacity:1},{transform:`translateY(${-60*d}px) scale(.6)`,opacity:0}],{duration:350,easing:'cubic-bezier(.4,0,.2,1)',fill:'forwards'}).onfinish=()=>old.remove();
  next.animate([{transform:`translateY(${60*d}px) scale(.6)`,opacity:0},{transform:'none',opacity:1}],{duration:500,easing:'cubic-bezier(.34,1.56,.64,1)'});
 }else old.remove();
 $('key-note').classList.toggle('orig',key===0);$('key-note').textContent=key===0?'Original key':`${Math.abs(key)} semitone${Math.abs(key)>1?'s':''} ${key>0?'higher':'lower'}`;
}
$('key-down').onclick=()=>{haptic(8);send({action:'key',value:state.key-1});};
$('key-up').onclick=()=>{haptic(8);send({action:'key',value:state.key+1});};
$('key-reset').onclick=()=>{send({action:'speed',value:1});send({action:'key',value:0});};
function dragOnlyRange(input){
 const control=el('div',undefined,'range-control'),hit=el('div',undefined,'range-hit');
 input.before(control);control.append(input,hit);hit.setAttribute('aria-hidden','true');
 let gesture=null;
 const geometry=()=>{
  const rect=input.getBoundingClientRect(),classicMix=document.body.dataset.theme==='classic'&&input.closest('.mixline'),left=rect.left+(classicMix?52:2),width=Math.max(1,rect.width-(classicMix?62:4));
  return {left,width};
 };
 const ratio=()=>{const min=Number(input.min)||0,max=Number(input.max)||100;return Math.max(0,Math.min(1,(Number(input.value)-min)/(max-min||1)));};
 const update=x=>{
  const {left,width}=geometry(),min=Number(input.min)||0,max=Number(input.max)||100,step=Number(input.step)||0,value=min+Math.max(0,Math.min(1,(x-left)/width))*(max-min);
  input.value=String(step?min+Math.round((value-min)/step)*step:value);
  input.dispatchEvent(new Event('input',{bubbles:true}));
 };
 hit.onpointerdown=e=>{
  if(input.disabled||(e.pointerType==='mouse'&&e.button!==0))return;
  const {left,width}=geometry(),thumb=left+ratio()*width;
  if(Math.abs(e.clientX-thumb)>22)return;
  input.focus({preventScroll:true});gesture={id:e.pointerId,x:e.clientX,y:e.clientY,mode:'pending'};hit.setPointerCapture(e.pointerId);
 };
 hit.onpointermove=e=>{
  if(!gesture||gesture.id!==e.pointerId)return;
  const dx=e.clientX-gesture.x,dy=e.clientY-gesture.y;
  if(gesture.mode==='pending'&&Math.max(Math.abs(dx),Math.abs(dy))>=8){
   if(Math.abs(dx)>Math.abs(dy)*1.2)gesture.mode='horizontal';
   else if(Math.abs(dy)>Math.abs(dx)*1.2)gesture.mode='vertical';
  }
  if(gesture.mode==='horizontal')update(e.clientX);
 };
 const finish=e=>{if(gesture?.id===e.pointerId)gesture=null;};
 hit.onpointerup=finish;hit.onpointercancel=finish;
}
for(const id of ['vocal','music','speed','lyric-scale'])dragOnlyRange($(id));
for(const [id,action] of [['vocal','vocal'],['music','music'],['speed','speed'],['lyric-scale','lyric_scale']]){const sendValue=throttle(value=>send({action,value}));$(id).oninput=()=>sendValue(Number($(id).value));}
// Presets set both sliders, gliding there so the change is visible; A cappella is the singer alone.
let gliding=false;
for(const b of document.querySelectorAll('.presets button'))b.onclick=()=>{
 const to=[Number(b.dataset.vocal),Number(b.dataset.music)],from=[Number($('vocal').value),Number($('music').value)],start=performance.now();
 haptic(6);send({action:'vocal',value:to[0]});send({action:'music',value:to[1]});
 if(REDUCED.matches)return;
 gliding=true;
 const step=now=>{
  const k=Math.min(1,(now-start)/350),e=1-(1-k)**3;
  $('vocal').value=from[0]+(to[0]-from[0])*e;$('music').value=from[1]+(to[1]-from[1])*e;syncRanges();
  if(k<1)requestAnimationFrame(step);else{gliding=false;if(state)showControls(state);}
 };
 requestAnimationFrame(step);
};
// Segmented: room display settings and the pronunciation guide.
const SEGMENTED=document.querySelectorAll('.seg');
function placePill(seg){
 const on=seg.querySelector('[aria-pressed=true]:not([hidden])'),pill=seg.querySelector('.pill');pill.hidden=!on;
 if(!on||!on.offsetWidth)return;
 pill.style.width=`${on.offsetWidth}px`;pill.style.transform=`translateX(${on.offsetLeft-3}px)`;
 // Slide only once the pill has a place, so it doesn't sweep in from the left on load.
 if(!seg.classList.contains('ready'))requestAnimationFrame(()=>seg.classList.add('ready'));
}
for(const seg of SEGMENTED)seg.onclick=e=>{const b=e.target.closest('button');if(b){haptic(6);send({action:seg.dataset.action,value:b.dataset.value});}};
// A control measured while hidden (the Classic settings tab, a closed sheet) gets its pill once it has a size.
addEventListener('resize',()=>SEGMENTED.forEach(placePill));
{const sized=new ResizeObserver(entries=>entries.forEach(entry=>placePill(entry.target)));SEGMENTED.forEach(seg=>sized.observe(seg));}
$('hero-lyrics').onclick=()=>{if(state?.current)lyricsPanel.open(state.current,{followCurrent:true});};
function openSheet(){document.body.classList.add('sheet-open');$('sheet').inert=false;haptic(8);requestAnimationFrame(()=>SEGMENTED.forEach(placePill));}
function closeSheet(){document.body.classList.remove('sheet-open');$('sheet').inert=true;}
$('open-controls').onclick=()=>document.body.dataset.theme==='classic'?classicUi.setTab('settings'):openSheet();
$('scrim').onclick=closeSheet;
let suppressHandleClick=false;
$('sheet-handle').onclick=()=>{if(suppressHandleClick){suppressHandleClick=false;return;}closeSheet();};
// Classic theme: room time in Settings. Classic is always two-line lyrics.
function showClassic(){const on=state.theme==='classic';$('room-time').hidden=!on;document.querySelector('[data-action=lyric_mode]').closest('.seg-row').hidden=on;roomLeft();}
function roomLeft(){if(!state?.room_ends)return;const left=secondsLeft(state),end=new Date(state.room_ends*1000).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});
 if(state.theme==='classic'){const lcd=el('span',String(Math.ceil(left/60)).padStart(3,'0'),'lcd');lcd.dataset.ghost='888';$('room-left').replaceChildren(lcd,el('span','분','u'));$('room-time').classList.toggle('up',!left);$('room-end').textContent=left?`종료 예정\n${end}`:'시간 종료\nTIME\'S UP';return;}
 $('room-left').textContent=left?`${Math.ceil(left/60)}분 left`:'Time is up';$('room-end').textContent=`${end} 종료`;}
setInterval(roomLeft,1000);
for(const b of document.querySelectorAll('[data-minutes]'))b.onclick=()=>{haptic(6);send({action:'add_time',minutes:+b.dataset.minutes});};
addEventListener('keydown',e=>{if(e.key!=='Escape')return;if(lyricsPanel.isOpen)lyricsPanel.close();else if(document.body.classList.contains('sheet-open'))closeSheet();});
// Drag only the handle to dismiss the settings sheet, leaving the content area free to scroll.
{
 const sheet=$('sheet'),handle=$('sheet-handle');let startY=null,movedHandle=false;
 handle.onpointerdown=e=>{if(document.body.dataset.theme==='classic'||(e.pointerType==='mouse'&&e.button!==0))return;e.preventDefault();startY=e.clientY;movedHandle=false;sheet.style.transition='none';handle.setPointerCapture(e.pointerId);};
 handle.onpointermove=e=>{if(startY===null)return;const distance=Math.max(0,e.clientY-startY);if(distance>8)movedHandle=true;sheet.style.transform=`translateY(${distance}px)`;};
 handle.onpointerup=e=>{if(startY===null)return;const distance=e.clientY-startY;startY=null;sheet.style.transition='';sheet.style.transform='';suppressHandleClick=movedHandle;if(movedHandle)setTimeout(()=>{suppressHandleClick=false;},300);if(distance>100)closeSheet();};
 handle.onpointercancel=()=>{startY=null;sheet.style.transition='';sheet.style.transform='';};
}
// Queue. Rebuilt only when its songs or statuses change, so position reports never swap a button
// out from under a tap; preparation progress updates in place. A drag holds rebuilds until it ends.
let readyKeys;
// Keep the page's end clear of the dock, whatever its height.
new ResizeObserver(()=>document.body.style.setProperty('--dock',`${$('dock').offsetHeight}px`)).observe($('dock'));
classicUi=classicRemote({send,toast,haptic,swipeable:catalog.swipeable});if(state)classicUi.render(state);
