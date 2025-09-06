terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.54" }
  }
}

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = var.name
  cluster_version = var.k8s_version
  cluster_endpoint_public_access = true

  vpc_id     = var.network_id
  subnet_ids = [var.subnet_id]

  eks_managed_node_groups = {
    for p in var.node_pools :
    p.name => {
      instance_types = [p.machine]
      min_size       = p.min
      max_size       = p.max
      desired_size   = p.min
      disk_size      = p.disk_gb
      capacity_type  = p.spot ? "SPOT" : "ON_DEMAND"
    }
  }
}

output "endpoint"        { value = module.eks.cluster_endpoint }
output "ca_cert"         { value = module.eks.cluster_certificate_authority_data }
output "kube_client_cmd" { value = "aws eks update-kubeconfig --name ${var.name} --region ${var.region}" }
