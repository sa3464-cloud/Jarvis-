const SILENCE_MS = 900;
const LEVEL_THRESHOLD = 0.025;
const MAX_TURN_MS = 30000;
const $ = id => document.getElementById(id);
let csrf, enabled = false, stream, context, captureNode, interval, speech, speechURL;
let busy = false, generation = 0;
let history = [];
for (let i=0;i<24;i++) $('bars').appendChild(document.createElement('i'));
function state(name, message) { $('state').textContent=name; $('reactor').dataset.state=name.toLowerCase(); if(message) $('status').textContent=message; }
function approved() { if(!$('approval').checked) throw Error('Approve ElevenLabs credit use before using voice.'); }
async function api(path, body, mime='application/json') {
  const response=await fetch(path,{method:'POST',headers:{'Content-Type':mime,'X-Jarvis-CSRF':csrf,'X-Jarvis-Voice-Approved':$('approval').checked?'yes':'no'},body});
  if(!response.ok) {
    const payload=await response.json();
    const error=new Error(payload.error||`Request failed: ${response.status}`);
    error.status=response.status;
    throw error;
  }
  return response;
}
function addTurn(role, text) {
  const card=document.createElement('article');const label=document.createElement('strong');
  card.className=role;
  label.textContent=role==='user'?'You':'JARVIS';const paragraph=document.createElement('p');
  paragraph.textContent=text;card.append(label,paragraph);
  $('thread-empty').hidden=true;
  const conversation=$('conversation');
  conversation.appendChild(card);
  while(conversation.children.length>20)conversation.firstChild.remove();
  conversation.scrollTop=conversation.scrollHeight;
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
  if(captureNode){captureNode.port.close();captureNode=null;}
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
    const response=await api('/api/speak',JSON.stringify({text}));
    const localVoice=response.headers.get('Content-Type')==='audio/wav';
    const blob=await response.blob();
    if(ticket!==generation)return;
    speechURL=URL.createObjectURL(blob);speech=new Audio(speechURL);
    state('Speaking',localVoice?'ElevenLabs credits unavailable. Using the built-in Windows voice.':'Microphone is off while JARVIS speaks.');
    await new Promise((resolve,reject)=>{speech.onended=resolve;speech.onerror=()=>reject(Error('Audio playback failed.'));speech.play().catch(reject);});
    if(ticket!==generation)return;
    URL.revokeObjectURL(speechURL);speechURL=null;speech=null;busy=false;
    state('Idle',localVoice?'Spoken with the built-in Windows voice.':'Speech finished.');if(enabled) await record();
  } catch(error) {if(ticket===generation){busy=false;enabled=false;state('Error',error.message);}}
}
async function speechWav(chunks, capturedFrames, inputRate) {
  if(!capturedFrames)throw Error('No microphone audio was captured. Try speaking again.');
  const sampleRate=16000;
  const frames=Math.ceil(capturedFrames*sampleRate/inputRate);
  const renderContext=new OfflineAudioContext(1,frames,sampleRate);
  const input=renderContext.createBuffer(1,capturedFrames,inputRate);
  const samples=input.getChannelData(0);
  let offset=0;
  for(const chunk of chunks){
    samples.set(chunk,offset);
    offset+=chunk.length;
  }
  const source=renderContext.createBufferSource();
  source.buffer=input;
  source.connect(renderContext.destination);
  source.start();
  const mono=await renderContext.startRendering();
  const pcm=mono.getChannelData(0);
  const buffer=new ArrayBuffer(44+frames*2);
  const view=new DataView(buffer);
  const bytes=new Uint8Array(buffer);
  const encoder=new TextEncoder();
  bytes.set(encoder.encode('RIFF'),0);
  view.setUint32(4,buffer.byteLength-8,true);
  bytes.set(encoder.encode('WAVEfmt '),8);
  view.setUint32(16,16,true);
  view.setUint16(20,1,true);
  view.setUint16(22,1,true);
  view.setUint32(24,sampleRate,true);
  view.setUint32(28,sampleRate*2,true);
  view.setUint16(32,2,true);
  view.setUint16(34,16,true);
  bytes.set(encoder.encode('data'),36);
  view.setUint32(40,frames*2,true);
  for(let i=0;i<frames;i++){
    const sample=Math.max(-1,Math.min(1,pcm[i]));
    view.setInt16(44+i*2,sample*(sample<0?32768:32767),true);
  }
  return buffer;
}
async function record() {
  approved(); if(busy)return;
  if(!navigator.mediaDevices?.getUserMedia||!window.AudioWorkletNode) throw Error('This browser cannot record audio. Try a current Chrome, Edge, Firefox, or Safari.');
  const captureTicket=generation;
  const captured=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true}});
  if(!enabled||captureTicket!==generation){captured.getTracks().forEach(track=>track.stop());return;}
  stream=captured;
  const captureContext=new AudioContext();
  context=captureContext;
  await captureContext.audioWorklet.addModule('/voice-capture.js');
  if(!enabled||captureTicket!==generation)return;
  await captureContext.resume();
  if(!enabled||captureTicket!==generation)return;

  const analyser=captureContext.createAnalyser();
  analyser.fftSize=1024;
  const node=new AudioWorkletNode(captureContext,'jarvis-microphone',{
    channelCount:1,channelCountMode:'explicit',outputChannelCount:[1],
  });
  captureNode=node;
  const chunks=[];
  let capturedFrames=0;
  const maxFrames=Math.floor(MAX_TURN_MS/1000*captureContext.sampleRate);
  node.port.onmessage=({data})=>{
    const remaining=maxFrames-capturedFrames;
    if(remaining<=0)return;
    const chunk=data.length>remaining?data.subarray(0,remaining):data;
    chunks.push(chunk);
    capturedFrames+=chunk.length;
  };
  node.onprocessorerror=()=>{
    if(captureTicket!==generation)return;
    stop();state('Error','Microphone recording failed.');
  };
  captureContext.createMediaStreamSource(captured).connect(analyser);
  analyser.connect(node);
  node.connect(captureContext.destination);

  const finishRecording=async()=>{
    const ticket=++generation;
    deaf();busy=true;state('Thinking','Transcribing your recording…');$('caption').textContent='Waiting for ElevenLabs transcript…';
    try {
      const audio=await speechWav(chunks,capturedFrames,captureContext.sampleRate);
      if(ticket!==generation)return;
      let response, local=false;
      try {
        response=await api('/api/listen',audio,'audio/wav');
      } catch(error) {
        if(error.status!==402)throw error;
        if(ticket!==generation)return;
        local=true;
        state('Thinking','ElevenLabs credits unavailable. Transcribing with Windows.');
        $('caption').textContent='Waiting for Windows transcript…';
        response=await api('/api/listen/local',audio,'audio/wav');
      }
      const result=await response.json();if(ticket!==generation)return;
      $('text').value=result.text;
      $('caption').textContent=result.text ? (local ? `Windows transcript: ${result.text}` : result.text) : 'No speech detected.';
      busy=false;
      if(result.text.trim())await ask(result.text);
      else{state('Idle','No speech detected.');if(enabled)await record();}
    }catch(error){if(ticket===generation){stop();state('Error',error.message);}}
  };
  let heard=false;
  const started=Date.now();
  let lastVoice=started;
  state('Listening','Speak naturally. Silence ends each turn.');
  $('caption').textContent='Listening… transcript appears after each turn.';
  const samples=new Float32Array(analyser.fftSize);
  interval=setInterval(()=>{
    analyser.getFloatTimeDomainData(samples);const level=Math.sqrt(samples.reduce((sum,x)=>sum+x*x,0)/samples.length);
    for(const [i,bar] of [...$('bars').children].entries())bar.style.height=`${3+Math.min(22,level*240)*(0.5+0.5*Math.sin(i))}px`;
    const now=Date.now();if(level>LEVEL_THRESHOLD){heard=true;lastVoice=now;}
    if(!heard&&now-started>=MAX_TURN_MS){stop();state('Idle','No speech detected for 30 seconds. Microphone stopped; no transcription requested.');return;}
    if((heard&&now-lastVoice>=SILENCE_MS)||now-started>=MAX_TURN_MS)void finishRecording();
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
$('clear').onclick=()=>{
  stop();
  history=[];
  $('conversation').replaceChildren();
  $('thread-empty').hidden=false;
  $('text').value='';
  state('Idle','New conversation.');
};
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

document.querySelectorAll('button[data-question]').forEach(button=>{
  button.onclick=()=>{
    $('text').value=button.dataset.question;
    $('text').focus();
  };
});

const easternTime=new Intl.DateTimeFormat(undefined,{
  month:'short',day:'numeric',hour:'numeric',minute:'2-digit',
  timeZone:'America/New_York',timeZoneName:'short',
});
function updateClock(){
  const now=new Date();
  $('clock').dateTime=now.toISOString();
  $('clock').textContent=easternTime.format(now);
}
updateClock();
setInterval(updateClock,15000);

fetch('/api/status').then(response=>response.json()).then(status=>{
  csrf=status.csrf;
  $('model').textContent=status.model.message;
  $('voice-mode').textContent=status.voice_configured?'ElevenLabs with Windows fallback':'ElevenLabs key required';
  $('email-mode').textContent=status.demo?'Disabled in demo mode':'Read-only · sign-in on request';
  $('inbox').disabled=status.demo;
  state('Idle',status.voice_configured?'Ready for text or voice.':'Text is ready. Set an ElevenLabs key to enable voice.');
}).catch(error=>state('Error',`Server unavailable: ${error.message}`));
