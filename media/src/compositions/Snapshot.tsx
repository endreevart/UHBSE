import { AbsoluteFill, Sequence, useCurrentFrame } from "remotion";
import { Field } from "../field";
import { BEAT, progress } from "../motion";
import { cam, fmt, Mark, Plate, Shot, TypeCard } from "../shots";
import { theme } from "../theme";
import type { MediaSummary } from "../types";

function World({ frame, summary }: { frame: number; summary: MediaSummary }) {
  const play = 70 + progress(frame, 58, 135) * 790;
  const cut = 70 + progress(frame, 118, 148) * 550;
  const dots = Array.from({ length: 20 }, (_, i) => i);
  return (
    <svg viewBox="0 0 980 520" width="980">
      <rect x="0" y="0" width="980" height="520" rx="18" fill="rgba(8,12,20,0.7)" stroke="rgba(120,170,255,0.2)" />
      <line x1="48" y1="260" x2="932" y2="260" stroke="rgba(255,255,255,0.08)" strokeDasharray="6 10" />
      {dots.map((i) => {
        const x = 70 + i * 42;
        const y = 260 + Math.sin(i * 0.62) * 70;
        const kept = x < cut;
        const lit = play > x;
        return (
          <circle
            key={i}
            cx={x}
            cy={y}
            r={lit ? 7 : 4}
            fill={kept ? theme.accentHi : "rgba(180,90,80,0.35)"}
            opacity={kept ? 1 : 0.35}
          />
        );
      })}
      <line x1={cut} x2={cut} y1="70" y2="450" stroke={theme.ink} strokeWidth="2" />
      <rect x={cut + 14} y="86" width="118" height="36" rx="8" fill="rgba(0,0,0,0.55)" stroke={theme.accent} />
      <text x={cut + 24} y="110" fill={theme.accentHi} fontSize="18" fontFamily={theme.mono}>
        T cut
      </text>
      <text x="48" y="490" fill={theme.muted} fontSize="22" fontFamily={theme.mono}>
        {fmt(summary.snapshot.excluded_future_count)} excluded
      </text>
    </svg>
  );
}

export const Snapshot: React.FC<MediaSummary> = (summary) => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill>
      <Field />
      <Sequence from={0} durationInFrames={BEAT.titleUntil} layout="none">
        <TypeCard
          frame={frame}
          from={BEAT.titleFrom}
          until={BEAT.titleUntil}
          lines={[{ text: "A cut" }, { text: "at time T", accent: true }]}
        />
      </Sequence>
      <Shot from={BEAT.plateFrom} duration={BEAT.plateDur} camFrom={cam(1.05, 10, 12)} camTo={cam(1.0, -6, -6)}>
        <Plate tilt={progress(frame, 50, 160) * -6 + 4}>
          <World frame={frame} summary={summary} />
        </Plate>
      </Shot>
      <Sequence from={BEAT.closerFrom} durationInFrames={BEAT.duration - BEAT.closerFrom} layout="none">
        <TypeCard
          frame={frame}
          from={BEAT.closerIn}
          until={BEAT.duration}
          lines={[{ text: "Future" }, { text: "stays future", accent: true }]}
        />
      </Sequence>
      <Mark summary={summary} />
    </AbsoluteFill>
  );
};
