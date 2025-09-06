output "zone_id"     { value = google_dns_managed_zone.zone.id }
output "nameservers" { value = google_dns_managed_zone.zone.name_servers }
