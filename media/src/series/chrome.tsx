import type { ReactNode } from "react";
import { AbsoluteFill, interpolate, Sequence, useCurrentFrame, useVideoConfig } from "remotion";
import { Field } from "../field";
import { clampEase, enter, flow } from "../motion";
import { SERIES_COLORS as C, type Caption, type Episode } from "./types";

export function SeriesField() {
  return <Field />;
}

export function SeriesChrome({ episode, index }: { episode: Episode; index: number }) {
  const frame = useCurrentFrame();
  const caption = activeCaption(episode.captions, frame);
  const capT = interpolate(frame, [caption.from, caption.from + 8], [0, 1], enter);
  return (
    <AbsoluteFill style={{ pointerEvents: "none", fontFamily: C.font }}>
      <div style={{ position: "absolute", top: 56, left: 72, right: 72 }}>
        <div style={{ color: C.faint, letterSpacing: "0.28em", fontSize: 14 }}>UHBSE</div>
        <div style={{ color: C.muted, fontSize: 18, marginTop: 10, lineHeight: 1.35 }}>
          {episode.series_title}
        </div>
        <div style={{ color: C.ink, fontSize: 16, marginTop: 14, letterSpacing: "0.16em" }}>
          {String(index).padStart(2, "0")} / 06 · {episode.title.toUpperCase()}
        </div>
      </div>
      <div
        style={{
          position: "absolute",
          top: 56,
          right: 72,
          color: C.faint,
          fontSize: 13,
          letterSpacing: "0.08em",
          textAlign: "right",
          maxWidth: 280,
        }}
      >
        {episode.disclosure_label}
      </div>
      <div
        style={{
          position: "absolute",
          left: 72,
          right: 72,
          bottom: 118,
          minHeight: 72,
          color: C.ink,
          fontSize: 28,
          lineHeight: 1.25,
          fontWeight: 500,
          opacity: capT,
          transform: `translateY(${(1 - capT) * 10}px)`,
          filter: `blur(${(1 - capT) * 6}px)`,
        }}
      >
        {caption.text}
      </div>
      <div
        style={{
          position: "absolute",
          left: 72,
          right: 72,
          bottom: 48,
          color: C.faint,
          fontSize: 16,
          lineHeight: 1.35,
        }}
      >
        {episode.disclaimer}
      </div>
    </AbsoluteFill>
  );
}

function activeCaption(captions: Caption[], frame: number): Caption {
  const hit = captions.find((item) => frame >= item.from && frame < item.to);
  return hit || { from: frame, to: frame + 1, text: "" };
}

export function Ride({ children }: { children: ReactNode }) {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const t = interpolate(frame, [0, Math.max(1, durationInFrames - 1)], [0, 1], flow);
  const scale = 1.1 - t * 0.1;
  const y = interpolate(t, [0, 1], [14, -14], flow);
  const x = Math.sin(frame / 16) * 8;
  return (
    <AbsoluteFill style={{ transform: `translate(${x}px, ${y}px) scale(${scale})`, transformOrigin: "50% 42%" }}>
      {children}
    </AbsoluteFill>
  );
}

export function Fade({
  from,
  until,
  children,
}: {
  from: number;
  until: number;
  children: ReactNode;
}) {
  const duration = Math.max(1, until - from);
  return (
    <Sequence from={from} durationInFrames={duration} layout="none">
      <FadeBody duration={duration}>{children}</FadeBody>
    </Sequence>
  );
}

function FadeBody({ duration, children }: { duration: number; children: ReactNode }) {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [0, 4, duration - 4, duration], [0, 1, 1, 0], flow);
  const y = interpolate(frame, [0, 8], [16, 0], enter);
  const scale = interpolate(frame, [0, 10], [1.06, 1], enter);
  return (
    <AbsoluteFill style={{ opacity, transform: `translateY(${y}px) scale(${scale})`, transformOrigin: "50% 42%" }}>
      {children}
    </AbsoluteFill>
  );
}

export function BigType({ lines, top = 240 }: { lines: string[]; top?: number }) {
  const frame = useCurrentFrame();
  return (
    <div style={{ position: "absolute", left: 88, right: 88, top, fontFamily: C.font }}>
      {lines.map((line, i) => {
        const t = interpolate(frame, [i * 5, i * 5 + 8], [0, 1], enter);
        return (
          <div
            key={line}
            style={{
              color: C.ink,
              fontSize: line.length > 42 ? 46 : 58,
              fontWeight: 560,
              letterSpacing: "-0.035em",
              lineHeight: 1.12,
              marginBottom: 16,
              opacity: t,
              filter: `blur(${(1 - t) * 8}px)`,
              transform: `translateX(${(1 - t) * 28}px)`,
            }}
          >
            {line}
          </div>
        );
      })}
    </div>
  );
}

export function countDisplay(value: string, t: number): string {
  const clamped = Math.max(0, Math.min(1, t));
  const compact = value.replace(/,/g, "");
  const match = compact.match(/^(-?[\d.]+)([KMkm]?)$/);
  if (!match) return clamped > 0.12 ? value : "";
  const n = Number(match[1]);
  const suffix = match[2] ? match[2].toUpperCase() : "";
  const cur = n * clamped;
  if (!Number.isFinite(n)) return value;
  if (suffix) {
    const decimals = (match[1].split(".")[1] || "").length;
    return `${decimals ? cur.toFixed(decimals) : Math.round(cur)}${suffix}`;
  }
  if (value.includes(",")) return Math.round(cur).toLocaleString("en-US");
  if (value.includes(".")) return cur.toFixed((value.split(".")[1] || "").length);
  return String(Math.round(cur));
}

export function Stack({
  items,
  accent,
  from = 0,
}: {
  items: { label: string; value: string }[];
  accent?: string;
  from?: number;
}) {
  const frame = useCurrentFrame();
  const max = Math.max(...items.map((item) => parseMagnitude(item.value)), 1);
  return (
    <div style={{ position: "absolute", left: 96, right: 96, top: 236, fontFamily: C.font }}>
      {items.map((item, i) => {
        const start = from + i * 5;
        const t = interpolate(frame, [start, start + 10], [0, 1], enter);
        const bar = interpolate(frame, [start + 2, start + 14], [0.08, parseMagnitude(item.value) / max], flow);
        return (
          <div
            key={item.label}
            style={{
              marginBottom: 22,
              opacity: t,
              transform: `translateY(${(1 - t) * 18}px)`,
            }}
          >
            <div
              style={{
                height: 4,
                width: `${Math.max(8, bar * 100)}%`,
                background: accent || C.computed,
                marginBottom: 10,
                opacity: 0.85,
              }}
            />
            <div style={{ color: C.ink, fontSize: 52, fontWeight: 560, letterSpacing: "-0.04em" }}>
              {countDisplay(item.value, t)}
            </div>
            <div style={{ color: C.muted, fontSize: 24, marginTop: 4 }}>{item.label}</div>
            {i < items.length - 1 ? <div style={{ color: C.faint, marginTop: 10, fontSize: 22 }}>↓</div> : null}
          </div>
        );
      })}
    </div>
  );
}

function parseMagnitude(value: string): number {
  const compact = value.replace(/,/g, "");
  const match = compact.match(/^(-?[\d.]+)([KMkm]?)$/);
  if (!match) return 1;
  const n = Number(match[1]);
  const suffix = (match[2] || "").toUpperCase();
  if (suffix === "K") return n * 1_000;
  if (suffix === "M") return n * 1_000_000;
  return n;
}

export function Grid({
  items,
  from = 0,
}: {
  items: { label: string; value: string }[];
  from?: number;
}) {
  const frame = useCurrentFrame();
  return (
    <div
      style={{
        position: "absolute",
        left: 88,
        right: 88,
        top: 236,
        display: "grid",
        gridTemplateColumns: "1fr 1fr",
        gap: 18,
        fontFamily: C.font,
      }}
    >
      {items.map((item, i) => {
        const start = from + i * 4;
        const t = interpolate(frame, [start, start + 8], [0, 1], enter);
        return (
          <div
            key={item.label}
            style={{
              background: C.plate,
              padding: "22px 24px",
              border: `1px solid ${C.line}`,
              opacity: t,
              transform: `translateY(${(1 - t) * 16}px) scale(${0.94 + t * 0.06})`,
            }}
          >
            <div style={{ color: C.ink, fontSize: 40, fontWeight: 560 }}>{countDisplay(item.value, t)}</div>
            <div style={{ color: C.muted, fontSize: 20, marginTop: 6 }}>{item.label}</div>
          </div>
        );
      })}
    </div>
  );
}

export function Thesis({ text }: { text: string }) {
  const frame = useCurrentFrame();
  const t = interpolate(frame, [0, 16], [0, 1], enter);
  return (
    <div
      style={{
        position: "absolute",
        left: 88,
        right: 88,
        top: 340,
        color: C.ink,
        fontSize: 42,
        fontWeight: 560,
        letterSpacing: "-0.03em",
        lineHeight: 1.2,
        whiteSpace: "pre-line",
        fontFamily: C.font,
        opacity: t,
        filter: `blur(${(1 - t) * 7}px)`,
        transform: `translateY(${(1 - t) * 16}px)`,
      }}
    >
      {text}
    </div>
  );
}

export function Pulse({ children, when }: { children: ReactNode; when: number }) {
  const frame = useCurrentFrame();
  const punch = interpolate(frame, [when, when + 8, when + 20], [1, 1.06, 1], clampEase);
  return <AbsoluteFill style={{ transform: `scale(${punch})`, transformOrigin: "50% 45%" }}>{children}</AbsoluteFill>;
}
