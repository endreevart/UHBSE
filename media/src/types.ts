export type MediaSummary = {
  schema: string;
  slice_version: string;
  status: string;
  sample_class: string;
  clinical_validation: string;
  production_readiness: string;
  scope: {
    cohort_loaded_subjects: number;
    timelines_built_subjects: number;
    snapshots_built_subjects: number;
    simulated_subjects: number;
  };
  row_counts: Record<string, number>;
  row_counts_unchanged: boolean;
  provenance: {
    total_records_evaluated: number;
    valid_records: number;
    invalid_records: number;
    full_coverage: boolean;
  };
  timeline: {
    subjects_summarised: number;
    total_events: number;
    ordering: string[];
  };
  snapshot: {
    subjects_summarised: number;
    imputation_policy: string;
    demographics_count: number;
    lab_count: number;
    imputed_count: number;
    conflict_count: number;
    excluded_future_count: number;
  };
  branches: {
    count: number;
    dose_change_differs: boolean;
    first_divergence_week: number | null;
    labels: string[];
  };
  idempotent: boolean;
  disclaimer: string;
};

export const DEFAULT_SUMMARY: MediaSummary = {
  schema: "uhbse.media.summary.v1",
  slice_version: "0.1.2.1",
  status: "TECHNICAL_VERTICAL_SLICE_PASS",
  sample_class: "TECHNICAL_COVERAGE_BIASED_SAMPLE",
  clinical_validation: "NOT_STARTED",
  production_readiness: "NOT_CLAIMED",
  scope: {
    cohort_loaded_subjects: 100,
    timelines_built_subjects: 10,
    snapshots_built_subjects: 10,
    simulated_subjects: 1,
  },
  row_counts: {
    source_system: 1,
    source_record: 12544,
    subject: 100,
    subject_characteristic: 200,
    encounter: 2153,
    observation: 4000,
    observation_component: 5333,
  },
  row_counts_unchanged: true,
  provenance: {
    total_records_evaluated: 24331,
    valid_records: 24331,
    invalid_records: 0,
    full_coverage: true,
  },
  timeline: {
    subjects_summarised: 10,
    total_events: 598,
    ordering: ["clinical_time", "recorded_time", "source_order"],
  },
  snapshot: {
    subjects_summarised: 10,
    imputation_policy: "no_silent_imputation",
    demographics_count: 20,
    lab_count: 352,
    imputed_count: 0,
    conflict_count: 2,
    excluded_future_count: 160,
  },
  branches: {
    count: 3,
    dose_change_differs: true,
    first_divergence_week: 3,
    labels: ["control", "intervention", "dose change"],
  },
  idempotent: true,
  disclaimer:
    "Technical vertical slice. Not a clinical model. Clinical validation not started. Production readiness not claimed.",
};
