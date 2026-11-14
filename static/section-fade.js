// A separate output gain preserves the singer's music/vocal mix.
export function createSectionFade(context, output, finish, video){
 const gain=context.createGain();gain.connect(output);
 let timer=null,running=false,visual=null;
 function reset(){
  visual?.cancel();visual=null;
  clearTimeout(timer);timer=null;running=false;
  gain.gain.cancelScheduledValues(context.currentTime);
  gain.gain.setValueAtTime(1,context.currentTime);
 }
 function ramp(from,to){
  visual?.cancel();
  if(video)visual=video.animate([{opacity:from},{opacity:to}],{duration:1500,easing:'linear',fill:'forwards'});
  const now=context.currentTime;
  gain.gain.cancelScheduledValues(now);
  gain.gain.setValueAtTime(from,now);
  gain.gain.linearRampToValueAtTime(to,now+1.5);
 }
 function run(kind,seek=()=>{},done=()=>{}){
  if(running)return;
  reset();running=true;
  ramp(1,0);
  timer=setTimeout(()=>{
   visual?.finish();
   if(kind==='next'){running=false;finish();return;}
   seek();
   ramp(0,1);
   timer=setTimeout(()=>{reset();done();},1500);
  },1500);
 }
 return {gain,run,reset};
}
