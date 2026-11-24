import { AbsoluteFill, Sequence, useCurrentFrame } from "remotion";
import { Field } from "../field";
import { BEAT, progress } from "../motion";
import { cam, fmt, Mark, Plate, Shot, TypeCard } from "../shots";
import { theme } from "../theme";
import type { MediaSummary } from "../types";

const ROWS: { key: string; label: string }[] = [
  { key: "subject", label: "subjects" },
  { key: "source_record", label: "source records" },
  { key: "encounter", label: "encounters" },
  { key: "observation", label: "observations" },
  { key: "observation_component", label: "components" },
];

function World({ frame, summary }: { frame: number; summary: MediaSummary }) {
  const max = Math.max(...ROWS.map((r) => summary.row_counts[r.key] || 1));
  return (
    <svg viewBox="0 0 980 640" width="980">
      <rect x="0" y="0" width="980" height="640" rx="18" fill="rgba(8,12,20,0.72)" stroke="rgba(120,170,255,0.22)" />
      {ROWS.map((row, i) => {
        const value = summary.row_counts[row.key] || 0;
        const t = progress(frame, 58 + i * 6, 108 + i * 6);
        const share = Math.log(value + 1) / Math.log(max + 1);
        const y = 70 + i * 110;
        return (
          <g key={row.key}>
            <text x="48" y={y} fill={theme.muted} fontSize="24">
              {row.label}
            </text>
            <text x="932" y={y} textAnchor="end" fill={theme.ink} fontSize="32" fontFamily={theme.mono}>
              {fmt(Math.round(value * t))}
            </text>
            <rect x="48" y={y + 16} width="884" height="10" rx="5" fill="rgba(255,255,255,0.06)" />
            <rect x="48" y={y + 16} width={884 * share * t} height="10" rx="5" fill={theme.accent} />
          </g>
        );
      })}
    </svg>
  );
}

export const Load: React.FC<MediaSummary> = (summary) => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill>
      <Field />
      <Sequence from={0} durationInFrames={BEAT.titleUntil} layout="none">
        <TypeCard
          frame={frame}
          from={BEAT.titleFrom}
          until={BEAT.titleUntil}
          lines={[{ text: "Source A" }, { text: "becomes evidence", accent: true }]}
        />
      </Sequence>
      <Shot from={BEAT.plateFrom} duration={BEAT.plateDur} camFrom={cam(1.05, 0, 16)} camTo={cam(1.0, 0, -8)}>
        <Plate tilt={progress(frame, 50, 160) * -6 + 4}>
          <World frame={frame} summary={summary} />
        </Plate>
      </Shot>
      <Sequence from={BEAT.closerFrom} durationInFrames={BEAT.duration - BEAT.closerFrom} layout="none">
        <TypeCard
          frame={frame}
          from={BEAT.closerIn}
          until={BEAT.duration}
          lines={[{ text: fmt(summary.row_counts.source_record) }, { text: "source records", accent: true }]}
        />
      </Sequence>
      <Mark summary={summary} />
    </AbsoluteFill>
  );
};
