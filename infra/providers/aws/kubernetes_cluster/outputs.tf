output "endpoint"        { value = module.eks.cluster_endpoint }
output "ca_cert"         { value = module.eks.cluster_certificate_authority_data }
output "kube_client_cmd" { value = "aws eks update-kubeconfig --name ${var.name} --region ${var.region}" }
