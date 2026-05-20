# Nginx config (deployed)

`aevus.conf` is a snapshot of `/etc/nginx/sites-available/aevus` on the
`aevus-testbed` EC2 instance (i-017562fca3e3401a8, us-east-1).

## What it enforces
- HTTPS via Certbot/Let's Encrypt for `aevus.intrepidlogic.io`
- HTTP → HTTPS 301 redirect (managed by Certbot)
- Proxy to FastAPI on `127.0.0.1:8000` (the `aevus.service` systemd unit)
- WebSocket upgrade support
- **Defense-in-depth: returns 404 for `/docs`, `/redoc`, `/openapi.json`** (matches the FastAPI-side `docs_url=None` config in `src/main.py`)

## To sync changes
EC2 → repo:
```
aws ssm send-command --instance-ids i-017562fca3e3401a8 \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["sudo cat /etc/nginx/sites-available/aevus"]'
```

Repo → EC2:
```
# SSH or SSM into the box and replace, then:
sudo nginx -t && sudo systemctl reload nginx
```

Last synced: 2026-05-20
