import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { enter, flow } from "../motion";
import { BigType, Fade, Ride, SeriesChrome, SeriesField, Thesis } from "./chrome";
import { SERIES_COLORS as C, episodeOf, type Episode, type SeriesFixture } from "./types";

export const Roadmap04: React.FC<SeriesFixture> = (fixture) => {
  const episode = episodeOf(fixture, "Roadmap04");
  return (
    <AbsoluteFill>
      <SeriesField />
      <Ride>
        <Fade from={0} until={56}>
          <BigType lines={episode.hook} top={270} />
        </Fade>
        <Fade from={52} until={140}>
          <ForkSplit episode={episode} />
        </Fade>
        <Fade from={136} until={208}>
          <ForkLock episode={episode} />
        </Fade>
        <Fade from={204} until={270}>
          <Thesis text={episode.thesis} />
        </Fade>
      </Ride>
      <SeriesChrome episode={episode} index={4} />
    </AbsoluteFill>
  );
};

function ForkSplit({ episode }: { episode: Episode }) {
  const frame = useCurrentFrame();
  const split = interpolate(frame, [6, 28], [0, 1], flow);
  const hashes = episode.hashes || {};
  return (
    <div style={{ position: "absolute", left: 88, right: 88, top: 230, fontFamily: C.font }}>
      <div style={{ color: C.computed, fontSize: 28, letterSpacing: "0.08em" }}>{episode.checkpoint_label}</div>
      <div style={{ color: C.muted, fontSize: 22, marginTop: 10, fontFamily: C.mono }}>hash {hashes.checkpoint}</div>
      <div
        style={{
          height: 6,
          marginTop: 24,
          background: C.computed,
          transform: `scaleX(${interpolate(frame, [4, 22], [0.12, 1], flow)})`,
          transformOrigin: "left center",
          opacity: 0.7,
        }}
      />
      <div style={{ display: "flex", gap: 24, marginTop: 28 }}>
        {(episode.branches || []).map((label, i) => (
          <div
            key={label}
            style={{
              flex: 1,
              minHeight: 240,
              padding: 22,
              border: `1px solid ${i === 0 ? C.computed : C.synthetic}`,
              transform: `translate(${i === 0 ? -split * 10 : split * 10}px, ${(1 - split) * 18}px) scale(${0.94 + split * 0.06})`,
              opacity: 0.25 + split * 0.75,
            }}
          >
            <div style={{ color: i === 0 ? C.computed : C.synthetic, fontSize: 22, letterSpacing: "0.06em" }}>
              {label}
            </div>
            <div style={{ color: C.ink, fontSize: 20, marginTop: 16, fontFamily: C.mono }}>
              {i === 0 ? hashes.counterfactual : hashes.event_fork}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ForkLock({ episode }: { episode: Episode }) {
  const frame = useCurrentFrame();
  const event = interpolate(frame, [4, 16], [0, 1], enter);
  const iso = interpolate(frame, [14, 26], [0, 1], enter);
  const roll = interpolate(frame, [28, 42], [0, 1], enter);
  const hashes = episode.hashes || {};
  return (
    <div style={{ position: "absolute", left: 88, right: 88, top: 250, fontFamily: C.font }}>
      <div
        style={{
          color: C.synthetic,
          fontSize: 32,
          opacity: event,
          transform: `scale(${0.92 + event * 0.08})`,
        }}
      >
        {episode.event_label} · WEEK {episode.event_week}
      </div>
      <div style={{ color: C.muted, marginTop: 16, fontSize: 22, opacity: event }}>
        first divergence week {episode.divergence_week} · changed variables {episode.changed_variables}
      </div>
      {(episode.isolation || []).map((line, i) => {
        const t = interpolate(frame, [16 + i * 5, 16 + i * 5 + 8], [0, 1], enter);
        return (
          <div key={line} style={{ color: C.observed, fontSize: 24, marginTop: 12, opacity: iso * t }}>
            {line}
          </div>
        );
      })}
      <div
        style={{
          color: C.pass,
          fontSize: 26,
          marginTop: 28,
          fontFamily: C.mono,
          opacity: roll,
          transform: `translateY(${(1 - roll) * 12}px)`,
        }}
      >
        {episode.rollback_label}
      </div>
      <div style={{ color: C.muted, fontSize: 20, marginTop: 8, fontFamily: C.mono, opacity: roll }}>
        {hashes.rollback} = {hashes.counterfactual}
      </div>
    </div>
  );
}
