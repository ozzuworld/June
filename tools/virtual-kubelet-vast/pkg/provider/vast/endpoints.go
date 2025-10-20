package vast

import (
	"context"
	"fmt"
	"time"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
	"k8s.io/klog/v2"

	vapi "github.com/ozzuworld/June/tools/virtual-kubelet-vast/pkg/provider/vast/api"
)

// EndpointManager handles updating Kubernetes service endpoints for Vast.ai instances
type EndpointManager struct {
	clientset kubernetes.Interface
}

// NewEndpointManager creates a new endpoint manager
func NewEndpointManager() *EndpointManager {
	// Get Kubernetes client
	config, err := rest.InClusterConfig()
	if err != nil {
		klog.Error(fmt.Errorf("failed to create Kubernetes config: %w", err))
		return &EndpointManager{}
	}

	clientset, err := kubernetes.NewForConfig(config)
	if err != nil {
		klog.Error(fmt.Errorf("failed to create Kubernetes client: %w", err))
		return &EndpointManager{}
	}

	return &EndpointManager{
		clientset: clientset,
	}
}

// UpdatePodEndpoints updates the service endpoints for STT and TTS services
func (e *EndpointManager) UpdatePodEndpoints(ctx context.Context, pod *corev1.Pod, instance *vapi.Instance) error {
	if e.clientset == nil {
		return fmt.Errorf("kubernetes client not available")
	}

	log := klog.FromContext(ctx)
	log.Info(fmt.Sprintf("Updating service endpoints for pod %s (instance %d at %s)", 
		pod.Name, instance.ID, instance.PublicIP))

	// Update june-stt service endpoints (port 8001)
	sttExternalPort := instance.Ports[8001]
	if sttExternalPort == 0 {
		return fmt.Errorf("STT port 8001 not found in instance port mapping")
	}

	if err := e.updateServiceEndpoint(ctx, "default", "june-stt", instance.PublicIP, sttExternalPort); err != nil {
		return fmt.Errorf("failed to update june-stt endpoints: %w", err)
	}

	// Update june-tts service endpoints (port 8000)
	ttsExternalPort := instance.Ports[8000]
	if ttsExternalPort == 0 {
		return fmt.Errorf("TTS port 8000 not found in instance port mapping")
	}

	if err := e.updateServiceEndpoint(ctx, "default", "june-tts", instance.PublicIP, ttsExternalPort); err != nil {
		return fmt.Errorf("failed to update june-tts endpoints: %w", err)
	}

	log.Info(fmt.Sprintf("Service endpoints updated: june-stt → %s:%d, june-tts → %s:%d",
		instance.PublicIP, sttExternalPort, instance.PublicIP, ttsExternalPort))

	return nil
}

// updateServiceEndpoint updates a specific service endpoint
func (e *EndpointManager) updateServiceEndpoint(ctx context.Context, namespace, serviceName, ip string, port int) error {
	// Create or update endpoints
	endpoints := &corev1.Endpoints{
		ObjectMeta: metav1.ObjectMeta{
			Name:      serviceName,
			Namespace: namespace,
			Annotations: map[string]string{
				"vast.ai/managed":                "true",
				"virtual-kubelet.io/last-update": metav1.Now().Format(time.RFC3339),
			},
		},
		Subsets: []corev1.EndpointSubset{
			{
				Addresses: []corev1.EndpointAddress{
					{
						IP: ip,
					},
				},
				Ports: []corev1.EndpointPort{
					{
						Port: int32(port),
						Protocol: corev1.ProtocolTCP,
					},
				},
			},
		},
	}

	// Try to update existing endpoints first
	_, err := e.clientset.CoreV1().Endpoints(namespace).Update(ctx, endpoints, metav1.UpdateOptions{})
	if err != nil {
		// If update fails, try to create
		_, err = e.clientset.CoreV1().Endpoints(namespace).Create(ctx, endpoints, metav1.CreateOptions{})
		if err != nil {
			return fmt.Errorf("failed to create/update endpoints: %w", err)
		}
	}

	return nil
}

// CleanupPodEndpoints removes endpoints when pod is deleted
func (e *EndpointManager) CleanupPodEndpoints(ctx context.Context, pod *corev1.Pod) error {
	if e.clientset == nil {
		return nil
	}

	log := klog.FromContext(ctx)
	log.Info(fmt.Sprintf("Cleaning up service endpoints for pod %s", pod.Name))

	// Remove endpoints by setting empty subsets
	services := []string{"june-stt", "june-tts"}
	for _, serviceName := range services {
		endpoints, err := e.clientset.CoreV1().Endpoints("default").Get(ctx, serviceName, metav1.GetOptions{})
		if err != nil {
			continue // Service might not exist
		}

		// Clear subsets
		endpoints.Subsets = []corev1.EndpointSubset{}
		
		_, err = e.clientset.CoreV1().Endpoints("default").Update(ctx, endpoints, metav1.UpdateOptions{})
		if err != nil {
			log.Info(fmt.Sprintf("Failed to cleanup %s endpoints: %v", serviceName, err))
		}
	}

	return nil
}