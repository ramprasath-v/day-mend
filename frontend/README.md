# DayMend Angular frontend

Angular 20 recovery-status UI for the DayMend childcare disruption demo.

## Run locally

```bash
npm install
npm start
```

The development configuration calls `http://localhost:8000`. Production reads the API base URL at
runtime from `window.__DAYMEND_CONFIG__` in `public/config.js`. The tracked template stays empty;
deployment writes the hosted URL only into the generated bundle before upload.

Run verification with:

```bash
npm test -- --watch=false --browsers=ChromeHeadless
npm run build
```

The main experience is deliberately not chat. It renders backend recovery status, meaningful
timeline events, coverage plans, Plan A impact and preservation, approval, execution results, and
deterministically verified completion.
