const $=id=>document.getElementById(id);
let worker,ready=false,busy=false,history=[],output,sequence=0;
function status(text){$('status').textContent=text;}
function add(role,text){$('welcome')?.remove();const card=document.createElement('article');card.className=role;const title=document.createElement('strong');title.textContent=role==='user'?'YOU':'JARVIS';const body=document.createElement('p');body.textContent=text;card.append(title,body);$('messages').appendChild(card);while($('messages').children.length>22)$('messages').firstChild.remove();return body;}
function finish(){busy=false;$('send').disabled=!ready;$('stop').hidden=true;$('engine-state').textContent=ready?'ENGINE READY':'ENGINE STANDBY';}
function resetWorker(){worker?.terminate();worker=null;ready=false;finish();$('load').disabled=false;$('load').textContent='Load browser AI ↗';$('progress').hidden=true;}
$('load').onclick=async()=>{
  if(!navigator.gpu){status('WebGPU is unavailable. Try a current Chrome or Edge browser on a supported device. The desktop console is another option.');return;}
  $('load').disabled=true;$('progress').hidden=false;status('Checking your GPU and loading the browser engine…');
  try{
    if(!await navigator.gpu.requestAdapter())throw Error('No compatible GPU adapter is available.');
    worker=new Worker('engine.js',{type:'module'});
    worker.onerror=()=>{resetWorker();status('The browser engine could not start. Check your connection and WebGPU support, then retry.');};
    worker.onmessage=({data})=>{
      if(data.type==='progress'){status(data.text);$('progress').value=data.progress||0;}
      if(data.type==='ready'){ready=true;$('load').textContent='Browser AI loaded';$('progress').hidden=true;status(`Ready · ${data.model}. Questions run on this device.`);finish();}
      if(data.id!==undefined&&data.id!==sequence)return;
      if(data.type==='delta'&&output){output.textContent+=data.text;$('messages').scrollTop=$('messages').scrollHeight;}
      if(data.type==='done'){history.push({role:'assistant',content:output.textContent});history=history.slice(-20);finish();}
      if(data.type==='error'){if(!ready)resetWorker();else finish();status(data.message);if(output&&busy===false&&!output.textContent)output.textContent='No answer was generated. Please try again.';}
    };
    worker.postMessage({type:'load'});
  }catch(error){resetWorker();status(error.message||'Unable to load the local engine.');}
};
$('ask-form').onsubmit=event=>{
  event.preventDefault();if(busy)return;if(!ready){status('Load the browser AI first to start a conversation.');return;}
  const question=$('question').value.trim();if(!question)return;
  busy=true;sequence++;add('user',question);output=add('assistant','');history.push({role:'user',content:question});history=history.slice(-20);$('question').value='';$('send').disabled=true;$('stop').hidden=false;$('engine-state').textContent='THINKING';status('Generating an answer locally…');worker.postMessage({type:'chat',id:sequence,history});
};
$('question').onkeydown=event=>{if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();$('ask-form').requestSubmit();}};
$('stop').onclick=()=>{sequence++;resetWorker();if(output&&!output.textContent)output.textContent='Generation stopped.';status('Stopped. Reload the browser AI to continue; cached model files can be reused.');};
$('clear').onclick=()=>{if(busy)$('stop').click();history=[];$('messages').replaceChildren();status(ready?'New conversation. The engine is ready.':'Conversation cleared. Load the browser AI to begin.');};
document.querySelectorAll('[data-question]').forEach(button=>button.onclick=()=>{$('question').value=button.dataset.question;$('question').focus();});
function clock(){$('clock').textContent=new Date().toLocaleString(undefined,{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});}clock();setInterval(clock,30000);
if(!navigator.gpu)status('This browser does not expose WebGPU. Use a supported Chrome or Edge device, or open the desktop console.');
