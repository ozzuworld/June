resource "aws_ecr_repository" "repo" {
  name = var.name
  image_scanning_configuration { scan_on_push = true }
}
output "registry_url" { value = aws_ecr_repository.repo.repository_url }
