# GPU Index

Public index of GPU cloud list prices and availability signals, updated hourly.

## Run locally

```bash
cp .env.example .env   # add API keys as needed
docker compose up --build -d
open http://localhost:8080
```

## Services

| Service | Purpose |
|---------|---------|
| `scheduler` | Hourly data collection + snapshot rollups |
| `api` | Web UI + JSON API |
| `caddy` | Reverse proxy (port 8080 locally) |

## Useful commands

```bash
docker compose exec scheduler gpuindex-status
docker compose exec scheduler gpuindex-rollup
docker compose exec scheduler gpuindex-snapshot --gpu H100-SXM-80GB
pytest
```

## Environment variables

See `.env.example`. Never commit `.env`.

## License

TBD
