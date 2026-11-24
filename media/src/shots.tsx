import type { ReactNode } from "react";
import { AbsoluteFill, interpolate, Sequence, useCurrentFrame } from "remotion";
import { clampEase, enter, flow } from "./motion";
import { theme } from "./theme";
import type { MediaSummary } from "./types";

export type Cam = {
  x: number;
  y: number;
  scale: number;
  rotate: number;
};

export const cam = (scale: number, x = 0, y = 0, rotate = 0): Cam => ({
  scale,
  x,
  y,
  rotate,
});

function mixCam(from: Cam, to: Cam, t: number): Cam {
  const m = (a: number, b: number) => a + (b - a) * t;
  return {
    x: m(from.x, to.x),
    y: m(from.y, to.y),
    scale: m(from.scale, to.scale),
    rotate: m(from.rotate, to.rotate),
  };
}

export function Shot({
  from,
  duration,
  camFrom,
  camTo,
  fadeIn = 10,
  fadeOut = 10,
  children,
}: {
  from: number;
  duration: number;
  camFrom: Cam;
  camTo: Cam;
  fadeIn?: number;
  fadeOut?: number;
  children: ReactNode;
}) {
  return (
    <Sequence from={from} durationInFrames={duration} layout="none">
      <ShotBody
        duration={duration}
        camFrom={camFrom}
        camTo={camTo}
        fadeIn={fadeIn}
        fadeOut={fadeOut}
      >
        {children}
      </ShotBody>
    </Sequence>
  );
}

function ShotBody({
  duration,
  camFrom,
  camTo,
  fadeIn,
  fadeOut,
  children,
}: {
  duration: number;
  camFrom: Cam;
  camTo: Cam;
  fadeIn: number;
  fadeOut: number;
  children: ReactNode;
}) {
  const frame = useCurrentFrame();
  const t = interpolate(frame, [0, Math.max(1, duration - 1)], [0, 1], flow);
  const opacity = interpolate(
    frame,
    [0, fadeIn, duration - fadeOut, duration],
    [0, 1, 1, 0],
    clampEase,
  );
  const c = mixCam(camFrom, camTo, t);
  return (
    <AbsoluteFill
      style={{
        opacity,
        transform: `translate(${c.x}px, ${c.y}px) scale(${c.scale}) rotate(${c.rotate}deg)`,
        transformOrigin: "50% 45%",
      }}
    >
      {children}
    </AbsoluteFill>
  );
}

export function Plate({
  children,
  tilt = 0,
}: {
  children: ReactNode;
  tilt?: number;
}) {
  return (
    <AbsoluteFill
      style={{
        perspective: 1600,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <div
        style={{
          transform: `rotateX(${14 + tilt}deg) rotateY(${-18 + tilt * 0.35}deg)`,
          transformOrigin: "center",
          width: 980,
        }}
      >
        {children}
      </div>
    </AbsoluteFill>
  );
}

export function TypeCard({
  lines,
  frame,
  from,
  until,
}: {
  lines: { text: string; accent?: boolean }[];
  frame: number;
  from: number;
  until: number;
}) {
  return (
    <AbsoluteFill
      style={{
        justifyContent: "center",
        padding: "0 72px",
        fontFamily: theme.font,
      }}
    >
      {lines.map((line, i) => {
        const t = interpolate(frame, [from + i * 8, from + 12 + i * 8], [0, 1], enter);
        const fade = interpolate(frame, [until - 10, until], [1, 0], clampEase);
        return (
          <div
            key={line.text}
            style={{
              fontSize: 86,
              fontWeight: 450,
              letterSpacing: "-0.045em",
              lineHeight: 1.12,
              color: line.accent ? theme.accentHi : theme.ink,
              filter: `blur(${(1 - t) * 7}px)`,
              transform: `translateX(${(1 - t) * 18}px)`,
              opacity: t * fade,
            }}
          >
            {line.text}
          </div>
        );
      })}
    </AbsoluteFill>
  );
}

export function Mark({ summary }: { summary: MediaSummary }) {
  return (
    <AbsoluteFill style={{ pointerEvents: "none", fontFamily: theme.font }}>
      <div
        style={{
          position: "absolute",
          top: 56,
          left: 56,
          letterSpacing: "0.28em",
          fontSize: 16,
          color: theme.faint,
          textTransform: "uppercase",
        }}
      >
        UHBSE
      </div>
      <div
        style={{
          position: "absolute",
          top: 56,
          right: 56,
          letterSpacing: "0.12em",
          fontSize: 16,
          color: theme.faint,
        }}
      >
        v{summary.slice_version}
      </div>
      <div
        style={{
          position: "absolute",
          bottom: 52,
          left: 56,
          right: 56,
          color: theme.faint,
          fontSize: 16,
          lineHeight: 1.4,
        }}
      >
        {summary.disclaimer}
      </div>
    </AbsoluteFill>
  );
}

export function fmt(n: number): string {
  return n.toLocaleString("en-US");
}
