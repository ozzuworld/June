# Base DNS (→ Keycloak at https://auth.<domain>)
domain = "allsafe.world"

# Region/zone
region = "us-central1"
zone   = "us-central1-a"

# Keycloak admin (first login)
kc_admin_password = "Pokemon123!"

# Postgres credentials (VM)
kc_db_user     = "keycloak"
kc_db_password = "Pokemon123!"
kc_db_name     = "keycloak"

# Optional custom VPC name/cidr if you want different than defaults:
# vpc_name    = "app-vpc"
# subnet_cidr = "10.10.0.0/24"
# (Optional) tweak min/max if desired
kc_min_instances = 1
kc_max_instances = 5