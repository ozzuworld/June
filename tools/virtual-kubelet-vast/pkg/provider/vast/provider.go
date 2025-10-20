package vast

import (
	"context"
	"fmt"
	"io"
	"sync"
	"time"

	"github.com/virtual-kubelet/virtual-kubelet/errdefs"
	pkglog "github.com/virtual-kubelet/virtual-kubelet/log"
	vkapi "github.com/virtual-kubelet/virtual-kubelet/node/api"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	vapi "github.com/ozzuworld/June/tools/virtual-kubelet-vast/pkg/provider/vast/api"
)

// Summary for stats (simplified to avoid kubelet internals)
type Summary struct {
	Node *NodeStats `json:"node"`
}

type NodeStats struct {
	NodeName  string `json:"nodeName"`
	StartTime string `json:"startTime"`
}

type VastProvider struct {
	client     *vapi.VastClient
	nodeName   string
	instances  map[string]*vapi.Instance  // podName -> instance
	mu         sync.RWMutex
	scheduler  *InstanceScheduler
	endpoints  *EndpointManager
}

// NewVastProvider creates a new Vast.ai provider
func NewVastProvider(ctx context.Context, apiKey, nodeName string) (*VastProvider, error) {
	log := pkglog.G(ctx).WithField("provider", "vast.ai")
	
	client, err := vapi.NewVastClient(apiKey)
	if err != nil {
		return nil, fmt.Errorf("failed to create Vast.ai client: %w", err)
	}

	// Test API connectivity
	if err := client.TestConnection(ctx); err != nil {
		return nil, fmt.Errorf("failed to connect to Vast.ai API: %w", err)
	}

	log.Info("Successfully connected to Vast.ai API")

	p := &VastProvider{
		client:    client,
		nodeName:  nodeName,
		instances: make(map[string]*vapi.Instance),
	}

	// Initialize scheduler
	p.scheduler = NewInstanceScheduler(client)
	
	// Initialize endpoint manager
	p.endpoints = NewEndpointManager()

	return p, nil
}

// ConfigureNode enables a provider to configure the node object that will be used for the provider
func (p *VastProvider) ConfigureNode(ctx context.Context, node *corev1.Node) {
	log := pkglog.G(ctx).WithField("node", p.nodeName)
	
	node.Status.Capacity = corev1.ResourceList{
		"cpu":            *resource.NewQuantity(16, resource.DecimalSI),
		"memory":         *resource.NewQuantity(32*1024*1024*1024, resource.BinarySI),
		"nvidia.com/gpu": *resource.NewQuantity(1, resource.DecimalSI),
		"pods":           *resource.NewQuantity(10, resource.DecimalSI),
	}
	node.Status.Allocatable = node.Status.Capacity
	
	node.Status.NodeInfo = corev1.NodeSystemInfo{
		Architecture:    "amd64",
		OperatingSystem: "linux",
		KernelVersion:   "5.15.0",
		OSImage:        "Ubuntu 22.04 LTS",
		ContainerRuntimeVersion: "docker://24.0.0",
		KubeletVersion: "v1.28.0-vk-vast",
		KubeProxyVersion: "v1.28.0-vk-vast",
	}

	node.Status.Addresses = []corev1.NodeAddress{
		{
			Type:    corev1.NodeInternalIP,
			Address: "10.0.0.1",
		},
	}

	node.Status.DaemonEndpoints = corev1.NodeDaemonEndpoints{
		KubeletEndpoint: corev1.DaemonEndpoint{
			Port: 10250,
		},
	}

	// Set conditions
	node.Status.Conditions = []corev1.NodeCondition{
		{
			Type:               corev1.NodeReady,
			Status:             corev1.ConditionTrue,
			LastHeartbeatTime:  metav1.Now(),
			LastTransitionTime: metav1.Now(),
			Reason:            "VirtualKubeletReady",
			Message:           "Virtual Kubelet is ready",
		},
		{
			Type:               corev1.NodeMemoryPressure,
			Status:             corev1.ConditionFalse,
			LastHeartbeatTime:  metav1.Now(),
			LastTransitionTime: metav1.Now(),
			Reason:            "VirtualKubeletHasSufficientMemory",
			Message:           "Virtual Kubelet has sufficient memory",
		},
		{
			Type:               corev1.NodeDiskPressure,
			Status:             corev1.ConditionFalse,
			LastHeartbeatTime:  metav1.Now(),
			LastTransitionTime: metav1.Now(),
			Reason:            "VirtualKubeletHasNoDiskPressure",
			Message:           "Virtual Kubelet has no disk pressure",
		},
		{
			Type:               corev1.NodePIDPressure,
			Status:             corev1.ConditionFalse,
			LastHeartbeatTime:  metav1.Now(),
			LastTransitionTime: metav1.Now(),
			Reason:            "VirtualKubeletHasSufficientPID",
			Message:           "Virtual Kubelet has sufficient PID",
		},
	}

	log.Info("Node configured for Vast.ai GPU provider")
}

// NotifyNodeStatus implements node.NodeProvider interface for VK v1.11
func (p *VastProvider) NotifyNodeStatus(ctx context.Context, notifierFunc func(*corev1.Node)) {
	log := pkglog.G(ctx).WithField("provider", "vast.ai")
	log.Info("Starting node status monitoring")

	ticker := time.NewTicker(60 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			// Create updated node status
			node := &corev1.Node{
				ObjectMeta: metav1.ObjectMeta{
					Name: p.nodeName,
				},
				Status: corev1.NodeStatus{
					Conditions: []corev1.NodeCondition{
						{
							Type:               corev1.NodeReady,
							Status:             corev1.ConditionTrue,
							LastHeartbeatTime:  metav1.Now(),
							LastTransitionTime: metav1.Now(),
							Reason:            "VastProviderHealthy",
							Message:           "Vast.ai provider is healthy",
						},
					},
				},
			}
			
			// Configure full node status
			p.ConfigureNode(ctx, node)
			
			// Notify controller of updated node status
			notifierFunc(node)
		}
	}
}

// CreatePod accepts a Pod definition and creates a Vast.ai instance
func (p *VastProvider) CreatePod(ctx context.Context, pod *corev1.Pod) error {
	log := pkglog.G(ctx).WithField("pod", pod.Name)
	log.Info("Creating pod on Vast.ai")

	// Select and launch instance
	instance, err := p.scheduler.SelectAndLaunchInstance(ctx, pod)
	if err != nil {
		return fmt.Errorf("failed to launch Vast.ai instance: %w", err)
	}

	// Store instance mapping
	p.mu.Lock()
	p.instances[pod.Name] = instance
	p.mu.Unlock()

	// Update service endpoints
	if err := p.endpoints.UpdatePodEndpoints(ctx, pod, instance); err != nil {
		log.WithError(err).Warn("Failed to update service endpoints")
	}

	log.WithField("instanceId", instance.ID).Info("Pod created on Vast.ai")
	return nil
}

// UpdatePod accepts a Pod definition and updates the existing instance
func (p *VastProvider) UpdatePod(ctx context.Context, pod *corev1.Pod) error {
	log := pkglog.G(ctx).WithField("pod", pod.Name)
	log.Info("Updating pod on Vast.ai")

	p.mu.RLock()
	instance, exists := p.instances[pod.Name]
	p.mu.RUnlock()

	if !exists {
		return fmt.Errorf("instance for pod %s not found", pod.Name)
	}

	// Update instance configuration if needed
	if err := p.client.UpdateInstance(ctx, instance.ID, pod); err != nil {
		return fmt.Errorf("failed to update instance: %w", err)
	}

	log.WithField("instanceId", instance.ID).Info("Pod updated on Vast.ai")
	return nil
}

// DeletePod accepts a Pod definition and deletes the Vast.ai instance
func (p *VastProvider) DeletePod(ctx context.Context, pod *corev1.Pod) error {
	log := pkglog.G(ctx).WithField("pod", pod.Name)
	log.Info("Deleting pod from Vast.ai")

	p.mu.RLock()
	instance, exists := p.instances[pod.Name]
	p.mu.RUnlock()

	if !exists {
		log.Warn("Instance for pod not found, assuming already deleted")
		return nil
	}

	// Destroy instance
	if err := p.client.DestroyInstance(ctx, instance.ID); err != nil {
		return fmt.Errorf("failed to destroy instance: %w", err)
	}

	// Remove from tracking
	p.mu.Lock()
	delete(p.instances, pod.Name)
	p.mu.Unlock()

	// Clean up endpoints
	if err := p.endpoints.CleanupPodEndpoints(ctx, pod); err != nil {
		log.WithError(err).Warn("Failed to cleanup service endpoints")
	}

	log.WithField("instanceId", instance.ID).Info("Pod deleted from Vast.ai")
	return nil
}

// GetPod returns a pod by name that is being managed by the provider
func (p *VastProvider) GetPod(ctx context.Context, namespace, name string) (*corev1.Pod, error) {
	p.mu.RLock()
	instance, exists := p.instances[name]
	p.mu.RUnlock()

	if !exists {
		return nil, errdefs.NotFound("pod not found")
	}

	// Get current instance status
	status, err := p.client.GetInstanceStatus(ctx, instance.ID)
	if err != nil {
		return nil, fmt.Errorf("failed to get instance status: %w", err)
	}

	// Convert to pod status
	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Namespace: namespace,
			Name:      name,
		},
		Status: corev1.PodStatus{
			Phase: p.convertInstanceStatusToPodPhase(status),
			Conditions: []corev1.PodCondition{
				{
					Type:   corev1.PodReady,
					Status: p.convertInstanceStatusToConditionStatus(status),
					LastTransitionTime: metav1.Now(),
				},
			},
			ContainerStatuses: []corev1.ContainerStatus{
				{
					Name:  "june-multi-gpu",
					Ready: status == vapi.InstanceStatusRunning,
					State: corev1.ContainerState{
						Running: &corev1.ContainerStateRunning{
							StartedAt: metav1.Now(),
						},
					},
				},
			},
		},
	}

	return pod, nil
}

// GetPodStatus returns the status of a pod by name that is being managed by the provider
func (p *VastProvider) GetPodStatus(ctx context.Context, namespace, name string) (*corev1.PodStatus, error) {
	pod, err := p.GetPod(ctx, namespace, name)
	if err != nil {
		return nil, err
	}
	return &pod.Status, nil
}

// GetPods returns a list of all pods known to be running within the provider
func (p *VastProvider) GetPods(ctx context.Context) ([]*corev1.Pod, error) {
	p.mu.RLock()
	defer p.mu.RUnlock()

	var pods []*corev1.Pod
	for podName := range p.instances {
		pod, err := p.GetPod(ctx, "default", podName)
		if err != nil {
			continue
		}
		pods = append(pods, pod)
	}

	return pods, nil
}

// RunInContainer executes a command in a container in the pod
func (p *VastProvider) RunInContainer(ctx context.Context, namespace, podName, containerName string, cmd []string, attach vkapi.AttachIO) error {
	return fmt.Errorf("RunInContainer not supported for Vast.ai provider")
}

// GetPodLogs retrieves the logs of a container of the specified pod
func (p *VastProvider) GetPodLogs(ctx context.Context, namespace, podName, containerName string, opts vkapi.ContainerLogOpts) (io.ReadCloser, error) {
	p.mu.RLock()
	instance, exists := p.instances[podName]
	p.mu.RUnlock()

	if !exists {
		return nil, errdefs.NotFound("pod not found")
	}

	return p.client.GetInstanceLogs(ctx, instance.ID, vapi.ContainerLogOpts{})
}

// GetStatsSummary returns the stats for all pods known by this provider
func (p *VastProvider) GetStatsSummary(ctx context.Context) (*Summary, error) {
	return &Summary{
		Node: &NodeStats{
			NodeName:  p.nodeName,
			StartTime: time.Now().Format(time.RFC3339),
		},
	}, nil
}

// NotifyPods instructs the notifier to call the passed in function when the pod status changes
func (p *VastProvider) NotifyPods(ctx context.Context, notifierFunc func(*corev1.Pod)) {
	log := pkglog.G(ctx).WithField("provider", "vast.ai")
	log.Info("Starting pod status monitoring")

	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			p.checkAndNotifyPodStatuses(ctx, notifierFunc)
		}
	}
}

func (p *VastProvider) checkAndNotifyPodStatuses(ctx context.Context, notifierFunc func(*corev1.Pod)) {
	p.mu.RLock()
	instances := make(map[string]*vapi.Instance)
	for k, v := range p.instances {
		instances[k] = v
	}
	p.mu.RUnlock()

	for podName, instance := range instances {
		status, err := p.client.GetInstanceStatus(ctx, instance.ID)
		if err != nil {
			continue
		}

		pod, err := p.GetPod(ctx, "default", podName)
		if err != nil {
			continue
		}

		pod.Status.Phase = p.convertInstanceStatusToPodPhase(status)
		notifierFunc(pod)
	}
}

func (p *VastProvider) convertInstanceStatusToPodPhase(status vapi.InstanceStatus) corev1.PodPhase {
	switch status {
	case vapi.InstanceStatusRunning:
		return corev1.PodRunning
	case vapi.InstanceStatusStarting:
		return corev1.PodPending
	case vapi.InstanceStatusStopped:
		return corev1.PodSucceeded
	case vapi.InstanceStatusFailed:
		return corev1.PodFailed
	default:
		return corev1.PodPending
	}
}

func (p *VastProvider) convertInstanceStatusToConditionStatus(status vapi.InstanceStatus) corev1.ConditionStatus {
	if status == vapi.InstanceStatusRunning {
		return corev1.ConditionTrue
	}
	return corev1.ConditionFalse
}