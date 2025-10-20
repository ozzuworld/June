package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/ozzuworld/June/tools/virtual-kubelet-vast/pkg/provider/vast"
	"github.com/virtual-kubelet/virtual-kubelet/errdefs"
	"github.com/virtual-kubelet/virtual-kubelet/log"
	"github.com/virtual-kubelet/virtual-kubelet/node"
	"github.com/virtual-kubelet/virtual-kubelet/node/api"
	nodeopts "github.com/virtual-kubelet/virtual-kubelet/node/opts"
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
		log.G(ctx).Info("Shutting down Virtual Kubelet Vast.ai provider")
		cancel()
	}()

	// Get configuration
	nodeName := getEnvOrDefault("NODENAME", "vast-gpu-node-na-1")
	apiKey := os.Getenv("VAST_API_KEY")
	if apiKey == "" {
		log.G(ctx).Fatal("VAST_API_KEY environment variable is required")
	}

	// Create Kubernetes client
	config, err := rest.InClusterConfig()
	if err != nil {
		log.G(ctx).WithError(err).Fatal("Failed to create Kubernetes config")
	}

	clientset, err := kubernetes.NewForConfig(config)
	if err != nil {
		log.G(ctx).WithError(err).Fatal("Failed to create Kubernetes client")
	}

	// Initialize Vast.ai provider
	provider, err := vast.NewVastProvider(ctx, apiKey, nodeName)
	if err != nil {
		log.G(ctx).WithError(err).Fatal("Failed to initialize Vast.ai provider")
	}

	// Node configuration
	nodeOpts := []nodeopts.NodeOpt{
		nodeopts.WithClient(clientset),
		nodeopts.WithNodeName(nodeName),
		nodeopts.WithOperatingSystem("Linux"),
		nodeopts.WithTaints([]corev1.Taint{
			{
				Key:    "vast.ai/gpu",
				Value:  "true",
				Effect: corev1.TaintEffectNoSchedule,
			},
			{
				Key:    "virtual-kubelet.io/provider",
				Value:  "vast",
				Effect: corev1.TaintEffectNoSchedule,
			},
		}),
		nodeopts.WithNodeLabels(map[string]string{
			"provider":                    "vast.ai",
			"gpu.nvidia.com/class":       "RTX3060",
			"node.kubernetes.io/instance-type": "vast.gpu",
			"region":                     "north-america",
			"kubernetes.io/arch":         "amd64",
			"kubernetes.io/os":           "linux",
		}),
	}

	// Create node runner
	nodeRunner, err := node.NewNodeController(
		provider,
		node.WithNodeSpec(corev1.NodeSpec{
			Taints: []corev1.Taint{
				{
					Key:    "vast.ai/gpu",
					Value:  "true",
					Effect: corev1.TaintEffectNoSchedule,
				},
			},
		}),
		nodeOpts...,
	)
	if err != nil {
		log.G(ctx).WithError(err).Fatal("Failed to create node controller")
	}

	// Start HTTP server for kubelet API
	go func() {
		if err := api.AttachMetricsRoutes(ctx, nodeRunner, nil, ":10255"); err != nil {
			log.G(ctx).WithError(err).Error("Failed to start metrics server")
		}
	}()

	log.G(ctx).Info(fmt.Sprintf("Starting Virtual Kubelet Vast.ai provider for node: %s", nodeName))

	// Run the node controller
	if err := nodeRunner.Run(ctx); err != nil {
		if !errdefs.IsAborted(err) {
			log.G(ctx).WithError(err).Fatal("Node runner exited with error")
		}
	}

	log.G(ctx).Info("Virtual Kubelet Vast.ai provider stopped")
}

func getEnvOrDefault(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}