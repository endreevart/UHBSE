export type Caption = { from: number; to: number; text: string };
export type Stat = { label: string; value: string; tone?: string };
export type ModelCard = { label: string; status: string; mae?: string | number };
export type MetricCard = { label: string; value: string };

export type Episode = {
  id: string;
  slug: string;
  filename: string;
  title: string;
  duration_frames: number;
  capability_status: string;
  cover_headline: string;
  series_title: string;
  disclaimer: string;
  disclosure_label: string;
  hook: string[];
  thesis: string;
  captions: Caption[];
  funnel?: Stat[];
  stats?: Stat[];
  flow?: Stat[];
  rejects?: Stat[];
  pipeline?: string[];
  counts?: Stat[];
  extras?: Stat[];
  layers?: string[];
  composite_label?: string;
  snapshot_label?: string;
  checkpoint_label?: string;
  checkpoint_hash?: string;
  branches?: string[];
  event_label?: string;
  event_week?: string;
  divergence_week?: string;
  changed_variables?: string;
  hashes?: Record<string, string>;
  isolation?: string[];
  rollback_label?: string;
  tests?: string[];
  statuses?: Stat[];
  status_badge?: string;
  method?: string[];
  models?: ModelCard[];
  metrics?: MetricCard[];
  guards?: string[];
  conclusion?: string;
};

export type SeriesFixture = {
  schema: string;
  series_title: string;
  fps: number;
  width: number;
  height: number;
  no_database_connection: boolean;
  synthetic_composite_only: boolean;
  episodes: Episode[];
};

export const SERIES_COLORS = {
  bg: "#070809",
  ink: "#f4f1ea",
  muted: "rgba(244,241,234,0.58)",
  faint: "rgba(244,241,234,0.34)",
  observed: "#c8c4bc",
  computed: "#4f8cff",
  synthetic: "#9b7dff",
  uncertainty: "rgba(120,180,255,0.35)",
  reject: "#d4a017",
  pass: "#3d9a6a",
  line: "rgba(255,255,255,0.12)",
  plate: "rgba(16,18,22,0.92)",
  font: '-apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, sans-serif',
  mono: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
} as const;

const STUB: Episode = {
  id: "Roadmap01",
  slug: "01-longitudinal-data",
  filename: "stub.mp4",
  title: "stub",
  duration_frames: 270,
  capability_status: "WORKING_NOW",
  cover_headline: "",
  series_title: "UHBSE — Building a Human Biology Simulation Engine",
  disclaimer: "Aggregated counts from one connected pilot source. No patient record is displayed.",
  disclosure_label: "Aggregates only · no patient record",
  hook: ["STUB"],
  thesis: "",
  captions: [],
};

export function episodeOf(fixture: SeriesFixture, id: string): Episode {
  return fixture.episodes.find((item) => item.id === id) || { ...STUB, id };
}

export const DEFAULT_FIXTURE: SeriesFixture = {
  schema: "uhbse.public.roadmap.fixture.v1",
  series_title: "UHBSE — Building a Human Biology Simulation Engine",
  fps: 30,
  width: 1080,
  height: 1920,
  no_database_connection: true,
  synthetic_composite_only: true,
  episodes: [],
};
