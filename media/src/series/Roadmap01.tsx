import { AbsoluteFill } from "remotion";
import { BigType, Fade, Ride, SeriesChrome, SeriesField, Stack, Thesis } from "./chrome";
import { SERIES_COLORS as C, episodeOf, type SeriesFixture } from "./types";

export const Roadmap01: React.FC<SeriesFixture> = (fixture) => {
  const episode = episodeOf(fixture, "Roadmap01");
  return (
    <AbsoluteFill>
      <SeriesField />
      <Ride>
        <Fade from={0} until={56}>
          <BigType lines={episode.hook} />
        </Fade>
        <Fade from={52} until={140}>
          <Stack items={episode.funnel || []} />
        </Fade>
        <Fade from={136} until={208}>
          <Stack items={episode.stats || []} accent={C.observed} />
        </Fade>
        <Fade from={204} until={270}>
          <Thesis text={episode.thesis} />
        </Fade>
      </Ride>
      <SeriesChrome episode={episode} index={1} />
    </AbsoluteFill>
  );
};
