// Each stage owns its brand/QR timer.
export function createBrandRotation(){
let brandTimer=null,brandRotation=false,showBrand=false;
function rotateBrand(enabled){
 if(enabled===brandRotation)return;
 brandRotation=enabled;clearTimeout(brandTimer);brandTimer=null;
 document.body.classList.remove('player-transition');
 document.body.classList.toggle('player-brand-visible',!enabled);
 if(!enabled)return;
 showBrand=false;
 const cycle=()=>{
  document.body.classList.add('player-transition');
  brandTimer=setTimeout(()=>{
   showBrand=!showBrand;
   document.body.classList.toggle('player-brand-visible',showBrand);
   document.body.classList.remove('player-transition');
   brandTimer=setTimeout(cycle,6000);
  },600);
 };
 document.body.classList.remove('player-brand-visible');
 brandTimer=setTimeout(cycle,6000);
}
return rotateBrand;
}
