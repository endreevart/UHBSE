import type { FC } from "react";
import { Composition } from "remotion";
import { Branches } from "./compositions/Branches";
import { Formula } from "./compositions/Formula";
import { Load } from "./compositions/Load";
import { Provenance } from "./compositions/Provenance";
import { Scope } from "./compositions/Scope";
import { Snapshot } from "./compositions/Snapshot";
import { Roadmap01 } from "./series/Roadmap01";
import { Roadmap02 } from "./series/Roadmap02";
import { Roadmap03 } from "./series/Roadmap03";
import { Roadmap04 } from "./series/Roadmap04";
import { Roadmap05 } from "./series/Roadmap05";
import { Roadmap06 } from "./series/Roadmap06";
import { DEFAULT_FIXTURE, type SeriesFixture } from "./series/types";
import { VIDEO } from "./theme";
import { DEFAULT_SUMMARY, type MediaSummary } from "./types";

const ids: { id: string; component: FC<MediaSummary> }[] = [
  { id: "Formula", component: Formula },
  { id: "Load", component: Load },
  { id: "Provenance", component: Provenance },
  { id: "Snapshot", component: Snapshot },
  { id: "Branches", component: Branches },
  { id: "Scope", component: Scope },
];

const series: { id: string; component: FC<SeriesFixture>; duration: number }[] = [
  { id: "Roadmap01", component: Roadmap01, duration: 270 },
  { id: "Roadmap02", component: Roadmap02, duration: 270 },
  { id: "Roadmap03", component: Roadmap03, duration: 270 },
  { id: "Roadmap04", component: Roadmap04, duration: 270 },
  { id: "Roadmap05", component: Roadmap05, duration: 270 },
  { id: "Roadmap06", component: Roadmap06, duration: 270 },
];

export const RemotionRoot: FC = () => {
  return (
    <>
      {ids.map((item) => (
        <Composition
          key={item.id}
          id={item.id}
          component={item.component}
          durationInFrames={VIDEO.duration}
          fps={VIDEO.fps}
          width={VIDEO.width}
          height={VIDEO.height}
          defaultProps={DEFAULT_SUMMARY}
        />
      ))}
      {series.map((item) => (
        <Composition
          key={item.id}
          id={item.id}
          component={item.component}
          durationInFrames={item.duration}
          fps={VIDEO.fps}
          width={VIDEO.width}
          height={VIDEO.height}
          defaultProps={DEFAULT_FIXTURE}
        />
      ))}
    </>
  );
};
