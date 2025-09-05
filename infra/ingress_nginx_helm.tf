resource "helm_release" "nginx_ingress" {
  name             = "ingress-nginx"
  namespace        = "int-ingress"
  repository       = "https://kubernetes.github.io/ingress-nginx"
  chart            = "ingress-nginx"
  create_namespace = true

  values = [yamlencode({
    controller = {
      replicaCount = 2
      service = { type = "LoadBalancer" }
    }
  })]

  depends_on = [google_container_cluster.gke]
}
