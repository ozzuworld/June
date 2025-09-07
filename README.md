
# June — Cloud Run CI/CD integration (tied to your repo)

Services auto-detected: june-orchestrator, june-stt, june-tts

- `.github/workflows/deploy.yml` — build/push/deploy on push, plus quarterly redeploy.
- `.github/workflows/pg-backup.yml` — Cloud Run Job for PG→R2 backup (on-demand or daily at 03:00 UTC).
- `terraform/ci/` — WIF, Artifact Registry, baseline Secret Manager.
- `scripts/seed_secrets.sh` — seed secrets from `.env.production` (not committed).
- `scripts/cloudflare_dns.sh` — help map custom domains and print DNS records.
- `jobs/pg-backup/` — job image.

**Paths:** If your repo uses a nested `June/services/`, edit `SERVICES_ROOT` in deploy.yml to `June/services`.
**Security:** rotate any keys you pasted earlier; store only in Secret Manager.
