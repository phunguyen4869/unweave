import React from 'react';
import {Composition} from 'remotion';
import {Intro, INTRO_FRAMES} from './Intro';

export const Root: React.FC = () => (
  <>
    <Composition id="Intro" component={Intro} durationInFrames={INTRO_FRAMES} fps={30} width={1920} height={1080} />
    <Composition id="IntroVertical" component={Intro} durationInFrames={INTRO_FRAMES} fps={30} width={1080} height={1920} />
  </>
);
