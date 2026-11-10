import React from 'react';
import {Composition} from 'remotion';
import {Video2} from './Video2';

// v2: 24 fps. Los golpes bajan a 12 fps dentro de la animacion. El grano se agrega con ffmpeg.
export const Root: React.FC = () => (
  <Composition id="Video" component={Video2} durationInFrames={600} fps={24} width={1080} height={1920} />
);
