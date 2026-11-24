import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { enter, flow } from "../motion";
import { BigType, Fade, Grid, Ride, SeriesChrome, SeriesField, Thesis } from "./chrome";
import { SERIES_COLORS as C, episodeOf, type Episode, type SeriesFixture } from "./types";

export const Roadmap03: React.FC<SeriesFixture> = (fixture) => {
  const episode = episodeOf(fixture, "Roadmap03");
  return (
    <AbsoluteFill>
      <SeriesField />
      <Ride>
        <Fade from={0} until={56}>
          <BigType lines={episode.hook} top={260} />
        </Fade>
        <Fade from={52} until={140}>
          <Grid items={episode.counts || []} />
        </Fade>
        <Fade from={136} until={208}>
          <Assemble episode={episode} />
        </Fade>
        <Fade from={204} until={270}>
          <Thesis text={episode.thesis} />
        </Fade>
      </Ride>
      <SeriesChrome episode={episode} index={3} />
    </AbsoluteFill>
  );
};

function Assemble({ episode }: { episode: Episode }) {
  const frame = useCurrentFrame();
  const gather = interpolate(frame, [4, 28], [0, 1], flow);
  const collapse = interpolate(frame, [24, 42], [0, 1], flow);
  return (
    <div style={{ position: "absolute", left: 88, right: 88, top: 250, fontFamily: C.font }}>
      <div style={{ color: C.faint, letterSpacing: "0.18em", fontSize: 16, marginBottom: 18 }}>
        {episode.composite_label}
      </div>
      {["encounters", "laboratory observations", "temporal ordering", "source references"].map((label, i) => {
        const t = interpolate(frame, [i * 5, i * 5 + 8], [0, 1], enter);
        return (
          <div key={label} style={{ marginBottom: 12, opacity: t }}>
            <div style={{ color: C.muted, fontSize: 18, marginBottom: 6 }}>{label}</div>
            <div
              style={{
                height: 36,
                background: C.observed,
                opacity: 0.22 + gather * (0.18 + i * 0.08),
                transform: `scaleX(${(0.28 + gather * 0.72) * (1 - collapse * 0.55)})`,
                transformOrigin: "left center",
              }}
            />
          </div>
        );
      })}
      <div
        style={{
          marginTop: 22,
          padding: 24,
          background: C.plate,
          border: `1px solid ${C.computed}`,
          color: C.computed,
          fontSize: 32,
          opacity: collapse,
          transform: `translateY(${(1 - collapse) * 18}px) scale(${0.92 + collapse * 0.08})`,
        }}
      >
        {episode.snapshot_label}
      </div>
      <div style={{ display: "flex", gap: 12, marginTop: 18 }}>
        {(episode.layers || []).map((layer, i) => {
          const t = interpolate(frame, [38 + i * 6, 38 + i * 6 + 8], [0, 1], enter);
          return (
            <div
              key={layer}
              style={{
                flex: 1,
                padding: 14,
                color: i === 0 ? C.observed : i === 1 ? C.computed : C.synthetic,
                border: "1px solid currentColor",
                fontSize: 18,
                letterSpacing: "0.08em",
                opacity: t,
                transform: `translateY(${(1 - t) * 12}px)`,
              }}
            >
              {layer}
            </div>
          );
        })}
      </div>
    </div>
  );
}
