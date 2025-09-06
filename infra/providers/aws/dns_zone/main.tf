resource "aws_route53_zone" "zone" {
  name = var.domain
}
output "zone_id"     { value = aws_route53_zone.zone.zone_id }
output "nameservers" { value = aws_route53_zone.zone.name_servers }
