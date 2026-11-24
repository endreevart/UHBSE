import { AbsoluteFill, Sequence, useCurrentFrame } from "remotion";
import { Field } from "../field";
import { BEAT, progress } from "../motion";
import { cam, fmt, Mark, Plate, Shot, TypeCard } from "../shots";
import { theme } from "../theme";
import type { MediaSummary } from "../types";

function World({ frame, summary }: { frame: number; summary: MediaSummary }) {
  const cover = progress(frame, 58, 140);
  const ring = 2 * Math.PI * 168;
  return (
    <svg viewBox="0 0 980 620" width="980">
      <circle cx="490" cy="300" r="168" fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="22" />
      <circle
        cx="490"
        cy="300"
        r="168"
        fill="none"
        stroke={theme.accentHi}
        strokeWidth="22"
        strokeDasharray={`${ring * cover} ${ring}`}
        transform="rotate(-90 490 300)"
      />
      <text x="490" y="292" textAnchor="middle" fill={theme.ink} fontSize="48" fontFamily={theme.mono}>
        {fmt(Math.round(summary.provenance.valid_records * cover))}
      </text>
      <text x="490" y="336" textAnchor="middle" fill={theme.muted} fontSize="20" fontFamily={theme.mono}>
        of {fmt(summary.provenance.total_records_evaluated)}
      </text>
    </svg>
  );
}

export const Provenance: React.FC<MediaSummary> = (summary) => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill>
      <Field />
      <Sequence from={0} durationInFrames={BEAT.titleUntil} layout="none">
        <TypeCard
          frame={frame}
          from={BEAT.titleFrom}
          until={BEAT.titleUntil}
          lines={[{ text: "Every value" }, { text: "has an origin", accent: true }]}
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
          lines={[{ text: "Full coverage" }, { text: "layers never mix", accent: true }]}
        />
      </Sequence>
      <Mark summary={summary} />
    </AbsoluteFill>
  );
};
