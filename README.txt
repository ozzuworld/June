june-idp Option B Patch (CUSTOMIZED)

Project: main-buffer-469817-v7
Region:  us-central1
Assumed Artifact Registry repo: us-central1-docker.pkg.dev/main-buffer-469817-v7/june
Neon JDBC URL: jdbc:postgresql://ep-dry-art-ad9moi68-pooler.c-2.us-east-1.aws.neon.tech:5432/neondb?sslmode=require
Neon role: neondb_owner

Files:
- services/june-idp/Dockerfile
- infra/modules/cloud_run_service/variables.tf
- infra/modules/cloud_run_service/main.tf
- infra/modules/cloud_run_service/outputs.tf
- infra/envs/quarterly/secrets.tf
- infra/envs/quarterly/june-idp.tf
- .github/workflows/deploy-idp.yml

CI Secrets to set (GitHub → Settings → Secrets and variables → Actions):
- GCP_SA_KEY            (JSON for a deploy SA)
- KC_DB_PASSWORD        (Neon role password)
- KC_BASE_URL           (set AFTER first deploy to the Cloud Run URL or your custom domain)

Optional (override defaults if you prefer):
- GCP_AR_REPO, GCP_PROJECT_ID, GCP_REGION

Apply (manual TF):
  terraform -chdir=infra/envs/quarterly init -upgrade
  terraform -chdir=infra/envs/quarterly apply     -var "image_idp=us-central1-docker.pkg.dev/main-buffer-469817-v7/june/june-idp:<tag>"     -var "KC_DB_URL=jdbc:postgresql://ep-dry-art-ad9moi68-pooler.c-2.us-east-1.aws.neon.tech:5432/neondb?sslmode=require"     -var "KC_DB_USERNAME=neondb_owner"     -var "KC_BASE_URL=<cloud-run-url>"
