export const status = {
  kicker: 'Roadmap',
  title: 'Where UHBSE is today — and what comes next.',
  lead:
    'What is complete, in progress and planned next. UHBSE is a research technology — not for clinical use and not a substitute for clinical judgment.',
  sections: [
    {
      id: 'done',
      label: 'What is already done',
      items: [
        {
          id: 'architecture',
          title: 'UHBSE architecture defined',
          body:
            'The core engine model is defined: represent subject state over time, apply interventions and compute possible biological trajectories with uncertainty.',
          status: 'Status: architecture complete.',
        },
        {
          id: 'clinical-foundation',
          title: 'Source data foundation prepared',
          body:
            'The project has established a foundation for working with longitudinal medical data. Source datasets have been structurally audited: core clinical cases and subject observations are defined.',
          status: 'Status: audit complete.',
        },
        {
          id: 'source-alignment',
          title: 'Independent data sources aligned',
          body:
            'A method to compare heterogeneous datasets without premature record linking and without losing provenance.',
          status: 'Status: complete.',
        },
        {
          id: 'canonical-model',
          title: 'Unified biological data model designed',
          body: 'A canonical model now represents:',
          points: [
            'the subject and baseline state',
            'clinical events',
            'laboratory observations',
            'interventions',
            'temporal change',
            'the source of every measure',
            'synthetic scenarios',
            'predicted states',
          ],
          status: 'Status: design complete; base storage layer implemented.',
        },
        {
          id: 'evidence-layers',
          title: 'Facts, computation and prediction separated',
          body:
            'Clinical observations, derived parameters, synthetic scenarios and model predictions are distinct data types — so every result can be traced to its origin and confidence.',
          status: 'Status: implemented in architecture and data contracts.',
        },
        {
          id: 'scenario-system',
          title: 'Scenario system designed',
          body:
            'Branching logic is defined: dose change, added intervention, return to a control point and continuation along another trajectory.',
          status: 'Status: design complete; compute engine ahead.',
        },
        {
          id: 'infrastructure',
          title: 'Isolated research infrastructure deployed',
          body:
            'Base storage for standardised data is live. Access control, record provenance, reproducible change history and secure secret management are in place.',
          status:
            'Status: base infrastructure operational; clinical rows are not yet loaded into the new layer.',
        },
      ],
    },
    {
      id: 'active',
      label: 'What we are doing now',
      items: [
        {
          id: 'live-pilot',
          title: 'Preparing the first controlled live pilot',
          body:
            'A safe route from the first clinical source into the standardised research model is being finalised.',
          points: [
            'Goal: a reproducible set of longitudinal states without modifying source medical systems.',
          ],
        },
        {
          id: 'biological-state',
          title: 'Formalising subject biological state',
          body: 'Defining which measures form the starting state of a virtual subject:',
          points: [
            'anthropometrics',
            'laboratory measures',
            'diagnoses and history',
            'prescriptions',
            'nutrition',
            'activity',
            'temporal context',
            'completeness and quality of source data',
          ],
        },
        {
          id: 'math-core',
          title: 'Designing the mathematical core',
          body: 'A hybrid methodology combining:',
          points: [
            'physiology-informed modelling',
            'systems biology',
            'QSP and PK/PD approaches',
            'biochemical dependencies',
            'statistical models',
            'machine learning',
            'uncertainty estimation',
          ],
          status:
            'LLMs are an interface and orchestration layer; numerical simulation rests on verifiable mathematical and statistical methods.',
        },
        {
          id: 'validation-system',
          title: 'Building the validation framework',
          body:
            'A method to compare computed trajectories with observed subsequent subject dynamics.',
          points: [
            'forecast error',
            'uncertainty calibration',
            'robustness across cohorts',
            'forecast quality over time',
            'result reproducibility',
            'reasons for deviation',
          ],
        },
      ],
    },
    {
      id: 'next',
      label: 'What comes next',
      items: [
        {
          id: 'dataset',
          title: 'First standardised clinical dataset',
          body:
            'Controlled loading of the first limited longitudinal set into the UHBSE canonical model.',
        },
        {
          id: 'state-reconstruction',
          title: 'Baseline state reconstruction',
          body:
            'A temporal biological profile of the subject at a defined starting point, assembled from real observations.',
        },
        {
          id: 'narrow-module',
          title: 'First narrow simulation module',
          body:
            'The first pilot focuses on a limited set of measures and interventions — to measure model quality before whole-organism expansion.',
        },
        {
          id: 'retrospective',
          title: 'Retrospective validation',
          body:
            'The engine receives data up to a chosen time point, forecasts forward and compares with what was actually observed.',
        },
        {
          id: 'branching',
          title: 'Scenario branching',
          body: 'Alternative strategies become comparable:',
          points: [
            'keep current management',
            'change dose',
            'change duration',
            'add an intervention',
            'change nutrition or activity',
            'model different adherence',
            'return to a control point',
          ],
        },
        {
          id: 'impact-map',
          title: 'Impact map',
          body: 'For each intervention the system will show:',
          points: [
            'which measures changed',
            'direction of change',
            'time to effect',
            'direct and indirect dependencies',
            'differences between branches',
            'uncertainty range',
            'reasons a scenario stopped',
          ],
        },
        {
          id: 'coverage',
          title: 'Broader biological coverage',
          body:
            'After the first modules are validated, the engine expands to interactions across metabolic, endocrine, cardiovascular and other physiological systems.',
        },
        {
          id: 'research-tools',
          title: 'Research tooling',
          body: 'UHBSE will support:',
          points: [
            'research hypothesis formation',
            'virtual cohort simulation',
            'sensitivity analysis',
            'potential biomarker discovery',
            'preliminary protocol assessment',
            'selection of the most informative scenarios for follow-up',
          ],
        },
        {
          id: 'external-validation',
          title: 'External validation',
          body:
            'Validation on independent data and joint studies with medical organisations, research centres and biopharma R&D.',
        },
      ],
    },
  ],
}
