# GPU Pulse

An open-source index of GPU cloud **list prices** and **availability signals**, updated hourly from public provider data.

The goal is a durable, append-only time series: what did GPUs cost, and where did capacity actually look available, over time? The public site and JSON API expose hourly snapshots derived from that dataset.

**Live site:** [https://gpupulse.xyz](https://gpupulse.xyz)

---

## Features

- **Multi-provider price collection** — hyperscalers, neoclouds, and marketplaces
- **Availability signals** where providers expose them (marketplace listings, capacity APIs)
- **Canonical GPU naming** — cross-provider comparison on normalized types (e.g. `H100-SXM-80GB`)
- **Public web index** — sortable price table, per-GPU detail pages with history charts
- **Free JSON API** — same data, rate-limited, no auth
- **Hourly rollups** — the site reads pre-computed snapshots, not raw observation tables

---

## Architecture

```
┌─────────────┐     hourly      ┌──────────────┐
│  Collectors │ ──────────────► │   SQLite     │
└─────────────┘                 │  (time series)│
                                └──────┬───────┘
┌─────────────┐     hourly              │
│   Rollups   │ ◄───────────────────────┘
└──────┬──────┘
       │
       ▼
┌─────────────┐     HTTP      ┌─────────────┐
│  FastAPI    │ ◄──────────── │   Caddy     │
│  + web UI   │               │  (proxy)    │
└─────────────┘               └─────────────┘
```

Three long-running services, orchestrated with Docker Compose:

| Service | Role |
|---------|------|
| `scheduler` | Polls providers, writes observations, runs rollup job |
| `api` | Serves HTML pages and `/api/v1/*` JSON endpoints |
| `caddy` | Reverse proxy |

---

## JSON API

| Endpoint | Description |
|----------|-------------|
| `GET /api/v1/index` | All GPU types — cheapest prices, availability indicator, provider count |
| `GET /api/v1/prices?gpu={name}` | Provider comparison and hourly price history for one GPU |
| `GET /api/v1/availability?gpu={name}` | Daily availability rollup for one GPU |
| `GET /api/v1/meta` | Latest snapshot timestamp |

See the live site's **Methodology** page for how to interpret prices and availability indicators.

---

## Project structure

```
collectors/     Provider polling (one module per source)
analysis/       Rollup computation and CLI reports
api/            FastAPI app, routes, rate limiting
web/            HTML templates and static assets
jobs/           Scheduler process and operational CLIs
db/             SQLAlchemy models and migrations
tests/          Unit tests with mocked HTTP fixtures
```

---

## Data model

Observations are **append-only** — nothing is overwritten. Two core tables:

- **Price observations** — per-provider, per-GPU, per-region list prices (USD/GPU-hour)
- **Availability observations** — capacity signals where observed; labeled `unknown` when no signal exists

Hourly rollup tables power the website. Raw observations are retained for reprocessing.

---

## License

TBD
