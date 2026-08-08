# UHBSE landing

Multilingual marketing / research landing page for UHBSE.

This directory is **independent of the data-foundation pipeline**. It contains no
clinical data, no database access and no stage artifacts. Every number shown in
the engine demo is synthetic and generated in the browser.

## Stack

- Vite 7 + React 19 + TypeScript (strict)
- No UI framework, no chart library — all visuals are hand-built SVG
- Fonts loaded from Google Fonts (Newsreader, IBM Plex Sans/Mono, Noto Naskh
  Arabic, Noto Serif SC)

## Commands

```bash
npm install
npm run dev      # http://localhost:5173
npm run build    # type-check + production bundle into dist/
npm run preview  # serve the production bundle
```

## Languages

Seven locales live in `src/i18n/locales/`: `en`, `ru`, `ar`, `zh`, `es`, `fr`, `de`.

`en.ts` is the source of truth — its shape is exported as the `Dict` type, so every
other locale is type-checked against it and a missing key fails the build.

Locale selection order: `localStorage` → `?lang=` query parameter → browser
language → `en`. Arabic switches the document to `dir="rtl"`; the whole layout is
written with logical properties, so no separate RTL stylesheet is needed. Charts
stay LTR because a time axis does not mirror.

To add a language: create `src/i18n/locales/<code>.ts` typed as `Dict`, then add
an entry to `LOCALES` in `src/i18n/index.tsx`.

## The engine demo

`src/engine/model.ts` holds a small deterministic simulation used by the
interactive section:

- six indicators with a baseline, a reference interval and a measurement noise
  amplitude;
- four interventions, each with a reference dose, a response time constant and
  per-indicator effect sizes;
- exponential build-up from an intervention's start week and exponential
  wash-out after its end week;
- uncertainty that widens with the horizon and with the amount of change applied.

A scenario is a list of dose segments. Creating a branch clones the active
scenario at the current week; changing a dose on a branch closes the previous
segment and opens a new one at the branch week, so branches stay identical before
the branch point and diverge after it.

Measurement noise is seeded from the indicator, not the scenario — it belongs to
the person, so branches overlap exactly until they actually differ.

## Content structure

`src/App.tsx` composes the sections in order: hero, problem, what UHBSE does,
engine demo, layer separation, impact, why now, principles (light lab section),
status, partnership, manifesto.
