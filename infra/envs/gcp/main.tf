module "network" {
  source = "../../providers/gcp/network"
  name   = var.name
  cidr   = var.vpc_cidr
  region = var.region
}

module "kube" {
  source       = "../../providers/gcp/kubernetes_cluster"
  project_id   = var.project_id
  name         = var.name
  region       = var.region
  k8s_version  = var.k8s_version
  node_pools   = var.node_pools
  network_id   = module.network.network_id
  subnet_id    = module.network.subnet_id
}

module "registry" {
  source     = "../../providers/gcp/container_registry"
  project_id = var.project_id
  name       = var.name
  region     = var.region
}

module "dns" {
  source    = "../../providers/gcp/dns_zone"
  zone_name = var.dns_zone_name
  domain    = var.domain
  region    = var.region
}

module "bucket" {
  source = "../../providers/gcp/object_storage"
  name   = "${var.name}-artifacts"
  region = var.region
}

module "kms" {
  source = "../../providers/gcp/secrets_kms"
  name   = var.name
  region = var.region
}

output "kube_endpoint"     { value = module.kube.endpoint }
output "kube_ca_cert"      { value = module.kube.ca_cert }
output "kube_client_cmd"   { value = module.kube.kube_client_cmd }
output "registry_url"      { value = module.registry.registry_url }
output "dns_nameservers"   { value = module.dns.nameservers }
output "bucket_name"       { value = module.bucket.bucket_name }
output "kms_id"            { value = module.kms.kms_id }
