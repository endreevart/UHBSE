# UHBSE media factory

Local Remotion package. Renders 9:16 stills and reels from a PII-free summary.

```bash
audit --root . media summarize
cd media && npm install
audit --root . media render          # stills + mp4
audit --root . media render --stills-only
audit --root . media verify
```

Outputs go to `private/media-out/` (gitignored). Do not pass timeline JSON, subject ids, or clinical timestamps as props.

Public roadmap series (evidence-bound, private review only):

```bash
audit --root . media series                 # bindings + Remotion + contact sheets + review ZIP
audit --root . media series --skip-render   # evidence artifacts only
```

Masters: `artifacts/public-media/uhbse-roadmap-series-v0.1/`. Status: `PRIVATE_PUBLICATION_REVIEW_REQUIRED`. Do not post.

Free License (Remotion): individuals and teams of ≤3. See https://www.remotion.dev/docs/license
