const $=id=>document.getElementById(id);
let worker,ready=false,busy=false,history=[],output,sequence=0;
function status(text){$('status').textContent=text;}
function engineState(label,mode){
  $('engine-state').textContent=label;
  $('ai-core').dataset.engine=mode;
  $('model-status').textContent=mode==='loading'?'Downloading':ready?'Loaded':'On demand';
  if($('local-mode').hidden)$('connection-state').toggleAttribute('data-online',ready);
}
function asksForInbox(text){
  return /\b(?:my|unread|recent|latest)\s+(?:unread\s+)?(?:e-?mails?|inbox)\b|\b(?:read|check|show|summarize|summarise)\b.{0,30}\binbox\b/i.test(text);
}
function add(role,text){$('welcome')?.remove();const card=document.createElement('article');card.className=role;const title=document.createElement('strong');title.textContent=role==='user'?'YOU':'JARVIS';const body=document.createElement('p');body.textContent=text;card.append(title,body);$('messages').appendChild(card);while($('messages').children.length>22)$('messages').firstChild.remove();return body;}
function finish(){busy=false;$('send').disabled=!ready;$('stop').hidden=true;engineState(ready?'Ready':'Standby',ready?'ready':'standby');}
function resetWorker(){worker?.terminate();worker=null;ready=false;finish();$('load').disabled=false;$('load').textContent='Load browser AI';$('progress').hidden=true;}
$('load').onclick=async()=>{
  if(!navigator.gpu){status('WebGPU is unavailable. Try a current Chrome or Edge browser on a supported device. The desktop console is another option.');return;}
  $('load').disabled=true;$('progress').hidden=false;engineState('Loading model','loading');status('Checking your GPU and loading the browser engine…');
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
  if(asksForInbox(question)){
    add('user',question);
    add('assistant','Choose Use local PC at the top of the page to pair JARVIS and read your Gmail on your PC.');
    $('question').value='';
    return;
  }
  busy=true;sequence++;add('user',question);output=add('assistant','');history.push({role:'user',content:question});history=history.slice(-20);$('question').value='';$('send').disabled=true;$('stop').hidden=false;engineState('Thinking','thinking');status('Generating an answer locally…');worker.postMessage({type:'chat',id:sequence,history});
};
$('question').onkeydown=event=>{if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();$('ask-form').requestSubmit();}};
$('stop').onclick=()=>{sequence++;resetWorker();if(output&&!output.textContent)output.textContent='Generation stopped.';status('Stopped. Reload the browser AI to continue; cached model files can be reused.');};
$('clear').onclick=()=>{if(busy)$('stop').click();history=[];$('messages').replaceChildren();status(ready?'New conversation. The engine is ready.':'Conversation cleared. Load the browser AI to begin.');};
document.querySelectorAll('[data-question]').forEach(button=>button.onclick=()=>{$('question').value=button.dataset.question;$('question').focus();});
if(!navigator.gpu)status('This browser does not expose WebGPU. Use a supported Chrome or Edge device, or open the desktop console.');

const localOrigin='http://127.0.0.1:8767';
const localFrame=$('local-frame');
let localAttempt;
function preferBrowser(value){
  try{sessionStorage.setItem('jarvis-browser-mode',String(value));}catch{}
}
function showMode(local){
  $('browser-mode').hidden=local;
  $('local-mode').hidden=!local;
  $('local-toggle').textContent=local?'Use browser AI':'Use local PC';
  $('local-toggle').setAttribute('aria-pressed',String(local));
  $('settings-link').hidden=local;
  $('local-mode').classList.remove('is-paired');
  $('connection-state').textContent=local?'Local PC':'Browser';
  $('connection-state').toggleAttribute('data-online',!local&&ready);
  if(!local){
    localAttempt?.abort();
    localAttempt=null;
    localFrame.hidden=true;
    localFrame.removeAttribute('src');
  }
}

async function openLocal(automatic=false){
  if(!automatic)showMode(true);
  localAttempt?.abort();
  const attempt=new AbortController();
  localAttempt=attempt;
  $('local-retry').hidden=true;
  $('local-code-link').hidden=true;
  $('local-status').textContent='Connecting to JARVIS on this PC. Allow loopback access if Chrome asks.';
  $('connection-state').textContent='Connecting';
  let timeout;
  try{
    timeout=setTimeout(()=>attempt.abort(),25000);
    const response=await fetch(localOrigin+'/embed-ready',{
      mode:'cors',credentials:'omit',targetAddressSpace:'loopback',signal:attempt.signal,
    });
    if(!response.ok)throw Error('The local server did not accept this site.');
    if(attempt!==localAttempt)return;
    showMode(true);
    localFrame.src=localOrigin+'/embedded';
    localFrame.hidden=false;
    $('local-status').textContent='Opening your voice console…';
  }catch(error){
    if(attempt!==localAttempt)return;
    if(automatic)showMode(false);
    $('local-retry').hidden=false;
    const message='Could not reach JARVIS on this PC. Check that JARVIS is running and Chrome allows loopback access, then try again.';
    $('local-status').textContent=message;
    $('local-connection-note').textContent=message;
  }finally{
    clearTimeout(timeout);
  }
}

function connectPC(){
  preferBrowser(false);
  void openLocal();
}
$('local-toggle').onclick=()=>{
  if($('local-mode').hidden)connectPC();
  else{preferBrowser(true);showMode(false);}
};
$('local-connect').onclick=connectPC;
$('local-retry').onclick=connectPC;
localFrame.addEventListener('load',()=>{
  if(!localFrame.hidden)localFrame.contentWindow.postMessage({type:'jarvis-connect'},localOrigin);
});
window.addEventListener('message',event=>{
  if(event.origin!==localOrigin||event.source!==localFrame.contentWindow||$('local-mode').hidden)return;
  if(event.data?.type==='jarvis-pairing-required'){
    $('local-status').textContent='Use a pairing code to finish connecting this PC.';
    $('local-code-link').hidden=false;
    return;
  }
  if(event.data?.type!=='jarvis-pairing'||typeof event.data.paired!=='boolean')return;
  $('local-mode').classList.toggle('is-paired',event.data.paired);
  $('connection-state').toggleAttribute('data-online',event.data.paired);
  if(event.data.reason==='disconnected'){preferBrowser(true);showMode(false);}
  if(event.data.reason==='expired')void openLocal();
});
function connectOnEntry(){
  try{if(sessionStorage.getItem('jarvis-browser-mode')==='true')return;}catch{}
  void openLocal(true);
}
window.addEventListener('pageshow',event=>{if(event.persisted)connectOnEntry();});
connectOnEntry();
