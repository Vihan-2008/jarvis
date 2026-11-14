/* Runs on the browser's audio thread: turns the microphone into 20 ms pieces of 16-bit sound. */
class NovaMic extends AudioWorkletProcessor {
  constructor() { super(); this.piece = new Int16Array(320); this.filled = 0; }
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (channel) {
      for (let i = 0; i < channel.length; i++) {
        const sample = Math.max(-1, Math.min(1, channel[i]));
        this.piece[this.filled++] = sample < 0 ? sample * 32768 : sample * 32767;
        if (this.filled === 320) { this.port.postMessage(this.piece.slice(0)); this.filled = 0; }
      }
    }
    return true;
  }
}
registerProcessor('nova-mic', NovaMic);
