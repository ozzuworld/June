terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.54" }
  }
}

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = var.name
  cidr = var.cidr

  azs             = [for i in range(2) : "${var.region}a" if i == 0 else "${var.region}b"]
  public_subnets  = ["10.42.0.0/24","10.42.1.0/24"]

  enable_dns_hostnames = true
  enable_dns_support   = true
}

output "network_id" { value = module.vpc.vpc_id }
output "subnet_id"  { value = module.vpc.public_subnets[0] }
