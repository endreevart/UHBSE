import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { enter, flow } from "../motion";
import { BigType, Fade, Ride, SeriesChrome, SeriesField } from "./chrome";
import { SERIES_COLORS as C, episodeOf, type ModelCard, type SeriesFixture } from "./types";

const FALLBACK_GUARDS = [
  "EXPLORATORY TEST",
  "TEST: 2 SUBJECTS / 2 PAIRS",
  "NO INCREMENTAL SIGNAL CLAIMED",
  "CLINICAL VALIDATION: NOT STARTED",
];

function formatMae(mae: string | number | undefined): string | null {
  if (mae === undefined || mae === null || mae === "") return null;
  if (typeof mae === "number") return Number(mae.toFixed(3)).toString();
  return String(mae);
}

function modelMaeTone(models: ModelCard[], model: ModelCard): string {
  const values = models
    .map((item) => (typeof item.mae === "number" ? item.mae : Number(item.mae)))
    .filter((value) => Number.isFinite(value));
  const own = typeof model.mae === "number" ? model.mae : Number(model.mae);
  if (!Number.isFinite(own) || values.length < 2) return C.ink;
  const best = Math.min(...values);
  return own === best ? C.computed : C.ink;
}

export const Roadmap06: React.FC<SeriesFixture> = (fixture) => {
  const episode = episodeOf(fixture, "Roadmap06");
  const models = episode.models || [];
  const guards = episode.guards?.length ? episode.guards : FALLBACK_GUARDS;
  const metrics = (episode.metrics || []).filter((metric) => {
    const label = metric.label.toLowerCase();
    const value = String(metric.value).toUpperCase();
    if (label.includes("uncertainty") && value.includes("PASS")) return false;
    return true;
  });

  return (
    <AbsoluteFill>
      <SeriesField />
      <Ride>
        {episode.status_badge ? (
          <div
            style={{
              position: "absolute",
              top: 168,
              left: 88,
              right: 88,
              color: C.reject,
              letterSpacing: "0.14em",
              fontSize: 20,
              fontWeight: 560,
              fontFamily: C.font,
              lineHeight: 1.3,
            }}
          >
            {episode.status_badge}
          </div>
        ) : null}

        <Fade from={0} until={56}>
          <BigType lines={episode.hook} top={250} />
        </Fade>
        <Fade from={52} until={140}>
          <Results models={models} metrics={metrics} />
        </Fade>
        <Fade from={136} until={208}>
          <Guards items={guards} />
        </Fade>
        <Fade from={204} until={270}>
          <Closer thesis={episode.thesis} conclusion={episode.conclusion} />
        </Fade>
      </Ride>
      <SeriesChrome episode={episode} index={6} />
    </AbsoluteFill>
  );
};

function Results({
  models,
  metrics,
}: {
  models: ModelCard[];
  metrics: { label: string; value: string }[];
}) {
  const frame = useCurrentFrame();
  return (
    <div style={{ position: "absolute", left: 88, right: 88, top: 220, fontFamily: C.font }}>
      <div style={{ color: C.muted, fontSize: 22, letterSpacing: "0.12em", marginBottom: 18 }}>SUBJECT-MACRO MAE</div>
      {models.map((model, i) => {
        const mae = formatMae(model.mae);
        const t = interpolate(frame, [i * 6, i * 6 + 10], [0, 1], enter);
        return (
          <div
            key={model.label}
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "baseline",
              gap: 24,
              marginBottom: 18,
              borderBottom: `1px solid ${C.line}`,
              paddingBottom: 12,
              opacity: t,
              transform: `translateY(${(1 - t) * 12}px)`,
            }}
          >
            <div style={{ color: C.ink, fontSize: 28, fontWeight: 520, lineHeight: 1.2, maxWidth: 620 }}>{model.label}</div>
            <div
              style={{
                color: mae ? modelMaeTone(models, model) : C.faint,
                fontSize: 36,
                fontWeight: 600,
                fontFamily: C.mono,
                letterSpacing: "-0.02em",
                whiteSpace: "nowrap",
              }}
            >
              {mae ?? "—"}
            </div>
          </div>
        );
      })}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginTop: 8 }}>
        {metrics.slice(0, 4).map((metric, i) => {
          const t = interpolate(frame, [22 + i * 5, 22 + i * 5 + 8], [0, 1], enter);
          return (
            <div
              key={metric.label}
              style={{
                border: `1px solid ${C.line}`,
                background: C.plate,
                padding: "10px 14px",
                minWidth: 150,
                opacity: t,
              }}
            >
              <div style={{ color: C.muted, fontSize: 15, letterSpacing: "0.08em" }}>{metric.label}</div>
              <div style={{ color: C.ink, fontSize: 22, marginTop: 4, fontWeight: 560 }}>{metric.value}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Guards({ items }: { items: string[] }) {
  const frame = useCurrentFrame();
  return (
    <div style={{ position: "absolute", left: 88, right: 88, top: 320, fontFamily: C.font }}>
      {items.map((guard, i) => {
        const t = interpolate(frame, [i * 6, i * 6 + 8], [0, 1], enter);
        return (
          <div
            key={guard}
            style={{
              color: C.reject,
              fontSize: 32,
              fontWeight: 600,
              letterSpacing: "0.08em",
              lineHeight: 1.3,
              marginBottom: 18,
              opacity: t,
              transform: `translateX(${(1 - t) * 22}px)`,
            }}
          >
            {guard}
          </div>
        );
      })}
    </div>
  );
}

function Closer({ thesis, conclusion }: { thesis: string; conclusion?: string }) {
  const frame = useCurrentFrame();
  const t = interpolate(frame, [0, 10], [0, 1], enter);
  return (
    <div style={{ position: "absolute", left: 88, right: 88, top: 280, fontFamily: C.font }}>
      <div
        style={{
          color: C.ink,
          fontSize: 42,
          fontWeight: 560,
          letterSpacing: "-0.03em",
          lineHeight: 1.22,
          whiteSpace: "pre-line",
          opacity: t,
          filter: `blur(${(1 - t) * 6}px)`,
        }}
      >
        {thesis}
      </div>
      {conclusion ? (
        <div
          style={{
            color: C.muted,
            fontSize: 28,
            fontWeight: 500,
            lineHeight: 1.35,
            marginTop: 28,
            whiteSpace: "pre-line",
            opacity: interpolate(frame, [8, 18], [0, 1], flow),
          }}
        >
          {conclusion}
        </div>
      ) : null}
    </div>
  );
}
