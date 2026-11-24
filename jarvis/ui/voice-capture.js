class JarvisMicrophone extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer=new Float32Array(2048);
    this.used=0;
  }

  process(inputs) {
    const samples=inputs[0][0];
    if(!samples)return true;
    for(const sample of samples){
      this.buffer[this.used++]=sample;
      if(this.used===this.buffer.length){
        this.port.postMessage(this.buffer,[this.buffer.buffer]);
        this.buffer=new Float32Array(2048);
        this.used=0;
      }
    }
    // The output stays silent. The connection keeps the processor running.
    return true;
  }
}

registerProcessor('jarvis-microphone',JarvisMicrophone);
