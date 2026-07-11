# IntakeAI Landing

Marketing/pitch landing page for IntakeAI, built with Next.js 16 (App Router, TypeScript, plain CSS — no extra dependencies). Fully static, no backend calls, no PHI.

## Run

```bash
npm install
npm run dev      # http://localhost:3100
npm run validate # type-check + production build
```

## Structure

- `app/page.tsx` — single-page landing (hero with live-call transcript mock, problem stats, how-it-works, features, CTA).
- `app/globals.css` — all styling (dark theme, gradients).
- Static content only; stats and copy come from `PROJECT.md`.
