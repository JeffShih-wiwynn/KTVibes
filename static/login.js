const form=document.querySelector('form'),button=form.querySelector('[type=submit]'),message=document.getElementById('message');
const key=new URLSearchParams(location.hash.slice(1)).get('key');
if(location.hash)history.replaceState(null,'',location.pathname+location.search);
async function authenticate(endpoint,body){
 button.disabled=true;
 try{
  const response=await fetch(`/api/auth/${endpoint}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const result=await response.json();
  if(!response.ok)throw new Error(result.detail||'Could not sign in.');
  location.replace(location.pathname.startsWith('/remote')?'/remote':'/');
 }catch(error){message.textContent=error.message;button.disabled=false;}
}
form.onsubmit=event=>{event.preventDefault();authenticate('login',{password:document.getElementById('password').value});};
if(key){message.textContent='Connecting…';authenticate('pair',{key});}

const input=document.getElementById('password'),keypad=document.getElementById('keypad');
fetch('/api/auth/status').then(response=>response.json()).then(status=>{
 if(status.credential_type!=='pin')return;
 form.querySelector('label').textContent='PIN';
 input.inputMode='numeric';input.pattern='[0-9]{6,}';input.minLength=6;
 for(const digit of ['1','2','3','4','5','6','7','8','9','','0','⌫']){
  const key=document.createElement('button');key.type='button';key.textContent=digit;key.disabled=!digit;
  key.setAttribute('aria-label',digit==='⌫'?'Backspace':digit||'Blank');
  key.onclick=()=>{input.value=digit==='⌫'?input.value.slice(0,-1):input.value.length<input.maxLength?input.value+digit:input.value;input.dispatchEvent(new Event('input'));};
  keypad.append(key);
 }
 keypad.hidden=false;
}).catch(()=>{});
