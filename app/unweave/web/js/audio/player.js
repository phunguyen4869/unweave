import {t} from '../core/i18n.js';
// One AudioContext clock and one scheduled start time for every stem.
export class StemPlayer {
  constructor() {
    this.context = null;
    this.master = null;
    this.tracks = [];
    this.nodes = [];
    this.offset = 0;
    this.startedAt = 0;
    this.playing = false;
    this.starting = false;
    this.duration = 0;
    this.volume = 0.7;
    this.playbackRate = 1;
    this.tempoModule = null;
    this.tempoNode = null;
    this.onError = null;
    this.generation = 0;
  }
  ensureContext() {
    if (!this.context) {
      this.context = new AudioContext();
      this.master = this.context.createGain();
      this.master.gain.value = this.volume;
      this.master.connect(this.context.destination);
    }
    return this.context;
  }
  position() {
    return Math.min(this.duration, this.playing
      ? this.offset + Math.max(0, this.context.currentTime - this.startedAt) * this.playbackRate : this.offset);
  }
  stopNodes() {
    for (const {source, gain} of this.nodes) {
      source.onended = null;
      try { source.stop(); } catch (_) { /* Already ended. */ }
      source.disconnect(); gain.disconnect();
    }
    this.nodes = [];
    if (this.tempoNode) {
      this.tempoNode.port.onmessage = null;
      this.tempoNode.onprocessorerror = null;
      this.tempoNode.port.postMessage({type: 'stop'});
      this.tempoNode.disconnect();
      this.tempoNode.port.close();
      this.tempoNode = null;
    }
  }
  pause() {
    this.generation++;
    this.offset = this.position();
    this.playing = false;
    this.starting = false;
    this.stopNodes();
  }
  clear() {
    this.generation++;
    this.pause(); this.offset = 0; this.duration = 0; this.tracks = [];
  }
  setTracks(tracks, duration = null) {
    this.clear();
    this.tracks = tracks.map(t => ({...t, offset: Number(t.offset) || 0,
      bufferOffset: Number(t.bufferOffset) || 0, muted: false, solo: false, volume: 1}));
    const natural = Math.max(0, ...this.tracks.map(t =>
      t.offset + Math.max(0, t.buffer.duration - t.bufferOffset)));
    this.duration = Number.isFinite(duration) && duration > 0 ? duration : natural;
  }
  async play() {
    if (!this.tracks.length || this.playing || this.starting) return;
    const generation = this.generation;
    const context = this.ensureContext();
    this.starting = true;
    try {
      await context.resume();
      if (generation !== this.generation) return;
      if (this.playbackRate !== 1) await this.loadTempoModule(context);
      if (generation !== this.generation) return;
      if (this.offset >= this.duration) this.offset = 0;
      const startTime = context.currentTime + 0.06;
      this.startedAt = startTime;
      let destination = this.master;
      if (this.playbackRate !== 1) {
        this.tempoNode = new AudioWorkletNode(context, 'unweave-tempo', {
          numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [2],
          parameterData: {playbackRate: this.playbackRate},
          processorOptions: {startTime, duration: this.duration - this.offset, playbackRate: this.playbackRate},
        });
        this.tempoNode.connect(this.master);
        destination = this.tempoNode;
        // The processor reports rendered audio, including its initial buffering delay.
        this.startedAt = Infinity;
        this.tempoNode.port.onmessage = ({data}) => {
          if (generation !== this.generation || !this.playing) return;
          if (data.type === 'position') this.startedAt = data.at - data.elapsed / this.playbackRate;
          if (data.type === 'ended') { this.pause(); this.offset = 0; }
        };
        this.tempoNode.onprocessorerror = () => {
          if (generation !== this.generation) return;
          this.pause();
          this.onError?.(new Error(t('player.slowerStoppedUnexpected')));
        };
      }
      this.playing = true;
      for (const track of this.tracks) {
        const trackOffset = track.offset || 0;
        const local = this.offset - trackOffset;
        const bufferBase = track.bufferOffset || 0;
        const bufferOffset = bufferBase + Math.max(0, local);
        const available = track.buffer.duration - bufferOffset;
        const remaining = this.duration - Math.max(this.offset, trackOffset);
        const trackEnd = trackOffset + track.buffer.duration - bufferBase;
        if (available <= 0 || remaining <= 0) continue;
        const when = startTime + Math.max(0, -local);
        const source = context.createBufferSource();
        const gain = context.createGain();
        source.buffer = track.buffer;
        source.playbackRate.value = this.playbackRate;
        source.connect(gain).connect(destination);
        gain.gain.value = this.trackGain(track);
        if (!this.tempoNode && trackEnd >= this.duration - 0.02) {
          source.onended = () => {
            if (generation === this.generation && this.playing && this.position() >= this.duration - 0.02) {
              this.pause(); this.offset = 0;
            }
          };
        }
        this.nodes.push({source, gain, track});
        source.start(when, bufferOffset, Math.min(available, remaining * this.playbackRate));
      }
    } catch (error) {
      if (generation !== this.generation) return;
      this.pause();
      throw error;
    } finally {
      if (generation === this.generation) this.starting = false;
    }
  }
  async loadTempoModule(context) {
    if (!context.audioWorklet) throw new Error(t('player.slowerUnavailable'));
    if (!this.tempoModule) {
      this.tempoModule = context.audioWorklet.addModule('/tempo-worklet.js').catch(error => {
        this.tempoModule = null;
        throw new Error(t('player.slowerPrepareFailed'), {cause: error});
      });
    }
    await this.tempoModule;
  }
  async setPlaybackRate(rate) {
    if (!Number.isFinite(rate) || rate < 0.5 || rate > 1) throw new RangeError(t('player.speedRange'));
    if (rate === this.playbackRate) return;
    const resume = this.playing || this.starting;
    this.pause();
    this.playbackRate = rate;
    if (resume) await this.play();
  }
  async seek(seconds) {
    const resume = this.playing || this.starting;
    this.pause();
    this.offset = Math.max(0, Math.min(this.duration, seconds));
    if (resume) await this.play();
  }
  trackGain(track) {
    const soloing = this.tracks.some(t => t.solo);
    return track.muted || (soloing && !track.solo) ? 0 : track.volume;
  }
  updateMix() {
    for (const {gain, track} of this.nodes) {
      gain.gain.setTargetAtTime(this.trackGain(track), this.context.currentTime, 0.015);
    }
  }
  setVolume(value) {
    this.volume = value;
    if (this.master) this.master.gain.setTargetAtTime(value, this.context.currentTime, 0.015);
  }
}
