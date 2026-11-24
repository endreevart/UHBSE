import { Easing, interpolate } from "remotion";

export const clampEase = {
  extrapolateLeft: "clamp" as const,
  extrapolateRight: "clamp" as const,
};

/** Accelerate, cruise, settle — same curve for camera and on-screen action. */
export const flow = {
  ...clampEase,
  easing: Easing.inOut(Easing.cubic),
};

export const enter = {
  ...clampEase,
  easing: Easing.out(Easing.cubic),
};

export const BEAT = {
  duration: 255,
  titleFrom: 3,
  titleUntil: 58,
  plateFrom: 46,
  plateDur: 128,
  closerFrom: 158,
  closerIn: 164,
} as const;

export function unit(i: number): number {
  return ((i * 9301 + 49297) % 233280) / 233280;
}

export function progress(frame: number, from: number, to: number): number {
  return interpolate(frame, [from, to], [0, 1], flow);
}
