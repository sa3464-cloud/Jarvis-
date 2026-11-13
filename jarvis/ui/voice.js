const SILENCE_MS = 900;
const LEVEL_THRESHOLD = 0.025;
const MAX_TURN_MS = 30000;
const $ = id => document.getElementById(id);
let csrf, enabled = false, stream, context, analyser, recorder, interval, speech, speechURL;
let busy = false, heard = false, lastVoice = 0, started = 0, generation = 0;
let history = [];
for (let i=0;i<24;i++) $('bars').appendChild(document.createElement('i'));
function state(name, message) { $('state').textContent=name; $('reactor').dataset.state=name.toLowerCase(); if(message) $('status').textContent=message; }
function approved() { if(!$('approval').checked) throw Error('Approve ElevenLabs credit use before using voice.'); }
async function api(path, body, mime='application/json') {
  const response=await fetch(path,{method:'POST',headers:{'Content-Type':mime,'X-Jarvis-CSRF':csrf,'X-Jarvis-Voice-Approved':$('approval').checked?'yes':'no'},body});
  if(!response.ok) { const error=await response.json(); throw Error(error.error||`Request failed: ${response.status}`); }
  return response;
}
function addTurn(role, text) {
  const card=document.createElement('article');const label=document.createElement('strong');
  label.textContent=role==='user'?'You':'JARVIS';const paragraph=document.createElement('p');
  paragraph.textContent=text;paragraph.style.whiteSpace='pre-wrap';card.append(label,paragraph);
  $('conversation').appendChild(card);
  while($('conversation').children.length>20)$('conversation').firstChild.remove();
}
function showInbox(card) {
  $('cards').replaceChildren();
  if(!card.messages.length){$('cards').textContent='No unread inbox messages.';return;}
  for(const message of card.messages){const row=document.createElement('article');const title=document.createElement('strong');title.textContent=message.subject;const detail=document.createElement('p');detail.textContent=`${message.from} · ${message.date}`;row.append(title,detail);$('cards').appendChild(row);}
}
function showAction(result) {
  if(result.card?.type==='inbox')showInbox(result.card);
  if(result.card?.type==='website'){
    const row=document.createElement('article');const link=document.createElement('a');
    link.href=result.card.url;link.textContent=result.card.url;link.target='_blank';link.rel='noopener noreferrer';
    row.appendChild(link);$('conversation').appendChild(row);
  }
}
async function ask(question) {
  if(!question.trim())throw Error('Type or say a question first.');
  deaf();busy=true;const ticket=++generation;$('ask').disabled=true;
  state('Thinking','JARVIS is thinking locally…');addTurn('user',question);
  try{
    const result=await (await api('/api/chat',JSON.stringify({question,history}))).json();
    if(ticket!==generation)return;
    addTurn('assistant',result.answer);
    showAction(result);
    for(const source of result.sources){const card=document.createElement('article');const title=document.createElement('strong');title.textContent=source.file;const excerpt=document.createElement('p');excerpt.textContent=source.text;card.append(title,excerpt);$('conversation').appendChild(card);}
    $('model').textContent=result.model_missing?'Model unavailable — limited fallback only':result.action&&result.action!=='conversation'?result.model:`Local Ollama · ${result.model}`;
    if(!result.model_missing)history=[...history,{role:'user',content:question},{role:'assistant',content:result.answer}].slice(-20);
    busy=false;state('Idle',result.model_missing?'The local model is unavailable. Check the message below.':'Answer ready.');
    if($('approval').checked)await say(result.spoken);
    else if(enabled)await record();
  }catch(error){if(ticket===generation){enabled=false;deaf();busy=false;state('Error',error.message);}}
  finally{if(ticket===generation)busy=false;$('ask').disabled=false;}
}
function deaf() {
  clearInterval(interval); interval=null;
  if(recorder && recorder.state!=='inactive') {recorder.onstop=null; recorder.stop();}
  if(stream) stream.getTracks().forEach(track=>track.stop()); stream=null;
  if(context) context.close().catch(()=>{}); context=null;
  for(const bar of $('bars').children) bar.style.height='3px';
}
function stop() {
  generation++; enabled=false; deaf(); busy=false;
  if(speech) {speech.pause();speech.src='';speech=null;}
  if(speechURL) URL.revokeObjectURL(speechURL);speechURL=null;
  $('mic').textContent='Start microphone';$('caption').textContent='Microphone off';state('Idle','Stopped.');
}
async function say(text) {
  approved();
  if(speech){speech.pause();speech.src='';speech=null;}
  if(speechURL){URL.revokeObjectURL(speechURL);speechURL=null;}
  deaf(); busy=true; const ticket=++generation;
  state('Thinking','Generating speech… microphone is off.');
  try {
    const blob=await (await api('/api/speak',JSON.stringify({text}))).blob();
    if(ticket!==generation)return;
    speechURL=URL.createObjectURL(blob);speech=new Audio(speechURL);
    state('Speaking','Microphone is off while JARVIS speaks.');
    await new Promise((resolve,reject)=>{speech.onended=resolve;speech.onerror=()=>reject(Error('Audio playback failed.'));speech.play().catch(reject);});
    if(ticket!==generation)return;
    URL.revokeObjectURL(speechURL);speechURL=null;speech=null;busy=false;
    state('Idle','Speech finished.');if(enabled) await record();
  } catch(error) {if(ticket===generation){busy=false;enabled=false;state('Error',error.message);}}
}
async function record() {
  approved(); if(busy)return;
  if(!navigator.mediaDevices?.getUserMedia||!window.MediaRecorder) throw Error('This browser cannot record audio. Try a current Chrome, Edge, Firefox, or Safari.');
  const captureTicket=generation;
  const captured=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true}});
  if(!enabled||captureTicket!==generation){captured.getTracks().forEach(track=>track.stop());return;}
  stream=captured;const captureContext=new AudioContext();context=captureContext;await captureContext.resume();
  if(!enabled||captureTicket!==generation){captured.getTracks().forEach(track=>track.stop());captureContext.close().catch(()=>{});return;}
  analyser=context.createAnalyser();analyser.fftSize=1024;
  context.createMediaStreamSource(stream).connect(analyser);
  const mime=['audio/webm;codecs=opus','audio/ogg;codecs=opus','audio/mp4'].find(type=>MediaRecorder.isTypeSupported(type));
  recorder=new MediaRecorder(stream,mime?{mimeType:mime}:{});let chunks=[];
  recorder.ondataavailable=event=>{if(event.data.size)chunks.push(event.data);};
  recorder.onerror=()=>{stop();state('Error','Microphone recording failed.');};
  recorder.onstop=async()=>{
    const type=recorder.mimeType;const audio=new Blob(chunks,{type});const ticket=++generation;
    deaf();busy=true;state('Thinking','Transcribing your recording…');$('caption').textContent='Waiting for ElevenLabs transcript…';
    try {
      const result=await (await api('/api/listen',audio,type)).json();if(ticket!==generation)return;
      $('text').value=result.text;$('caption').textContent=result.text||'No speech detected.';
      busy=false;
      if(result.text.trim())await ask(result.text);
      else{state('Idle','No speech detected.');if(enabled)await record();}
    }catch(error){if(ticket===generation){stop();state('Error',error.message);}}
  };
  heard=false;started=lastVoice=Date.now();recorder.start();state('Listening','Speak naturally. Silence ends each turn.');
  $('caption').textContent='Listening… transcript appears after each turn.';
  const samples=new Float32Array(analyser.fftSize);
  interval=setInterval(()=>{
    analyser.getFloatTimeDomainData(samples);const level=Math.sqrt(samples.reduce((sum,x)=>sum+x*x,0)/samples.length);
    for(const [i,bar] of [...$('bars').children].entries())bar.style.height=`${3+Math.min(22,level*240)*(0.5+0.5*Math.sin(i))}px`;
    const now=Date.now();if(level>LEVEL_THRESHOLD){heard=true;lastVoice=now;}
    if(!heard&&now-started>=MAX_TURN_MS){stop();state('Idle','No speech detected for 30 seconds. Microphone stopped; no transcription requested.');return;}
    if((heard&&now-lastVoice>=SILENCE_MS)||now-started>=MAX_TURN_MS){clearInterval(interval);recorder.stop();}
  },50);
}
$('mic').onclick=async()=>{
  if(enabled&&!busy){stop();return;}
  // Starting voice is an explicit opt-in for this page session. The adjacent
  // notice explains credit use; do not require a separate checkbox first.
  $('approval').checked=true;
  stop();enabled=true;$('mic').textContent='Stop microphone';
  try{await record();}catch(error){stop();state('Error',error.message);}
};
$('stop').onclick=stop;
$('ask').onclick=()=>{stop();ask($('text').value).catch(error=>state('Error',error.message));};
$('text').addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();$('ask').click();}});
$('clear').onclick=()=>{stop();history=[];$('conversation').replaceChildren();$('text').value='';state('Idle','New conversation.');};
$('speak').onclick=()=>say($('text').value).catch(error=>state('Error',error.message));
$('approval').onchange=()=>{if(!$('approval').checked)stop();};
$('inbox').onclick=async()=>{
  stop();$('inbox').disabled=true;state('Thinking','Sign into Google in the opened browser. Waiting for inbox…');
  try{
    const result=await (await api('/api/inbox','{}')).json();showInbox(result);
    $('text').value=result.spoken;state('Idle',`Fetched ${result.messages.length} unread messages from ${result.account}.`);
    history=[...history,{role:'user',content:'Read my unread inbox messages.'},{role:'assistant',content:result.spoken}].slice(-20);
    if($('approval').checked)await say(result.spoken);
  }catch(error){state('Error',error.message);}finally{$('inbox').disabled=false;}
};
document.addEventListener('keydown',event=>{if(event.key==='Escape')stop();if(event.code==='Space'&&event.target===document.body){event.preventDefault();$('mic').click();}});
window.addEventListener('pagehide',stop);
fetch('/api/status').then(response=>response.json()).then(status=>{csrf=status.csrf;$('model').textContent=status.model.message;state('Idle',status.voice_configured?`Voice key configured. ${status.demo?'Demo mode: real email disabled.':'Real email enabled.'}`:'ElevenLabs key missing.');}).catch(error=>state('Error',`Server unavailable: ${error.message}`));
