# in both cloudbuild.infra-plan.yaml and cloudbuild.infra-apply.yaml
- name: hashicorp/terraform:1.8
  id: Terraform Init
  dir: ${_TF_DIR}
  entrypoint: bash
  args:
    - -lc
    - |
      terraform fmt -recursive
      terraform init -reconfigure -backend-config=backend.hcl
