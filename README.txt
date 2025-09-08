june-idp Option B Patch (Cloud Run + Secret Manager, no secrets in TF state)

Files in this zip:
- services/june-idp/Dockerfile
- infra/modules/cloud_run_service/variables.tf
- infra/modules/cloud_run_service/main.tf
- infra/modules/cloud_run_service/outputs.tf
- infra/envs/quarterly/secrets.tf
- infra/envs/quarterly/june-idp.tf   (adds the module block + output without touching your existing main.tf)
- .github/workflows/deploy-idp.yml   (optional CI; adapt or remove)

Apply order:
  1) Replace/add files in your repo using these paths.
  2) terraform -chdir=infra/envs/quarterly init -upgrade
  3) terraform -chdir=infra/envs/quarterly apply        -var "image_idp=us-<region>.pkg.dev/<project>/<registry>/june-idp:<tag>"        -var "KC_DB_URL=jdbc:postgresql://<host>:5432/<db>?sslmode=require"        -var "KC_DB_USERNAME=<role>"        -var "KC_BASE_URL=https://june-idp-<hash>-<region>.a.run.app"
     (If you don't know KC_BASE_URL yet, deploy once with a placeholder, capture the output idp_url, set KC_BASE_URL to that value, then apply again.)

Notes:
  - This is Option B: Secret Manager stores only secret *versions* (created by CI), not values in TF.
  - Cloud Run pulls KC_DB_PASSWORD at runtime via env_secrets mapping.
  - Keep your persistence in Neon/Upstash/R2/Qdrant; GCP is compute-only.
