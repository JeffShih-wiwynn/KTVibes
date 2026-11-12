// Detect baked-in black bars and fit the visible video to the stage.
const probe=document.createElement('canvas');probe.width=160;probe.height=90;const probeContext=probe.getContext('2d',{willReadFrequently:true});
export function fillFrame(v){
 let bars,samples=0,lastSample=0;
 const reset=()=>{bars=null;samples=0;lastSample=0;v.style.transform='';};
 const apply=()=>{
  if(!bars||!v.videoWidth)return;
  const W=innerWidth,H=innerHeight,w=v.videoWidth,h=v.videoHeight,cw=w*(1-bars.left-bars.right),ch=h*(1-bars.top-bars.bottom);
  const full=Math.max(W/w,H/h),crop=Math.max(W/cw,H/ch)*1.01,scale=crop/full;
  const dx=(bars.right-bars.left)/2*w*crop,dy=(bars.bottom-bars.top)/2*h*crop;
  v.style.transform=scale>1.01?`translate(${dx}px,${dy}px) scale(${scale})`:'';
 };
 const sample=()=>{
  try{probeContext.drawImage(v,0,0,160,90);}catch{return;}
  const {data}=probeContext.getImageData(0,0,160,90),dark=(x0,y0,x1,y1)=>{for(let y=y0;y<y1;y++)for(let x=x0;x<x1;x++){const i=(y*160+x)*4;if(data[i]+data[i+1]+data[i+2]>72)return false;}return true;};
  let top=0,bottom=0,left=0,right=0;
  while(top<45&&dark(0,top,160,top+1))top++;while(bottom<45&&dark(0,89-bottom,160,90-bottom))bottom++;
  while(left<80&&dark(left,0,left+1,90))left++;while(right<80&&dark(159-right,0,160-right,90))right++;
  if(top+bottom>60||left+right>110)return;  // a mostly black frame (fade, title card) says nothing about the bars
  const found={top:top/90,bottom:bottom/90,left:left/160,right:right/160};
  bars=bars?Object.fromEntries(Object.keys(found).map(k=>[k,Math.min(bars[k],found[k])])):found;samples++;apply();
 };
 v.addEventListener('loadstart',reset);
 v.addEventListener('timeupdate',()=>{if(samples<8&&v.currentTime-lastSample>1.5||v.currentTime<lastSample){lastSample=v.currentTime;sample();}});
 addEventListener('resize',apply);
}
