# DayMend Angular frontend

Angular 20 recovery-status UI for the DayMend childcare disruption demo.

## Run locally

```bash
npm install
npm start
```

The development configuration calls `http://localhost:8000`. Production builds use a same-origin
API base URL; deployment may replace `src/environments/environment.ts` as needed.

Run verification with:

```bash
npm test -- --watch=false --browsers=ChromeHeadless
npm run build
```

The main experience is deliberately not chat. It renders backend recovery status, meaningful
timeline events, coverage plans, Plan A impact and preservation, approval, execution results, and
deterministically verified completion.
