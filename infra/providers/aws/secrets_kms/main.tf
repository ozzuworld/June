resource "aws_kms_key" "key" { description = "KMS for ${var.name}" }
output "kms_id"      { value = aws_kms_key.key.key_id }
output "secrets_ref" { value = "use aws_secretsmanager_secret for app secrets" }
