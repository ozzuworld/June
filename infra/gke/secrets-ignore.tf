# Temporarily ignore secrets that already exist
# They will be managed outside of Terraform

# resource "google_secret_manager_secret" "oracle_credentials" {
#   for_each = toset([
#     "harbor-db-password",
#     "keycloak-db-password", 
#     "oracle-wallet-cwallet",
#     "oracle-wallet-ewallet",
#     "oracle-wallet-tnsnames",
#     "oracle-wallet-sqlnet"
#   ])
#   
#   secret_id = each.key
#   project   = var.project_id
# 
#   replication {
#     auto {}
#   }
#   
#   labels = {
#     purpose = "oracle-database"
#     service = "june-platform"
#   }
# }
