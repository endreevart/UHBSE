import { AbsoluteFill, Sequence, useCurrentFrame } from "remotion";
import { Field } from "../field";
import { BEAT, progress } from "../motion";
import { cam, fmt, Mark, Plate, Shot, TypeCard } from "../shots";
import { theme } from "../theme";
import type { MediaSummary } from "../types";

function World({ frame, summary }: { frame: number; summary: MediaSummary }) {
  const loaded = summary.scope.cohort_loaded_subjects;
  const keep10 = progress(frame, 72, 112);
  const keep1 = progress(frame, 116, 148);
  const cols = 10;
  return (
    <svg viewBox="0 0 980 720" width="980">
      {Array.from({ length: loaded }, (_, i) => {
        const col = i % cols;
        const row = Math.floor(i / cols);
        const x = 70 + col * 86;
        const y = 40 + row * 52;
        const inTen = i < summary.scope.timelines_built_subjects;
        const inOne = i < summary.scope.simulated_subjects;
        let opacity = 1;
        let fill: string = "rgba(180,190,210,0.45)";
        if (!inTen) opacity = 1 - keep10;
        else if (!inOne) {
          opacity = 1 - keep1 * 0.85;
          fill = theme.accent;
        } else fill = theme.accentHi;
        return <circle key={i} cx={x} cy={y} r="11" fill={fill} opacity={Math.max(0, opacity)} />;
      })}
      <text x="70" y="640" fill={theme.ink} fontSize="40" fontFamily={theme.mono}>
        {fmt(loaded)}  →  {fmt(summary.scope.timelines_built_subjects)}  →  {fmt(summary.scope.simulated_subjects)}
      </text>
    </svg>
  );
}

export const Scope: React.FC<MediaSummary> = (summary) => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill>
      <Field />
      <Sequence from={0} durationInFrames={BEAT.titleUntil} layout="none">
        <TypeCard
          frame={frame}
          from={BEAT.titleFrom}
          until={BEAT.titleUntil}
          lines={[{ text: "Honest" }, { text: "about scope", accent: true }]}
        />
      </Sequence>
      <Shot from={BEAT.plateFrom} duration={BEAT.plateDur} camFrom={cam(1.05, 0, 14)} camTo={cam(1.0, 0, -8)}>
        <Plate tilt={progress(frame, 50, 160) * -6 + 5}>
          <World frame={frame} summary={summary} />
        </Plate>
      </Shot>
      <Sequence from={BEAT.closerFrom} durationInFrames={BEAT.duration - BEAT.closerFrom} layout="none">
        <TypeCard
          frame={frame}
          from={BEAT.closerIn}
          until={BEAT.duration}
          lines={[{ text: "One hundred" }, { text: "to one", accent: true }]}
        />
      </Sequence>
      <Mark summary={summary} />
    </AbsoluteFill>
  );
};
