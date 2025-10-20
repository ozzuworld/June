package api

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"

	corev1 "k8s.io/api/core/v1"
	"k8s.io/klog/v2"
)

const (
	VastAPIBaseURL = "https://console.vast.ai/api/v0"
	DefaultTimeout = 30 * time.Second
)

type VastClient struct {
	apiKey     string
	httpClient *http.Client
	baseURL    string
}

// NewVastClient creates a new Vast.ai API client
func NewVastClient(apiKey string) (*VastClient, error) {
	if apiKey == "" {
		return nil, fmt.Errorf("API key is required")
	}

	return &VastClient{
		apiKey: apiKey,
		httpClient: &http.Client{
			Timeout: DefaultTimeout,
		},
		baseURL: VastAPIBaseURL,
	}, nil
}

// TestConnection verifies the API key works
func (c *VastClient) TestConnection(ctx context.Context) error {
	req, err := http.NewRequestWithContext(ctx, "GET", c.baseURL+"/users/current", nil)
	if err != nil {
		return err
	}

	req.Header.Set("Authorization", "Bearer "+c.apiKey)
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("HTTP request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		body, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("API test failed: %d %s", resp.StatusCode, string(body))
	}

	klog.Info("Vast.ai API connection test successful")
	return nil
}

// SearchInstances finds available instances based on criteria
func (c *VastClient) SearchInstances(ctx context.Context, criteria SearchCriteria) ([]InstanceOffer, error) {
	// Build query parameters for Vast.ai search offers API
	params := map[string]string{
		"rentable":        "true",
		"verified":        strconv.FormatBool(criteria.VerifiedOnly),
		"gpu_name":        criteria.GPUType,
		"gpu_ram_gte":     strconv.Itoa(criteria.MinGPUMemoryGB),
		"dph_lte":         fmt.Sprintf("%.2f", criteria.MaxPricePerHour),
		"reliability_gte": fmt.Sprintf("%.2f", criteria.MinReliability),
		"inet_down_gte":   strconv.Itoa(criteria.MinDownloadMbps),
		"inet_up_gte":     strconv.Itoa(criteria.MinUploadMbps),
	}

	// Add geolocation filter
	if len(criteria.PreferredRegions) > 0 {
		params["geolocation_in"] = strings.Join(criteria.PreferredRegions, ",")
	}

	// Build URL with parameters
	url := c.baseURL + "/bundles?"
	var paramPairs []string
	for k, v := range params {
		paramPairs = append(paramPairs, k+"="+v)
	}
	url += strings.Join(paramPairs, "&")

	req, err := http.NewRequestWithContext(ctx, "GET", url, nil)
	if err != nil {
		return nil, err
	}

	req.Header.Set("Authorization", "Bearer "+c.apiKey)
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("search request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("search failed: %d %s", resp.StatusCode, string(body))
	}

	var offers []InstanceOffer
	if err := json.NewDecoder(resp.Body).Decode(&offers); err != nil {
		return nil, fmt.Errorf("failed to decode response: %w", err)
	}

	klog.Infof("Found %d instance offers matching criteria", len(offers))
	return offers, nil
}

// CreateInstance launches a new instance on Vast.ai
func (c *VastClient) CreateInstance(ctx context.Context, offer InstanceOffer, pod *corev1.Pod) (*Instance, error) {
	// Build creation request
	createReq := CreateInstanceRequest{
		ClientID:      "virtual-kubelet-june",
		Image:         "ozzuworld/june-gpu-multi:latest", // TODO: extract from pod spec
		DiskGB:        50,
		DockerOptions: "-p 8000:8000 -p 8001:8001 --gpus all --restart unless-stopped",
		EnvVars: map[string]string{
			"STT_PORT":              "8001",
			"TTS_PORT":              "8000",
			"CUDA_VISIBLE_DEVICES": "0",
			"WHISPER_DEVICE":        "cuda",
			"TTS_CACHE_PATH":        "/app/cache",
			"COQUI_TOS_AGREED":      "1",
		},
		OnStart: "#!/bin/bash\necho '[VAST-K8S] Starting June GPU Multi-Service'\nnvidia-smi\n/app/start-services.sh",
	}

	body, err := json.Marshal(createReq)
	if err != nil {
		return nil, err
	}

	req, err := http.NewRequestWithContext(ctx, "PUT", 
		fmt.Sprintf("%s/asks/%d/", c.baseURL, offer.ID), 
		bytes.NewBuffer(body))
	if err != nil {
		return nil, err
	}

	req.Header.Set("Authorization", "Bearer "+c.apiKey)
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("create instance request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("instance creation failed: %d %s", resp.StatusCode, string(body))
	}

	var createResp CreateInstanceResponse
	if err := json.NewDecoder(resp.Body).Decode(&createResp); err != nil {
		return nil, fmt.Errorf("failed to decode create response: %w", err)
	}

	// Wait for instance to be ready and get connection details
	instance, err := c.waitForInstanceReady(ctx, createResp.NewContract)
	if err != nil {
		return nil, fmt.Errorf("instance failed to start: %w", err)
	}

	klog.Infof("Instance %d created successfully at %s", instance.ID, instance.PublicIP)
	return instance, nil
}

// waitForInstanceReady polls until instance is running
func (c *VastClient) waitForInstanceReady(ctx context.Context, instanceID int) (*Instance, error) {
	timeout := time.After(10 * time.Minute)
	ticker := time.NewTicker(15 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-timeout:
			return nil, fmt.Errorf("timeout waiting for instance %d to be ready", instanceID)
		case <-ticker.C:
			instance, err := c.GetInstance(ctx, instanceID)
			if err != nil {
				continue
			}
			
			if instance.Status == InstanceStatusRunning {
				// Verify services are healthy
				if c.checkInstanceHealth(ctx, instance) {
					return instance, nil
				}
			}
			
			if instance.Status == InstanceStatusFailed {
				return nil, fmt.Errorf("instance %d failed to start", instanceID)
			}
			
			klog.Infof("Waiting for instance %d (status: %s)...", instanceID, instance.Status)
		}
	}
}

// checkInstanceHealth verifies both STT and TTS services are responding
func (c *VastClient) checkInstanceHealth(ctx context.Context, instance *Instance) bool {
	// Check TTS health (port 8000)
	ttsURL := fmt.Sprintf("http://%s:%d/healthz", instance.PublicIP, instance.Ports[8000])
	if !c.checkEndpoint(ctx, ttsURL) {
		return false
	}

	// Check STT health (port 8001)
	sttURL := fmt.Sprintf("http://%s:%d/healthz", instance.PublicIP, instance.Ports[8001])
	if !c.checkEndpoint(ctx, sttURL) {
		return false
	}

	return true
}

func (c *VastClient) checkEndpoint(ctx context.Context, url string) bool {
	client := &http.Client{Timeout: 5 * time.Second}
	req, err := http.NewRequestWithContext(ctx, "GET", url, nil)
	if err != nil {
		return false
	}

	resp, err := client.Do(req)
	if err != nil {
		return false
	}
	defer resp.Body.Close()

	return resp.StatusCode == 200
}

// GetInstance retrieves instance details
func (c *VastClient) GetInstance(ctx context.Context, instanceID int) (*Instance, error) {
	req, err := http.NewRequestWithContext(ctx, "GET", 
		fmt.Sprintf("%s/instances/%d", c.baseURL, instanceID), nil)
	if err != nil {
		return nil, err
	}

	req.Header.Set("Authorization", "Bearer "+c.apiKey)
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("get instance request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("get instance failed: %d %s", resp.StatusCode, string(body))
	}

	var instance Instance
	if err := json.NewDecoder(resp.Body).Decode(&instance); err != nil {
		return nil, fmt.Errorf("failed to decode instance: %w", err)
	}

	return &instance, nil
}

// GetInstanceStatus returns the current status of an instance
func (c *VastClient) GetInstanceStatus(ctx context.Context, instanceID int) (InstanceStatus, error) {
	instance, err := c.GetInstance(ctx, instanceID)
	if err != nil {
		return InstanceStatusUnknown, err
	}
	return instance.Status, nil
}

// UpdateInstance updates an existing instance (limited support)
func (c *VastClient) UpdateInstance(ctx context.Context, instanceID int, pod *corev1.Pod) error {
	// Vast.ai has limited update capabilities
	// Most updates require destroying and recreating the instance
	return fmt.Errorf("instance updates not supported, recreate pod to get new instance")
}

// DestroyInstance terminates an instance
func (c *VastClient) DestroyInstance(ctx context.Context, instanceID int) error {
	req, err := http.NewRequestWithContext(ctx, "DELETE", 
		fmt.Sprintf("%s/instances/%d/", c.baseURL, instanceID), nil)
	if err != nil {
		return err
	}

	req.Header.Set("Authorization", "Bearer "+c.apiKey)
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("destroy instance request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 && resp.StatusCode != 404 {
		body, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("destroy instance failed: %d %s", resp.StatusCode, string(body))
	}

	klog.Infof("Instance %d destroyed", instanceID)
	return nil
}

// GetInstanceLogs retrieves logs from an instance
func (c *VastClient) GetInstanceLogs(ctx context.Context, instanceID int, opts ContainerLogOpts) (io.ReadCloser, error) {
	// Vast.ai doesn't provide direct log API, return empty
	return io.NopCloser(strings.NewReader("Vast.ai logs not available via API\n")), nil
}