# PRECREATE QBITTORRENT.CONFIG WITH DESIRED USERNAME/PASSWORD
log "Pre-setting qBittorrent Web UI username and password..."

cat > /mnt/media/configs/qbittorrent/qBittorrent.conf <<EOF
[LegalNotice]
Accepted=true

[Preferences]
WebUI\\Username=admin
WebUI\\Password_PBKDF2=@ByteArray(ARQ77eY1NUZaQsuDHbIMCA==:0WMRkYTUWVT9wVvdDtHAjU9b3b7uB8NR1Gur2hmQCvCDpm39Q+PsJRJPaCU51dEiz+dTzh8qbPsL8WkFljQYFQ==)
WebUI\\LocalHostAuth=false
EOF

chown 1000:1000 /mnt/media/configs/qbittorrent/qBittorrent.conf
