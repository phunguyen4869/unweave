import {el} from './core.js';
import {t} from './i18n.js';

const clamp = (value, minimum, maximum) => Math.max(minimum, Math.min(maximum, value));

export function formatClock(seconds, decimals = 3) {
  const factor = 10 ** decimals;
  seconds = Math.round(Math.max(0, seconds || 0) * factor) / factor;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds - minutes * 60;
  // Two digits of seconds, plus the point and the decimals when there are any.
  return `${minutes}:${rest.toFixed(decimals).padStart(decimals ? decimals + 3 : 2, '0')}`;
}

function spokenTime(seconds) {
  seconds = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  const parts = [];
  if (minutes) parts.push(t(minutes === 1 ? 'time.minute' : 'time.minutes', {n: minutes}));
  parts.push(t(rest === 1 ? 'time.second' : 'time.seconds', {n: rest}));
  return parts.join(' ');
}

export function sectionText(range, offset = 0) {
  const start = range.start + offset;
  const end = range.end + offset;
  return t('trim.sectionText', {start: formatClock(start, 1), end: formatClock(end, 1), length: (range.end - range.start).toFixed(1)});
}

export function trimRequest(range, duration) {
  if (!range || !duration || !Number.isFinite(range.start) || !Number.isFinite(range.end)) return null;
  if (range.start <= 0.001 && range.end >= duration - 0.001) return null;
  return {start: Number(range.start.toFixed(3)), end: Number(range.end.toFixed(3))};
}

export class TrimEditor {
  constructor(mount, options = {}) {
    this.mount = mount;
    const duration = Number(options.duration);
    this.duration = Number.isFinite(duration) ? Math.max(0, duration) : 0;
    this.buffer = options.buffer || null;
    this.displayOffset = Number(options.displayOffset) || 0;
    this.start = clamp(Number(options.start ?? 0), 0, this.duration);
    this.end = clamp(Number(options.end ?? this.duration), 0, this.duration);
    if (this.end <= this.start) this.end = this.duration;
    this.onChange = options.onChange || (() => {});
    this.onPreview = options.onPreview || null;
    this.hint = options.hint || t('trim.hintDefault');
    this.abort = new AbortController();
    this.previewSource = null;
    this.previewContext = null;
    this.previewFrame = 0;
    this.drag = null;
    this.build();
    this.draw();
    this.render();
  }

  build() {
    const signal = this.abort.signal;
    this.mount.replaceChildren();
    const editor = el('div', 'trim-editor');
    this.wave = el('div', 'trim-wave');
    this.canvas = el('canvas');
    this.canvas.setAttribute('aria-hidden', 'true');
    this.dimLeft = el('div', 'trim-dim trim-dim-left');
    this.dimRight = el('div', 'trim-dim trim-dim-right');
    this.selection = el('div', 'trim-selection');
    this.startHandle = this.handle(t('trim.dragStart'));
    this.endHandle = this.handle(t('trim.dragEnd'));
    this.playhead = el('span', 'trim-playhead');
    this.playhead.hidden = true;
    this.wave.append(this.canvas, this.dimLeft, this.dimRight, this.selection,
      this.startHandle, this.endHandle, this.playhead);

    this.startHandle.addEventListener('pointerdown', event => this.beginDrag(event, 'start'), {signal});
    this.endHandle.addEventListener('pointerdown', event => this.beginDrag(event, 'end'), {signal});
    this.selection.addEventListener('pointerdown', event => this.beginDrag(event, 'move'), {signal});
    this.startHandle.addEventListener('keydown', event => this.onHandleKey(event, 'start'), {signal});
    this.endHandle.addEventListener('keydown', event => this.onHandleKey(event, 'end'), {signal});

    const readouts = el('div', 'trim-readouts');
    this.startRead = el('span', 'trim-readout-value');
    this.endRead = el('span', 'trim-readout-value');
    this.lengthRead = el('span', 'trim-readout-value');
    for (const [label, node] of [[t('trim.start'), this.startRead], [t('trim.end'), this.endRead], [t('trim.length'), this.lengthRead]]) {
      const block = el('div', 'trim-readout-block');
      block.append(el('span', 'trim-readout-label', label), node);
      readouts.append(block);
    }

    const fields = el('div', 'trim-fields');
    const startLabel = el('label', 'trim-field', t('trim.start'));
    this.startInput = this.numberInput(t('trim.startAriaLabel'));
    startLabel.append(this.startInput);
    const endLabel = el('label', 'trim-field', t('trim.end'));
    this.endInput = this.numberInput(t('trim.endAriaLabel'));
    endLabel.append(this.endInput);
    const actions = el('div', 'trim-actions');
    this.fullButton = el('button', 'btn btn-ghost btn-sm', t('trim.fullSong'));
    this.fullButton.type = 'button';
    this.fullButton.onclick = () => this.setRange(0, this.duration);
    this.previewButton = el('button', 'btn btn-ghost btn-sm', t('trim.preview'));
    this.previewButton.type = 'button';
    this.previewButton.disabled = !this.buffer;
    this.previewButton.onclick = () => this.togglePreview();
    actions.append(this.fullButton, this.previewButton);
    fields.append(startLabel, endLabel, actions);

    this.startInput.addEventListener('change', () => this.applyInputs(), {signal});
    this.endInput.addEventListener('change', () => this.applyInputs(), {signal});

    editor.append(this.wave, readouts, fields, el('p', 'trim-hint', this.hint));
    this.mount.append(editor);
    if (window.ResizeObserver) {
      this.resizeObserver = new ResizeObserver(() => this.draw());
      this.resizeObserver.observe(this.wave);
    }
  }

  handle(label) {
    const button = el('button', 'trim-handle');
    button.type = 'button';
    button.setAttribute('role', 'slider');
    button.setAttribute('aria-label', label);
    return button;
  }

  numberInput(label) {
    const input = el('input');
    input.type = 'number';
    input.step = '0.001';
    input.min = '0';
    input.setAttribute('aria-label', label);
    return input;
  }

  snap(value) {
    return Math.min(this.duration, Math.max(0, Math.round(value * 100) / 100));
  }

  getRange() {
    return {start: this.start, end: this.end};
  }

  setRange(start, end, notify = true) {
    if (this.previewSource) this.stopPreview();
    start = this.snap(start);
    end = this.snap(end);
    const gap = Math.min(0.01, this.duration);
    if (end <= start) end = Math.min(this.duration, start + gap);
    if (start >= end) start = Math.max(0, end - gap);
    this.start = start;
    this.end = end;
    this.render();
    if (notify) this.onChange(this.getRange());
  }

  beginDrag(event, mode) {
    if (!this.duration) return;
    event.preventDefault();
    const box = this.wave.getBoundingClientRect();
    this.drag = {mode, origin: event.clientX, width: Math.max(1, box.width),
      start: this.start, end: this.end};
    const move = moveEvent => {
      if (!this.drag) return;
      const delta = (moveEvent.clientX - this.drag.origin) / this.drag.width * this.duration;
      if (this.drag.mode === 'start') {
        this.setRange(clamp(this.drag.start + delta, 0, this.end), this.end);
      } else if (this.drag.mode === 'end') {
        this.setRange(this.start, clamp(this.drag.end + delta, this.start, this.duration));
      } else {
        const length = this.drag.end - this.drag.start;
        const start = clamp(this.drag.start + delta, 0, this.duration - length);
        this.setRange(start, start + length);
      }
    };
    const up = () => {
      this.drag = null;
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  }

  onHandleKey(event, which) {
    const step = event.shiftKey ? 1 : 0.1;
    let handled = true;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowDown') {
      if (which === 'start') this.setRange(this.start - step, this.end);
      else this.setRange(this.start, this.end - step);
    } else if (event.key === 'ArrowRight' || event.key === 'ArrowUp') {
      if (which === 'start') this.setRange(this.start + step, this.end);
      else this.setRange(this.start, this.end + step);
    } else if (event.key === 'Home') {
      if (which === 'start') this.setRange(0, this.end);
      else this.setRange(this.start, this.start);
    } else if (event.key === 'End') {
      if (which === 'start') this.setRange(this.end, this.end);
      else this.setRange(this.start, this.duration);
    } else {
      handled = false;
    }
    if (handled) event.preventDefault();
  }

  applyInputs() {
    const start = Number(this.startInput.value) - this.displayOffset;
    const end = Number(this.endInput.value) - this.displayOffset;
    if (!Number.isFinite(start) || !Number.isFinite(end)) {
      this.render();
      return;
    }
    this.setRange(start, end);
  }

  render() {
    const percent = value => this.duration ? value / this.duration * 100 : 0;
    this.selection.style.left = `${percent(this.start)}%`;
    this.selection.style.width = `${percent(this.end - this.start)}%`;
    this.dimLeft.style.width = `${percent(this.start)}%`;
    this.dimRight.style.left = `${percent(this.end)}%`;
    this.startHandle.style.left = `${percent(this.start)}%`;
    this.endHandle.style.left = `${percent(this.end)}%`;
    for (const [node, value, name] of [[this.startHandle, this.start, 'start'],
      [this.endHandle, this.end, 'end']]) {
      node.setAttribute('aria-valuemin', '0');
      node.setAttribute('aria-valuemax', this.duration.toFixed(3));
      node.setAttribute('aria-valuenow', value.toFixed(3));
      node.setAttribute('aria-valuetext', t(name === 'start' ? 'trim.startAt' : 'trim.endAt', {time: spokenTime(value + this.displayOffset)}));
    }
    this.startRead.textContent = formatClock(this.start + this.displayOffset);
    this.endRead.textContent = formatClock(this.end + this.displayOffset);
    this.lengthRead.textContent = `${(this.end - this.start).toFixed(1)} s`;
    this.startInput.value = (this.start + this.displayOffset).toFixed(3);
    this.endInput.value = (this.end + this.displayOffset).toFixed(3);
    this.previewButton.disabled = !this.buffer || this.end <= this.start;
  }

  draw() {
    const width = Math.max(240, this.wave.clientWidth || this.mount.clientWidth || 600);
    const height = 64;
    const scale = window.devicePixelRatio || 1;
    this.canvas.width = Math.round(width * scale);
    this.canvas.height = Math.round(height * scale);
    this.canvas.style.width = '100%';
    this.canvas.style.height = `${height}px`;
    const context = this.canvas.getContext('2d');
    context.scale(scale, scale);
    context.clearRect(0, 0, width, height);
    if (!this.buffer) {
      context.fillStyle = 'rgba(255,255,255,.12)';
      context.fillRect(0, height / 2, width, 1);
      return;
    }
    const data = this.buffer.getChannelData(0);
    const columns = Math.floor(width / 3);
    const stride = Math.max(1, Math.floor(data.length / columns));
    const skip = Math.max(1, Math.floor(stride / 64));
    context.fillStyle = 'rgba(255, 138, 61, .55)';
    for (let column = 0; column < columns; column++) {
      let peak = 0;
      for (let index = column * stride; index < Math.min((column + 1) * stride, data.length); index += skip) {
        peak = Math.max(peak, Math.abs(data[index]));
      }
      const bar = Math.max(2, Math.min(height - 8, peak * height * 1.2));
      context.fillRect(column * 3, (height - bar) / 2, 2, bar);
    }
  }

  setBuffer(buffer) {
    this.buffer = buffer;
    this.draw();
    this.render();
  }

  async togglePreview() {
    if (this.previewSource) {
      this.stopPreview();
      return;
    }
    if (!this.buffer || this.end <= this.start) return;
    this.onPreview?.(this.getRange());
    try {
      this.previewContext ||= new AudioContext();
      await this.previewContext.resume();
      const source = this.previewContext.createBufferSource();
      const gain = this.previewContext.createGain();
      source.buffer = this.buffer;
      gain.gain.value = 0.7;
      source.connect(gain).connect(this.previewContext.destination);
      source.onended = () => this.stopPreview();
      source.start(0, this.start, this.end - this.start);
      this.previewSource = source;
      this.previewButton.textContent = t('trim.stop');
      this.playhead.hidden = false;
      const started = this.previewContext.currentTime;
      const tick = () => {
        if (!this.previewSource) return;
        const elapsed = this.previewContext.currentTime - started;
        const position = Math.min(this.end, this.start + elapsed);
        this.playhead.style.left = `${this.duration ? position / this.duration * 100 : 0}%`;
        this.previewFrame = requestAnimationFrame(tick);
      };
      tick();
    } catch (_) {
      this.stopPreview();
    }
  }

  stopPreview() {
    cancelAnimationFrame(this.previewFrame);
    const source = this.previewSource;
    this.previewSource = null;
    if (source) {
      try { source.stop(); } catch (_) { /* already ended */ }
      source.disconnect();
    }
    this.previewButton.textContent = t('trim.preview');
    this.playhead.hidden = true;
  }

  destroy() {
    this.abort.abort();
    this.stopPreview();
    this.resizeObserver?.disconnect();
    this.previewContext?.close?.();
    this.mount.replaceChildren();
  }
}
