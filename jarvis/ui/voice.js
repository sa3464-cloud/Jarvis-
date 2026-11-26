const PRE_ROLL_MS = 350;
const TAIL_MS = 450;
const MIN_SPEECH_MS = 160;
const PLAYBACK_COOLDOWN_MS = 350;
const MAX_TURN_MS = 30000;
const $ = id => document.getElementById(id);
const embedded = document.body.dataset.mode === 'embedded';
const hostedOrigin = 'https://seth-jarvis-command-center.sa3464.chatgpt.site';
let csrf, enabled = false, stream, context, captureNode, speech, speechURL;
let finishCapture, retryMicrophone;
let transcriptProvider = 'Windows';
let wakeWord = false, activeUntil = 0;
const FOLLOW_UP_MS = 25000;
let busy = false, generation = 0;
let cloudConfigured = true, cloudRecognition = true;
let history = [];
let statusRequest;
for (let i=0;i<5;i++) $('bars').appendChild(document.createElement('i'));
function setHudMeter(channel,fraction) {
  const value=`${Math.round(Math.max(0,Math.min(1,fraction))*100)}%`;
  const readout=$(`hud-${channel}`);
  if(readout.textContent===value)return;
  readout.textContent=value;
  $('reactor').style.setProperty(`--hud-${channel}`,value);
}
function state(name, message) {
  $('state').textContent=name;
  $('reactor').dataset.state=name.toLowerCase();
  if(name==='Idle'||name==='Error')setHudMeter('playback',0);
  if(message)$('status').textContent=message;
}
function approved() { if(!$('approval').checked) throw Error('Enable voice for this session first.'); }
function readLocalStatus(){
  if(!statusRequest){
    statusRequest=fetch('/api/status',{cache:'no-store',mode:'same-origin'})
      .then(async response=>{
        if(!response.ok)throw Error('Could not start a local JARVIS session.');
        const status=await response.json();
        if(typeof status.csrf!=='string'||!status.csrf)throw Error('The server did not provide a local JARVIS session.');
        csrf=status.csrf;
        return status;
      })
      .finally(()=>{statusRequest=undefined;});
  }
  return statusRequest;
}

async function api(path, body, mime='application/json') {
  const url=embedded?path.replace('/api/','/api/embed/'):path;
  const ticket=generation;
  if(!embedded&&!csrf)await readLocalStatus();
  for(let attempt=0;attempt<2;attempt++){
    if(ticket!==generation)throw Error('The request was canceled.');
    const token=csrf;
    const response=await fetch(url,{
      method:'POST',mode:'same-origin',
      headers:{'Content-Type':mime,'X-Jarvis-CSRF':token,'X-Jarvis-Voice-Approved':$('approval').checked?'yes':'no'},
      body,
    });
    if(embedded&&token!==csrf)throw Error('The local session has ended.');
    if(response.ok)return response;
    const payload=await response.json();
    // This error is returned before the server reads or acts on the request.
    if(!embedded&&attempt===0&&response.status===403&&payload.code==='stale_session'){
      if(token===csrf)showConsole(await readLocalStatus(),false);
      continue;
    }
    const error=new Error(payload.error||`Request failed: ${response.status}`);
    error.status=response.status;
    if(embedded&&error.status===401)lockEmbedded(error.message,'expired');
    throw error;
  }
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
    $('model').textContent=result.model_missing?'Model unavailable — limited fallback only':result.action&&result.action!=='conversation'?result.model:`${result.provider || 'Local Ollama'} · ${result.model}`;
    if(!result.model_missing)history=[...history,{role:'user',content:question},{role:'assistant',content:result.answer}].slice(-20);
    busy=false;state('Idle',result.model_missing?'The conversation model is unavailable. Check the message below.':'Answer ready.');
    if($('approval').checked)await say(result.spoken);
    else if(enabled)await record();
  }catch(error){
    if(ticket!==generation)return;
    busy=false;
    if(enabled)await resumeListening(error.message);
    else state('Error',error.message);
  }
  finally{if(ticket===generation)busy=false;$('ask').disabled=false;}
}
function deaf() {
  finishCapture=null;
  if(captureNode){captureNode.port.close();captureNode=null;}
  if(stream) stream.getTracks().forEach(track=>track.stop()); stream=null;
  if(context) context.close().catch(()=>{}); context=null;
  for(const bar of $('bars').children) bar.style.removeProperty('height');
  setHudMeter('mic',0);
  $('microphone-diagnostics').textContent='Microphone off';
}
function stop() {
  clearTimeout(retryMicrophone);
  activeUntil=0;
  generation++; enabled=false; deaf(); busy=false;
  if(speech) {speech.pause();speech.src='';speech=null;}
  if(speechURL) URL.revokeObjectURL(speechURL);speechURL=null;
  $('ask').disabled=false;
  $('mic').textContent='Start microphone';$('caption').textContent='Microphone off';state('Idle','Stopped.');
}
async function resumeListening(message) {
  try{await record(`${message} Listening again.`);}
  catch(error){stop();state('Error',error.message);}
}
async function say(text) {
  approved();
  if(speech){speech.pause();speech.src='';speech=null;}
  if(speechURL){URL.revokeObjectURL(speechURL);speechURL=null;}
  deaf(); busy=true; const ticket=++generation;
  setHudMeter('playback',0);
  state('Thinking','Generating speech… microphone is off.');
  try {
    const response=await api('/api/speak',JSON.stringify({text}));
    const localVoice=response.headers.get('Content-Type')==='audio/wav';
    const notice=response.headers.get('X-Jarvis-Voice-Notice');
    const blob=await response.blob();
    if(ticket!==generation)return;
    speechURL=URL.createObjectURL(blob);
    const playback=new Audio(speechURL);
    speech=playback;
    let bargeCapture;
    await new Promise((resolve,reject)=>{
      playback.onplaying=()=>{
        if(ticket!==generation)return;
        if(enabled&&!bargeCapture)bargeCapture=record(undefined,true).catch(()=>{});
        state('Speaking',localVoice?`${notice?notice+' ':''}Using the built-in Windows voice.`:'Speak to interrupt when echo cancellation is available.');
      };
      playback.onwaiting=()=>{
        if(ticket===generation)state('Thinking','Waiting for audio playback…');
      };
      playback.onpause=()=>{
        if(playback.ended)return;
        if(ticket===generation&&!finishCapture)state('Idle','Playback paused.');
        resolve();
      };
      playback.ontimeupdate=()=>{
        if(ticket===generation&&Number.isFinite(playback.duration)&&playback.duration>0){
          setHudMeter('playback',playback.currentTime/playback.duration);
        }
      };
      playback.onended=resolve;
      playback.onerror=()=>reject(Error('Audio playback failed.'));
      playback.play().catch(reject);
    });
    if(ticket!==generation)return;
    URL.revokeObjectURL(speechURL);speechURL=null;speech=null;busy=false;
    state('Idle',localVoice?'Spoken with the built-in Windows voice.':'Speech finished.');
    if(enabled){
      activeUntil=performance.now()+FOLLOW_UP_MS;
      if(bargeCapture)await bargeCapture;
      if(ticket!==generation||!enabled)return;
      if(finishCapture){state('Listening','Ready for your follow-up.');return;}
      // Let speaker echo decay before opening the microphone for the next turn.
      await new Promise(resolve=>setTimeout(resolve,PLAYBACK_COOLDOWN_MS));
      if(ticket===generation&&enabled)await record();
    }
  } catch(error) {
    if(ticket!==generation)return;
    if(speechURL)URL.revokeObjectURL(speechURL);
    speechURL=null;speech=null;busy=false;
    if(enabled){deaf();await resumeListening(error.message);}
    else state('Error',error.message);
  }
}
async function hear(transcript) {
  const words=transcript.toLowerCase().replace(/[^\p{L}\p{N}]+/gu,' ').trim();
  if(/^(?:(?:hey )?jarvis )?(?:stop listening|mute (?:the )?microphone)$/.test(words)){
    stop();
    state('Idle','Microphone stopped by voice command.');
    return;
  }
  if(!words){
    await record('I didn’t catch that. Could you repeat what you said?');
    return;
  }
  if(transcript.length>4000){
    await record('That recording was too long. Try a shorter question.');
    return;
  }
  $('caption').textContent=`Heard (${transcriptProvider}): ${transcript}`;
  activeUntil=performance.now()+FOLLOW_UP_MS;
  await ask(transcript);
}
async function speechWav(chunks, startFrame, endFrame, inputRate) {
  const capturedFrames=endFrame-startFrame;
  if(capturedFrames<=0)throw Error('No microphone audio was captured. Try speaking again.');
  const sampleRate=16000;
  const frames=Math.ceil(capturedFrames*sampleRate/inputRate);
  const renderContext=new OfflineAudioContext(1,frames,sampleRate);
  const input=renderContext.createBuffer(1,capturedFrames,inputRate);
  const samples=input.getChannelData(0);
  let offset=0;
  for(const chunk of chunks){
    const start=Math.max(startFrame-offset,0);
    const end=Math.min(endFrame-offset,chunk.length);
    if(start<end)samples.set(chunk.subarray(start,end),offset+start-startFrame);
    offset+=chunk.length;
    if(offset>=endFrame)break;
  }
  const source=renderContext.createBufferSource();
  source.buffer=input;
  source.connect(renderContext.destination);
  source.start();
  const mono=await renderContext.startRendering();
  const pcm=mono.getChannelData(0);
  const dc=pcm.reduce((sum,sample)=>sum+sample,0)/frames;
  let peak=0;
  for(const sample of pcm)peak=Math.max(peak,Math.abs(sample-dc));
  const gain=peak>0?Math.min(3,.8/peak):1;
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
    const sample=Math.max(-1,Math.min(1,(pcm[i]-dc)*gain));
    view.setInt16(44+i*2,sample*(sample<0?32768:32767),true);
  }
  return buffer;
}
async function updateMicrophones() {
  if(!navigator.mediaDevices?.enumerateDevices)return;
  const select=$('microphone-device');
  const selected=select.value;
  const devices=(await navigator.mediaDevices.enumerateDevices()).filter(device=>device.kind==='audioinput'&&device.deviceId!=='default'&&device.deviceId);
  select.replaceChildren(new Option('System default',''));
  for(const [index,device] of devices.entries())select.add(new Option(device.label||`Microphone ${index+1}`,device.deviceId));
  if(selected&&!devices.some(device=>device.deviceId===selected))select.add(new Option('Selected microphone (disconnected)',selected));
  select.value=selected;
}
function reconnectMicrophone(ticket, message) {
  if(ticket!==generation||!enabled)return;
  const retryTicket=++generation;
  deaf();busy=false;
  state('Standby',message+' Reconnecting automatically.');
  clearTimeout(retryMicrophone);
  retryMicrophone=setTimeout(async()=>{
    if(retryTicket!==generation||!enabled)return;
    try{await record('Microphone reconnected.');}
    catch(error){reconnectMicrophone(retryTicket,error.message);}
  },2000);
}
async function record(message = 'Speak naturally. JARVIS answers after you pause.', duringPlayback=false) {
  approved(); if(busy&&!duringPlayback)return;
  if(!navigator.mediaDevices?.getUserMedia||!window.AudioWorkletNode) throw Error('This browser cannot record audio. Try a current Chrome, Edge, Firefox, or Safari.');
  const captureTicket=generation;
  const device=$('microphone-device').value;
  const captured=await navigator.mediaDevices.getUserMedia({
    audio:{channelCount:1,echoCancellation:true,noiseSuppression:$('microphone-suppression').checked,autoGainControl:true,
           ...(device?{deviceId:{exact:device}}:{})},
  });
  if(!enabled||captureTicket!==generation){captured.getTracks().forEach(track=>track.stop());return;}
  if(duringPlayback&&(!speech||speech.ended||captured.getAudioTracks()[0]?.getSettings().echoCancellation!==true)){
    captured.getTracks().forEach(track=>track.stop());return;
  }
  stream=captured;
  void updateMicrophones().catch(()=>{});
  for(const track of captured.getAudioTracks()){
    track.onended=()=>{
      if(captureTicket!==generation)return;
      if(speech&&!speech.ended){
        deaf();
        return;
      }
      reconnectMicrophone(captureTicket,'Microphone disconnected.');
    };
  }
  const captureContext=new AudioContext();
  context=captureContext;
  await captureContext.audioWorklet.addModule('/voice-capture.js');
  if(!enabled||captureTicket!==generation)return;
  await captureContext.resume();
  if(!enabled||captureTicket!==generation)return;

  const node=new AudioWorkletNode(captureContext,'jarvis-microphone',{
    channelCount:1,channelCountMode:'explicit',outputChannelCount:[1],
  });
  captureNode=node;
  const chunks=[];
  const sampleRate=captureContext.sampleRate;
  const framesFor=ms=>Math.round(ms*sampleRate/1000);
  const maxFrames=framesFor(MAX_TURN_MS);
  const minVoiceFrames=framesFor(MIN_SPEECH_MS);
  let capturedFrames=0, firstFrame=0;
  let speechStart=null, needsWake=false;
  let lastSignalFrame=0;
  let candidateStart=null, voicedFrames=0, lastVoiceFrame=0, noiseFloor=.003;

  const finishRecording=async(manual=false)=>{
    if(captureTicket!==generation)return;
    if(speechStart===null&&(!manual||lastSignalFrame<=firstFrame||capturedFrames-firstFrame<framesFor(180))){
      state('Listening','No speech detected yet. The microphone is still listening.');
      return;
    }
    if(speechStart===null&&wakeWord&&performance.now()>=activeUntil)needsWake=true;
    const ticket=++generation;
    if(speech){
      speech.pause();speech=null;
      if(speechURL)URL.revokeObjectURL(speechURL);
      speechURL=null;setHudMeter('playback',0);
    }
    deaf();busy=true;state('Thinking',needsWake?'Checking wake word locally…':'Transcribing your recording…');$('caption').textContent='Microphone paused during transcription.';
    $('mic').textContent='Transcribing…';
    try {
      const start=speechStart===null?firstFrame:Math.max(firstFrame,speechStart-framesFor(PRE_ROLL_MS));
      const end=Math.min(start+maxFrames,manual?capturedFrames:lastVoiceFrame+framesFor(TAIL_MS),capturedFrames);
      const audio=await speechWav(chunks,start-firstFrame,end-firstFrame,sampleRate);
      if(ticket!==generation)return;
      if(needsWake){
        const response=await api('/api/listen/wake',audio,'audio/wav');
        const {detected}=await response.json();
        if(ticket!==generation)return;
        busy=false;
        if(detected)activeUntil=performance.now()+FOLLOW_UP_MS;
        await record(detected?'Listening. What can I do for you?':undefined);
        return;
      }
      let transcript='', uncertain=false;
      if(cloudRecognition){
        try {
          const response=await api('/api/listen',audio,'audio/wav');
          const result=await response.json();
          transcript=result.text.trim();
          uncertain=result.uncertain;
          transcriptProvider=result.provider||'Cloud';

        } catch(error) {
          if(error.status!==402&&error.status!==502)throw error;
          cloudRecognition=false;
        }
      }
      if(!transcript&&!uncertain){
        transcriptProvider='Windows';
        if(ticket!==generation)return;
        state('Thinking','Transcribing with Windows…');
        $('caption').textContent='Waiting for Windows transcript…';
        const response=await api('/api/listen/local',audio,'audio/wav');
        transcript=(await response.json()).text.trim();
      }
      if(ticket!==generation)return;
      busy=false;
      $('mic').textContent='Start microphone';
      await hear(transcript);
    }catch(error){if(ticket===generation){stop();state('Error',error.message);}}
  };
  node.port.onmessage=({data})=>{
    if(captureTicket!==generation)return;
    const chunk=data;
    const chunkStart=capturedFrames;
    chunks.push(chunk);
    capturedFrames+=chunk.length;
    let sum=0, squares=0;
    for(const sample of chunk){sum+=sample;squares+=sample*sample;}
    const level=Math.sqrt(Math.max(0,squares/chunk.length-(sum/chunk.length)**2));
    if(level>=.0008)lastSignalFrame=capturedFrames;
    setHudMeter('mic',level*5);
    const bars=$('bars').children;
    for(let i=0;i<bars.length;i++){
      let peak=0;
      for(let j=Math.floor(i*chunk.length/bars.length);j<Math.floor((i+1)*chunk.length/bars.length);j++){
        peak=Math.max(peak,Math.abs(chunk[j]));
      }
      bars[i].style.height=`${3+Math.min(22,peak*180)}px`;
    }
    const db=value=>Math.round(20*Math.log10(Math.max(.00001,value)));
    $('microphone-diagnostics').textContent=`Input ${db(level)} dBFS · Noise ${db(noiseFloor)} dBFS · ${transcriptProvider}`;
    const playing=Boolean(speech&&!speech.paused&&!speech.ended);
    const standby=wakeWord&&!playing&&performance.now()>=activeUntil;
    if(standby&&speechStart===null&&$('state').textContent==='Listening')state('Standby','Say “Jarvis” to start a conversation.');
    const sensitivity=Number($('microphone-sensitivity').value)/100;
    const threshold=Math.max(playing ? .012 : .0018,noiseFloor*(3.4-1.5*sensitivity)*(speechStart===null?1:.72));
    if(level>threshold){
      candidateStart??=chunkStart;
      voicedFrames+=chunk.length;
      lastVoiceFrame=capturedFrames;
      if(voicedFrames>=(playing?framesFor(280):minVoiceFrames)){
        if(speechStart===null)needsWake=standby;
        speechStart??=candidateStart;
        if(playing){
          speech.pause();
          state('Listening','Interrupted. Listening to you.');
        }
      }
    }else{
      noiseFloor+=.06*(level-noiseFloor);
      if(speechStart===null&&capturedFrames-lastVoiceFrame>=framesFor(90)){
        candidateStart=null;
        voicedFrames=0;
      }
    }
    const pauseMs=needsWake?600:Number($('microphone-pause').value);
    if(speechStart===null){
      const keepFrom=Math.min(capturedFrames-framesFor(1800),(candidateStart??capturedFrames)-framesFor(PRE_ROLL_MS));
      while(chunks.length&&firstFrame+chunks[0].length<=keepFrom)firstFrame+=chunks.shift().length;
    }else if(capturedFrames-speechStart>=maxFrames-framesFor(PRE_ROLL_MS)||capturedFrames-lastVoiceFrame>=framesFor(pauseMs+Math.min(350,120*(lastVoiceFrame-speechStart)/sampleRate))){
      void finishRecording();
    }
  };
  node.onprocessorerror=()=>{
    if(captureTicket!==generation)return;
    if(speech&&!speech.ended)deaf();
    else reconnectMicrophone(captureTicket,'Microphone recording failed.');
  };
  captureContext.createMediaStreamSource(captured).connect(node);
  node.connect(captureContext.destination);
  finishCapture=finishRecording;
  $('mic').textContent='Finish recording';
  if(!duringPlayback||!speech||speech.paused){
    if(wakeWord&&performance.now()>=activeUntil)state('Standby','Say “Jarvis” to start a conversation.');
    else state('Listening',message);
  }
  $('caption').textContent='Hands-free microphone on. Say “stop listening” to stop.';
}
$('microphone-device').onchange=async()=>{
  if(!enabled||busy||speech)return;
  const ticket=++generation;
  deaf();
  try{await record('Using the selected microphone.');}
  catch(error){reconnectMicrophone(ticket,error.message);}
};
$('microphone-suppression').onchange=$('microphone-device').onchange;
$('mic').onclick=async()=>{
  if(finishCapture){await finishCapture(true);return;}
  if(busy)return;
  if(enabled){stop();return;}
  // Starting voice is an explicit opt-in for this page session. The adjacent
  // notice explains credit use; do not require a separate checkbox first.
  $('approval').checked=true;
  cloudRecognition=cloudConfigured;
  stop();enabled=true;$('mic').textContent='Connecting microphone…';
  try{await record();}catch(error){stop();state('Error',error.message);}
};
$('stop').onclick=stop;
$('ask').onclick=()=>{
  const question=$('text').value.trim();
  if(!question){
    if(!enabled)state('Idle','Type or say a question first.');
    return;
  }
  stop();
  ask(question).catch(error=>state('Error',error.message));
};
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
function lockEmbedded(message,reason){
  csrf=undefined;
  stop();
  $('approval').checked=false;
  $('conversation').replaceChildren();
  $('thread-empty').hidden=false;
  $('cards').replaceChildren();
  $('text').value='';
  history=[];
  delete document.body.dataset.paired;
  window.parent.postMessage({type:'jarvis-pairing',paired:false,reason},hostedOrigin);
  $('pairing-message').textContent=message;
}

window.addEventListener('pagehide',()=>{
  if(embedded&&csrf){
    fetch('/api/embed/disconnect',{method:'POST',keepalive:true,
      headers:{'Content-Type':'application/json','X-Jarvis-CSRF':csrf},body:'{}'}).catch(()=>{});
    lockEmbedded('Pair this console again to continue.');
  } else stop();
});

document.querySelectorAll('button[data-question]').forEach(button=>{
  button.onclick=()=>{
    $('text').value=button.dataset.question;
    $('text').focus();
  };
});

function showConsole(status, announce=true){
  csrf=status.csrf;
  wakeWord=Boolean(status.wake_word);
  if(announce)cloudRecognition=cloudConfigured=status.voice_configured;
  $('connection-state').textContent='Online';
  $('connection-state').setAttribute('data-online','');
  $('model').textContent=status.model.message;
  const provider=status.tts_provider==='fish_audio'?'Fish Audio':'ElevenLabs';
  const speechConfigured=status.tts_configured??status.voice_configured;
  $('voice-mode').textContent=speechConfigured?`${provider} speech · Windows fallback`:`Windows speech · ${provider} setup needed`;
  $('voice-note').textContent=`Start the microphone for hands-free conversation. JARVIS answers after you pause. ElevenLabs transcribes when available, with Windows as the fallback. Reply text may go to ${provider}. Say “stop listening” to end the session.`;
  $('gmail-voice-note').textContent=`Sign in with your NJIT account when prompted. JARVIS leaves messages unread. When voice is enabled, sender names and subjects may go to ${provider} for speech.`;
  $('email-mode').textContent=status.demo?'Disabled in demo mode':'Read-only · sign-in on request';
  $('inbox').disabled=status.demo;
  if(announce&&!enabled&&!busy)state('Idle',status.voice_configured?'Ready for text or voice.':'Ready for text or Windows voice recognition.');
  $('issue-code').disabled=false;
  $('revoke-pairing').disabled=false;
}

function displayIssuedCode(code,message){
  $('issued-code').value=code;
  $('issued-code').hidden=!code;
  $('issued-code-label').hidden=!code;
  $('issued-code-message').textContent=message;
  if(code){$('issued-code').focus();$('issued-code').select();}
}

if(embedded){
  function showPairingFallback(message){
    $('pairing-message').textContent=message;
    $('pairing-fallback').hidden=false;
    window.parent.postMessage({type:'jarvis-pairing-required'},hostedOrigin);
  }
  async function connectEmbedded(path, credentials){
    const response=await fetch('/api/embed/'+path,{method:'POST',mode:'same-origin',
      headers:{'Content-Type':'application/json','X-Jarvis-Embedded':'yes'},
      body:JSON.stringify(credentials)});
    const result=await response.json();
    if(!response.ok)throw Error(result.error||'Pairing failed.');
    showConsole(result);
    document.body.dataset.paired='';
    window.parent.postMessage({type:'jarvis-pairing',paired:true},hostedOrigin);
    $('pairing-message').textContent='';
  }
  let automaticTicket=document.body.dataset.autoConnect;
  delete document.body.dataset.autoConnect;
  if(automaticTicket){
    window.addEventListener('message',event=>{
      if(event.origin!==hostedOrigin||event.source!==window.parent||event.data?.type!=='jarvis-connect'||!automaticTicket)return;
      const ticket=automaticTicket;
      automaticTicket=null;
      connectEmbedded('auto-connect',{ticket}).catch(error=>showPairingFallback(error.message));
    });
  }else showPairingFallback('Use a pairing code to connect.');

  $('pairing-form').onsubmit=async event=>{
    event.preventDefault();
    $('pair-submit').disabled=true;
    $('pairing-message').textContent='Pairing with the local server…';
    try{
      await connectEmbedded('connect',{code:$('pairing-code').value.trim()});
      $('text').focus();
    }catch(error){
      $('pairing-message').textContent=error.message;
    }finally{
      $('pairing-code').value='';
      $('pair-submit').disabled=false;
    }
  };
  $('embed-disconnect').onclick=async()=>{
    try{
      await api('/api/disconnect','{}');
      lockEmbedded('Disconnected.','disconnected');
    }catch(error){
      lockEmbedded(`Local controls closed. ${error.message}`,'disconnected');
    }
  };
}else{
  readLocalStatus().then(showConsole)
    .catch(error=>{
      $('connection-state').textContent='Offline';
      state('Error',`Server unavailable: ${error.message}`);
    });
  $('issue-code').onclick=async()=>{
    try{
      const result=await (await api('/api/embed-code','{}')).json();
      displayIssuedCode(result.code,'Code selected. Copy it with Ctrl+C and paste it into the embedded local console.');
    }catch(error){displayIssuedCode('',error.message);}
  };
  $('revoke-pairing').onclick=async()=>{
    try{
      await api('/api/embed-revoke','{}');
      displayIssuedCode('','Hosted session and unused pairing code were revoked.');
    }catch(error){displayIssuedCode('',error.message);}
  };
}
