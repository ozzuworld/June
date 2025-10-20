package main

import (
	"context"
	"flag"
	"fmt"
	"net/http"
	"os"
	"os/signal"
	"syscall"

	"github.com/ozzuworld/June/tools/virtual-kubelet-vast/pkg/provider/vast"
	logutil "github.com/virtual-kubelet/virtual-kubelet/log"
	"github.com/virtual-kubelet/virtual-kubelet/node"
	"github.com/virtual-kubelet/virtual-kubelet/node/api"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
	"k8s.io/klog/v2"
)

func main() {
	klog.InitFlags(nil)
	flag.Parse()

	ctx := context.Background()
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()

	// Handle shutdown gracefully
	c := make(chan os.Signal, 1)
	signal.Notify(c, os.Interrupt, syscall.SIGTERM)
	go func() {
		<-c
		logutil.G(ctx).Info("Shutting down Virtual Kubelet Vast.ai provider")
		cancel()
	}()

	// Config
	nodeName := getEnvOrDefault("NODENAME", "vast-gpu-node-na-1")
	apiKey := os.Getenv("VAST_API_KEY")
	if apiKey == "" {
		logutil.G(ctx).Fatal("VAST_API_KEY environment variable is required")
	}

	// K8s client
	config, err := rest.InClusterConfig()
	if err != nil {
		logutil.G(ctx).WithError(err).Fatal("Failed to create Kubernetes config")
	}
	clientset, err := kubernetes.NewForConfig(config)
	if err != nil {
		logutil.G(ctx).WithError(err).Fatal("Failed to create Kubernetes client")
	}

	// Provider
	provider, err := vast.NewVastProvider(ctx, apiKey, nodeName)
	if err != nil {
		logutil.G(ctx).WithError(err).Fatal("Failed to initialize Vast.ai provider")
	}

	// Build kube Node object for VK v1.11
	kubeNode := &corev1.Node{
		ObjectMeta: metav1.ObjectMeta{
			Name: nodeName,
			Labels: map[string]string{
				"provider":                      "vast.ai",
				"gpu.nvidia.com/class":         "RTX3060",
				"node.kubernetes.io/instance-type": "vast.gpu",
				"region":                       "north-america",
				"kubernetes.io/arch":           "amd64",
				"kubernetes.io/os":             "linux",
			},
		},
		Spec: corev1.NodeSpec{
			Taints: []corev1.Taint{
				{Key: "vast.ai/gpu", Value: "true", Effect: corev1.TaintEffectNoSchedule},
				{Key: "virtual-kubelet.io/provider", Value: "vast", Effect: corev1.TaintEffectNoSchedule},
			},
		},
	}

	nodesClient := clientset.CoreV1().Nodes()
	nodeController, err := node.NewNodeController(provider, kubeNode, nodesClient)
	if err != nil {
		logutil.G(ctx).WithError(err).Fatal("Failed to create node controller")
	}

	// HTTP server for VK routes
	mux := http.NewServeMux()
	api.AttachPodRoutes(provider, mux)
	api.AttachMetricsRoutes(ctx, nodeController, mux, "")

	go func() {
		srv := &http.Server{Addr: ":10255", Handler: mux}
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			logutil.G(ctx).WithError(err).Error("HTTP server error")
		}
	}()

	logutil.G(ctx).Info(fmt.Sprintf("Starting Virtual Kubelet Vast.ai provider for node: %s", nodeName))

	// Run node controller
	go func() {
		if err := nodeController.Run(ctx); err != nil {
			logutil.G(ctx).WithError(err).Error("NodeController exited with error")
		}
	}()

	select {
	case <-nodeController.Ready():
		logutil.G(ctx).Info("NodeController ready")
	case <-nodeController.Done():
		if err := nodeController.Err(); err != nil {
			logutil.G(ctx).WithError(err).Fatal("NodeController failed")
		}
		logutil.G(ctx).Info("NodeController stopped")
		return
	}

	<-ctx.Done()
	logutil.G(ctx).Info("Virtual Kubelet Vast.ai provider stopped")
}

func getEnvOrDefault(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}
