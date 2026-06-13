# MeetPilot Dashboard — React + Vite

## Project structure

```
meetpilot-react/
├── index.html
├── vite.config.js
├── package.json
├── .env.example
└── src/
    ├── main.jsx          ← entry point
    ├── App.jsx           ← router root
    ├── index.css         ← global CSS variables
    ├── utils/
    │   ├── api.js        ← all API calls (BASE from VITE_API_URL)
    │   └── format.js     ← date/duration/timestamp formatters
    ├── hooks/
    │   ├── useHealth.js  ← polls /health every 15s
    │   └── usePoll.js    ← generic auto-refresh hook
    ├── components/
    │   ├── UI.jsx        ← StateBadge, Button, Card, Loading, Input, etc.
    │   └── Sidebar.jsx   ← nav with active state + health dot
    └── pages/
        ├── NewMeeting.jsx    ← create form
        ├── Live.jsx          ← live sessions + upcoming
        ├── Meetings.jsx      ← list + search
        └── MeetingDetail.jsx ← detail + summary + transcript tabs
```

## Setup

```bash
npm install
```

Copy `.env.example` → `.env` and set your backend URL:

```
VITE_API_URL=http://localhost:8000
```

## Run

```bash
npm run dev          # dev server at http://localhost:3000
npm run build        # production build → dist/
npm run preview      # preview production build
```

## Deploy (serve built files with Node)

```bash
npm run build
npx serve dist       # or point nginx/caddy at the dist/ folder
```

## Serve from FastAPI backend

```python
from fastapi.staticfiles import StaticFiles
app.mount("/dashboard", StaticFiles(directory="dist", html=True), name="dashboard")
```
Set `VITE_API_URL=/` (relative) before building so API calls go to the same origin.
