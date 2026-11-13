# PRISMAgent — web interface

A Next.js application (React, TypeScript). It has no logic of its own: it shows what the Python API
(`src/sysrev/api.py`) returns and sends it the reviewer's decisions.

Start it from the project root with `sysrev web`, which launches the API and this application
together and opens them on <http://localhost:3000>. To work on the interface alone:

```bash
sysrev serve            # the API, on http://127.0.0.1:8000 (from the project root)
npm install             # once
npm run dev             # the interface, on http://localhost:3000
npm run typecheck
npm run build
```

`/api/*` is proxied to the API (`next.config.mjs`; set `SYSREV_API` to point elsewhere).

| Folder | Content |
|---|---|
| `app/` | layout, the two pages (`/` and `/runs/[id]`) and `globals.css`: design tokens and component styles |
| `components/` | `Shell` (sidebar, language switch, quota), `RunView` (header, tabs), `Pipeline` (progress strip), `Checkpoint` (the three human checkpoints), `NewReview`, `ui` (small shared pieces) |
| `components/tabs/` | one file per tab: Overview, Protocol, Screening, Studies, Report, Quality |
| `lib/api.ts` | types of the API responses and the fetch helpers |
| `lib/i18n.tsx` | English and French texts. Add a key to `en`: TypeScript then requires it in `fr` |

Only the interface is translated; what the agents write stays in English.
