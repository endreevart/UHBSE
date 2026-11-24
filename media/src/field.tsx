import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";

/** Slow caustic light on true black — product-film, not a lab grid. */
export function Field() {
  const frame = useCurrentFrame();
  const a = Math.sin(frame / 90);
  const b = Math.cos(frame / 130);
  const c = Math.sin(frame / 70 + 1.2);
  return (
    <AbsoluteFill style={{ backgroundColor: "#000", overflow: "hidden" }}>
      <div
        style={{
          position: "absolute",
          width: 980,
          height: 720,
          left: -80 + a * 50,
          top: -120 + b * 40,
          background:
            "radial-gradient(ellipse at 40% 30%, rgba(50,110,220,0.42) 0%, rgba(10,20,50,0.0) 62%)",
          filter: "blur(28px)",
        }}
      />
      <div
        style={{
          position: "absolute",
          width: 640,
          height: 900,
          right: -120 + c * 30,
          bottom: -200,
          background:
            "radial-gradient(ellipse at 60% 40%, rgba(30,70,180,0.28) 0%, transparent 70%)",
          filter: "blur(36px)",
        }}
      />
      <div
        style={{
          position: "absolute",
          left: 0,
          top: "8%",
          width: 18,
          height: "55%",
          background: "linear-gradient(180deg, transparent, rgba(90,160,255,0.75), transparent)",
          filter: "blur(6px)",
          opacity: 0.55 + a * 0.12,
          borderRadius: 20,
          transform: `translateX(${24 + b * 8}px) rotate(${-8 + a * 3}deg)`,
        }}
      />
      <div
        style={{
          position: "absolute",
          inset: 0,
          background:
            "radial-gradient(ellipse at 50% 60%, transparent 40%, rgba(0,0,0,0.55) 100%)",
        }}
      />
    </AbsoluteFill>
  );
}
