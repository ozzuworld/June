# June — Cloud-agnostic Terraform Skeleton

This folder provides a provider-agnostic layout so you can switch between GCP/AWS (and later Azure)
with minimal code changes. Your **app** should deploy via GitOps (Argo/Flux) or Helm, while Terraform
handles platform primitives (network, cluster, registry, DNS, object storage, KMS/Secrets).

## Structure

```
infra/
  modules/                 # cloud-agnostic interfaces (variables/outputs only)
  providers/
    gcp/                   # concrete GCP implementations
    aws/                   # concrete AWS implementations (partial example)
  envs/
    gcp/                   # backend + providers + wiring for GCP
    aws/                   # backend + providers + wiring for AWS
```

## Quick start (GCP)

```bash
cd infra/envs/gcp
terraform init
terraform apply -auto-approve
$(terraform output -raw kube_client_cmd)  # get kubeconfig
```

## Quick start (AWS)

```bash
cd infra/envs/aws
terraform init
terraform apply -auto-approve
$(terraform output -raw kube_client_cmd)  # get kubeconfig
```

> Fill in `terraform.tfvars` in each env with your project/account IDs, regions, and desired node pools.

---

## Source archive preview (first ~40 files)

```
June/.gitignore
June/cloudbuild.yaml
June/.cloudbuild/cloudbuild.infra-apply.yaml
June/.cloudbuild/cloudbuild.infra-plan.yaml
June/.git/COMMIT_EDITMSG
June/.git/config
June/.git/description
June/.git/FETCH_HEAD
June/.git/HEAD
June/.git/index
June/.git/ORIG_HEAD
June/.git/hooks/applypatch-msg.sample
June/.git/hooks/commit-msg.sample
June/.git/hooks/fsmonitor-watchman.sample
June/.git/hooks/post-update.sample
June/.git/hooks/pre-applypatch.sample
June/.git/hooks/pre-commit.sample
June/.git/hooks/pre-merge-commit.sample
June/.git/hooks/pre-push.sample
June/.git/hooks/pre-rebase.sample
June/.git/hooks/pre-receive.sample
June/.git/hooks/prepare-commit-msg.sample
June/.git/hooks/push-to-checkout.sample
June/.git/hooks/sendemail-validate.sample
June/.git/hooks/update.sample
June/.git/info/exclude
June/.git/logs/HEAD
June/.git/logs/refs/heads/master
June/.git/logs/refs/heads/fix/june-build-startup
June/.git/logs/refs/heads/recover/dd33870
June/.git/logs/refs/remotes/origin/HEAD
June/.git/logs/refs/remotes/origin/master
June/.git/logs/refs/remotes/origin/recover/dd33870
June/.git/objects/00/4b05bacc560691fcb4e29811094c51ec4c5f61
June/.git/objects/00/a4a6ddf96d555de2c04859628321b37bd64fdb
June/.git/objects/00/d4e8fe7676bdf1b957c3568dc61050c7279fbd
June/.git/objects/02/0715189fc5ef6551a249471109236bb0252288
June/.git/objects/02/2e1a5fd0a74b8d13b0dc9691689ed365117656
June/.git/objects/03/376025fb5c3f0e6d079b989c982f8cc491a8af
June/.git/objects/06/0546b67c2ffb048e391b95f1529b56807ff1c5
```
