import {el, REDUCED} from './shared.js';

// Keep the current preview immediately selectable while its visual transition finishes.
export function createLyricPreview(block, reading, toggle, names) {
 const label=el('span');toggle.append(label);
 toggle.dataset.widthLabel=names.reduce((longest,name)=>name.length>longest.length?name:longest,'');
 let contents=null,previewAnimations=[],labelAnimation=null,outgoing=null,revision=0;
 function cancelPreview(){
  revision++;
  for(const animation of previewAnimations)animation.cancel();
  previewAnimations=[];outgoing?.remove();outgoing=null;
  block.style.removeProperty('height');block.style.removeProperty('overflow');
 }
 function stop(){cancelPreview();labelAnimation?.cancel();labelAnimation=null;}
 const reduced=()=>{if(REDUCED.matches)stop();};
 REDUCED.addEventListener('change',reduced);
 return {
  label(name){
   if(label.textContent===name)return;
   const animate=!!label.textContent && toggle.isConnected && !REDUCED.matches;
   labelAnimation?.cancel();label.textContent=name;
   if(animate)labelAnimation=label.animate([{opacity:0},{opacity:1}],{duration:180,easing:'ease-out'});
  },
  show(lines){
   const next=JSON.stringify(lines);
   if(next===contents)return;
   const animate=contents!==null && block.isConnected && !REDUCED.matches;
   const before=block.getBoundingClientRect().height;
   cancelPreview();
   const old=animate?reading.cloneNode(true):null;
   contents=next;reading.replaceChildren(...lines.map(line=>el('small',line)));
   if(!animate)return;
   const after=block.getBoundingClientRect().height,token=revision;
   // The outgoing copy is visual only; assistive technology reads the new version immediately.
   old.className='lyric-preview-outgoing';old.setAttribute('aria-hidden','true');old.inert=true;
   outgoing=old;block.append(old);block.style.height=`${before}px`;block.style.overflow='hidden';
   const easing='cubic-bezier(.2,.7,.3,1)';
   previewAnimations=[old.animate([{opacity:1},{opacity:0}],{duration:180,easing,fill:'forwards'}),
    reading.animate([{opacity:0},{opacity:1}],{duration:180,easing}),
    block.animate([{height:`${before}px`},{height:`${after}px`}],{duration:220,easing,fill:'forwards'})];
   Promise.all(previewAnimations.map(animation=>animation.finished)).then(()=>{
    if(token===revision)cancelPreview();
   },()=>{});
  },
  destroy(){stop();REDUCED.removeEventListener('change',reduced);}
 };
}
