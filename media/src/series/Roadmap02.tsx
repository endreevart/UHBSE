import { AbsoluteFill } from "remotion";
import { BigType, Fade, Grid, Ride, SeriesChrome, SeriesField, Stack, Thesis } from "./chrome";
import { episodeOf, type SeriesFixture } from "./types";

export const Roadmap02: React.FC<SeriesFixture> = (fixture) => {
  const episode = episodeOf(fixture, "Roadmap02");
  return (
    <AbsoluteFill>
      <SeriesField />
      <Ride>
        <Fade from={0} until={56}>
          <BigType lines={episode.hook} />
        </Fade>
        <Fade from={52} until={140}>
          <Stack items={episode.flow || []} />
        </Fade>
        <Fade from={136} until={208}>
          <Grid items={episode.rejects || []} />
        </Fade>
        <Fade from={204} until={270}>
          <Thesis text={episode.thesis} />
        </Fade>
      </Ride>
      <SeriesChrome episode={episode} index={2} />
    </AbsoluteFill>
  );
};
