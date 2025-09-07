
# PowerShell-friendly bootstrap

```powershell
# Set variables in PowerShell (not bash syntax)
$PROJECT_ID = "<your-project-id>"
gcloud config set project $PROJECT_ID
$PROJECT_NUMBER = (gcloud projects describe $PROJECT_ID --format 'value(projectNumber)')

# Initialize and apply Terraform
terraform -chdir=terraform/ci init
terraform -chdir=terraform/ci apply -auto-approve `
  -var "project_id=$PROJECT_ID" `
  -var "project_number=$PROJECT_NUMBER" `
  -var "github_org=<your_github_org>" `
  -var "github_repo=<your_repo_name>"

# Show outputs (copy into GitHub Secrets/Variables)
terraform -chdir=terraform/ci output
```
