import { AbsoluteFill, Sequence, useCurrentFrame } from "remotion";
import { Field } from "../field";
import { BEAT, progress } from "../motion";
import { cam, Mark, Plate, Shot, TypeCard } from "../shots";
import { theme } from "../theme";
import type { MediaSummary } from "../types";

const NODES = ["State_before", "+ Intervention", "+ Context", "+ Time"] as const;

function World({ frame }: { frame: number }) {
  const travel = progress(frame, 58, 145);
  const after = progress(frame, 138, 158);
  return (
    <svg viewBox="0 0 980 720" width="980">
      {NODES.map((label, i) => {
        const on = travel > (i + 0.15) / 4;
        return (
          <g key={label}>
            <rect
              x="80"
              y={40 + i * 130}
              width="820"
              height="100"
              rx="14"
              fill={on ? "rgba(40,80,160,0.35)" : "rgba(255,255,255,0.03)"}
              stroke={on ? theme.accent : "rgba(255,255,255,0.12)"}
              strokeWidth="1.5"
            />
            <text x="490" y={100 + i * 130} textAnchor="middle" fill={on ? theme.ink : theme.muted} fontSize="36" fontFamily={theme.mono}>
              {label}
            </text>
          </g>
        );
      })}
      <rect x="80" y="560" width="820" height="110" rx="14" fill={theme.accent} opacity={after} />
      <text x="490" y="628" textAnchor="middle" fill="#000" fontSize="40" fontFamily={theme.mono} opacity={after}>
        → State_after
      </text>
    </svg>
  );
}

export const Formula: React.FC<MediaSummary> = (summary) => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill>
      <Field />
      <Sequence from={0} durationInFrames={BEAT.titleUntil} layout="none">
        <TypeCard
          frame={frame}
          from={BEAT.titleFrom}
          until={BEAT.titleUntil}
          lines={[{ text: "State" }, { text: "plus time", accent: true }]}
        />
      </Sequence>
      <Shot from={BEAT.plateFrom} duration={BEAT.plateDur} camFrom={cam(1.05, 0, 18)} camTo={cam(1.0, 0, -8)}>
        <Plate tilt={progress(frame, 50, 160) * -6 + 4}>
          <World frame={frame} />
        </Plate>
      </Shot>
      <Sequence from={BEAT.closerFrom} durationInFrames={BEAT.duration - BEAT.closerFrom} layout="none">
        <TypeCard
          frame={frame}
          from={BEAT.closerIn}
          until={BEAT.duration}
          lines={[{ text: "becomes" }, { text: "State_after", accent: true }]}
        />
      </Sequence>
      <Mark summary={summary} />
    </AbsoluteFill>
  );
};
