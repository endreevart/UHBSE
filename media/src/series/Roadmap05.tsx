import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { enter } from "../motion";
import { BigType, Fade, Ride, SeriesChrome, SeriesField, Thesis } from "./chrome";
import { SERIES_COLORS as C, episodeOf, type SeriesFixture } from "./types";

export const Roadmap05: React.FC<SeriesFixture> = (fixture) => {
  const episode = episodeOf(fixture, "Roadmap05");
  return (
    <AbsoluteFill>
      <SeriesField />
      <Ride>
        <Fade from={0} until={56}>
          <BigType lines={episode.hook} />
        </Fade>
        <Fade from={52} until={140}>
          <Tests items={episode.tests || []} />
        </Fade>
        <Fade from={136} until={208}>
          <Statuses episode={episode} />
        </Fade>
        <Fade from={204} until={270}>
          <Thesis text={episode.thesis} />
        </Fade>
      </Ride>
      <SeriesChrome episode={episode} index={5} />
    </AbsoluteFill>
  );
};

function Tests({ items }: { items: string[] }) {
  const frame = useCurrentFrame();
  return (
    <div style={{ position: "absolute", left: 88, right: 88, top: 230, fontFamily: C.font }}>
      {items.map((label, i) => {
        const start = 4 + i * 6;
        const t = interpolate(frame, [start, start + 8], [0, 1], enter);
        const failWindow = i === 2 && frame >= start && frame < start + 12;
        const passed = t > 0.72 && !failWindow;
        const color = failWindow ? C.reject : passed ? C.pass : C.muted;
        const mark = failWindow ? "FAIL" : passed ? "PASS" : "…";
        return (
          <div
            key={label}
            style={{
              display: "flex",
              justifyContent: "space-between",
              marginBottom: 12,
              opacity: 0.2 + t * 0.8,
              transform: `translateX(${(1 - t) * 18}px)`,
            }}
          >
            <div style={{ color: C.ink, fontSize: 22, maxWidth: 760 }}>{label}</div>
            <div style={{ color, fontSize: 20, letterSpacing: "0.12em", fontFamily: C.mono }}>{mark}</div>
          </div>
        );
      })}
    </div>
  );
}

function Statuses({ episode }: { episode: ReturnType<typeof episodeOf> }) {
  const frame = useCurrentFrame();
  return (
    <div style={{ position: "absolute", left: 88, right: 88, top: 320, fontFamily: C.font }}>
      {(episode.statuses || []).map((row, i) => {
        const t = interpolate(frame, [i * 8, i * 8 + 10], [0, 1], enter);
        return (
          <div key={row.label} style={{ marginBottom: 26, opacity: t, transform: `translateY(${(1 - t) * 16}px)` }}>
            <div style={{ color: C.muted, fontSize: 20, letterSpacing: "0.12em" }}>{row.label}</div>
            <div style={{ color: row.value.includes("NOT") ? C.reject : C.pass, fontSize: 44, fontWeight: 560 }}>
              {row.value}
            </div>
          </div>
        );
      })}
    </div>
  );
}
