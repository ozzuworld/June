# June Ephemeral Cloud Run Migration (Stateless on GCP, Persistence Off-GCP)

This folder contains a minimal, version-pinned IaC + CI/CD scaffold to deploy the **June** services onto a **fresh GCP project** each cycle, while relying on **external persistent services** (Keycloak, Neon/Postgres, Cloudflare).

## Components
- Terraform **org** stack: creates a brand-new GCP project with required APIs.
- Terraform **monthly** stack: deploys `june-orchestrator`, `june-stt`, `june-tts` as **Cloud Run** services.
- GitHub Actions workflow **monthly-rollover**: project creation → deploy → (optional) old project deletion.
- Keycloak provision script: creates/rotates client and prints secrets for injection into CI.

## Inputs (CI Secrets / Vars)
- GCP: `GCP_WIF_PROVIDER`, `ORG_PROJECT_FACTORY_SA`, `ORG_DEPLOYER_SA`, `ORG_DELETER_SA`, `GCP_ORG_ID`, `GCP_BILLING_ACCOUNT`, `GCP_SEED_PROJECT`, `TFC_ORG`, `GCP_REGION`
- Images (digests): `ORCHESTRATOR_IMAGE_DIGEST`, `STT_IMAGE_DIGEST`, `TTS_IMAGE_DIGEST`
- Keycloak: `KC_BASE_URL`, `KC_CLIENT_ID`, `KC_CLIENT_SECRET`, `KC_REALM`
- Database: `NEON_DB_URL`
- Gemini: `GEMINI_API_KEY`

## How to use
1. Configure **Terraform Cloud workspaces** (`june-org`, `june-monthly`) and set the backend blocks via `terraform init` in CI.
2. Set GitHub secrets & variables listed above.
3. Push this folder to your repo; enable the `monthly-rollover` workflow.
4. Optionally wire Cloudflare DNS to the Cloud Run URLs printed by `terraform output` or terminate TLS at Cloudflare and proxy to Cloud Run.

> NOTE: If you want GKE Autopilot instead of Cloud Run, swap the `cloud_run_service` module with a small GKE module and Helm charts. This scaffold focuses on Cloud Run to stay inside free tiers.
