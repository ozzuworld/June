# Generated K8s manifests (tailored to your repo)
Location: /mnt/data/k8s_generated/june-services

Update these placeholders before applying:
- Replace YOUR_PROJECT_ID with your GCP project id
- Confirm REGION (currently us-central1), REPO (currently 'june')
- Verify that service names match the images you build/push to Artifact Registry

Apply order:
kubectl apply -f /mnt/data/k8s_generated/june-services/namespace.yaml
kubectl apply -f /mnt/data/k8s_generated/june-services/*.yaml

DNS:
Create A records in Cloudflare for each <service>.allsafe.world pointing to the global static IP named 'allsafe-gclb-ip'.
