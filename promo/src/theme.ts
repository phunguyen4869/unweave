import {loadFont as loadDisplay} from '@remotion/google-fonts/SpaceGrotesk';
import {loadFont as loadBody} from '@remotion/google-fonts/Inter';
import {useVideoConfig} from 'remotion';

export const DISPLAY = loadDisplay().fontFamily;
export const BODY = loadBody().fontFamily;

// Same tokens as app/unweave/web/css/base.css and js/core/constants.js.
export const C = {
  bg: '#0b0c0f',
  surface: '#15181e',
  surface2: '#1b1f26',
  line: '#242932',
  text: '#eef0f4',
  text2: '#b3b9c6',
  text3: '#7c8494',
  accent: '#ff8a3d',
  accent2: '#ff5c6c',
  onAccent: '#1a0d06',
};

export const STEMS = [
  {id: 'vocals', label: 'Vocals', color: '#ff8a3d'},
  {id: 'drums', label: 'Drums', color: '#5ec8ff'},
  {id: 'bass', label: 'Bass', color: '#b48cff'},
  {id: 'guitar', label: 'Guitar', color: '#4fe0a8'},
  {id: 'piano', label: 'Piano', color: '#ffd166'},
  {id: 'other', label: 'Other', color: '#ff6f91'},
];

/** 1 at 1080p landscape; the vertical cut keeps the same sizes against its width. */
export const useScale = () => {
  const {width, height} = useVideoConfig();
  return Math.min(width, height) / 1080;
};

export const useVertical = () => {
  const {width, height} = useVideoConfig();
  return height > width;
};

/** Deterministic 0-1 noise so every render draws the same waveform. */
export const noise = (n: number) => {
  const x = Math.sin(n * 12.9898 + 78.233) * 43758.5453;
  return x - Math.floor(x);
};
