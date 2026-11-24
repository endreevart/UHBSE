import { AbsoluteFill, Sequence, useCurrentFrame } from "remotion";
import { Field } from "../field";
import { BEAT, progress } from "../motion";
import { cam, Mark, Plate, Shot, TypeCard } from "../shots";
import { theme } from "../theme";
import type { MediaSummary } from "../types";

const COLORS = [theme.control, theme.accentHi, theme.warm];

function World({ frame, summary }: { frame: number; summary: MediaSummary }) {
  const grow = progress(frame, 58, 148);
  const fork = 0.32;
  const labels = summary.branches.labels;
  return (
    <svg viewBox="0 0 980 560" width="980">
      <rect x="0" y="0" width="980" height="560" rx="18" fill="rgba(8,12,20,0.7)" stroke="rgba(120,170,255,0.18)" />
      <line
        x1="80"
        y1="280"
        x2={80 + 280 * Math.min(grow / fork, 1)}
        y2="280"
        stroke={theme.ink}
        strokeWidth="5"
        strokeLinecap="round"
      />
      {grow > fork
        ? COLORS.map((color, i) => {
            const t = (grow - fork) / (1 - fork);
            const y = 90 + i * 190;
            return (
              <g key={color}>
                <line
                  x1="360"
                  y1="280"
                  x2={360 + 500 * t}
                  y2={280 + (y - 280) * t}
                  stroke={color}
                  strokeWidth="4"
                  strokeLinecap="round"
                />
                <circle cx={360 + 500 * t} cy={280 + (y - 280) * t} r="8" fill={color} />
                <text x="80" y={430 + i * 34} fill={color} fontSize="22">
                  {labels[i]}
                </text>
              </g>
            );
          })
        : null}
    </svg>
  );
}

export const Branches: React.FC<MediaSummary> = (summary) => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill>
      <Field />
      <Sequence from={0} durationInFrames={BEAT.titleUntil} layout="none">
        <TypeCard
          frame={frame}
          from={BEAT.titleFrom}
          until={BEAT.titleUntil}
          lines={[{ text: "One start" }, { text: "three endings", accent: true }]}
        />
      </Sequence>
      <Shot from={BEAT.plateFrom} duration={BEAT.plateDur} camFrom={cam(1.05, 8, 12)} camTo={cam(1.0, -6, -8)}>
        <Plate tilt={progress(frame, 50, 160) * -6 + 5}>
          <World frame={frame} summary={summary} />
        </Plate>
      </Shot>
      <Sequence from={BEAT.closerFrom} durationInFrames={BEAT.duration - BEAT.closerFrom} layout="none">
        <TypeCard
          frame={frame}
          from={BEAT.closerIn}
          until={BEAT.duration}
          lines={[{ text: "Branches" }, { text: "stay isolated", accent: true }]}
        />
      </Sequence>
      <Mark summary={summary} />
    </AbsoluteFill>
  );
};
