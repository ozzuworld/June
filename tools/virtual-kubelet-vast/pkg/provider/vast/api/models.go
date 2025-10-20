package api

import "time"

// InstanceStatus represents the status of a Vast.ai instance
type InstanceStatus string

const (
	InstanceStatusUnknown  InstanceStatus = "unknown"
	InstanceStatusStarting InstanceStatus = "loading"
	InstanceStatusRunning  InstanceStatus = "running"
	InstanceStatusStopped  InstanceStatus = "stopped"
	InstanceStatusFailed   InstanceStatus = "failed"
)

// SearchCriteria defines the criteria for selecting Vast.ai instances
type SearchCriteria struct {
	GPUType           string
	MinGPUMemoryGB    int
	MaxPricePerHour   float64
	MinReliability    float64
	MinDownloadMbps   int
	MinUploadMbps     int
	PreferredRegions  []string
	VerifiedOnly      bool
	RentableOnly      bool
}

// InstanceOffer represents an available instance from Vast.ai search
type InstanceOffer struct {
	ID               int     `json:"id"`
	PublicIPAddr     string  `json:"public_ipaddr"`
	Geolocation      string  `json:"geolocation"`
	GPUName          string  `json:"gpu_name"`
	GPURam           int     `json:"gpu_ram"`
	DPH              float64 `json:"dph"`
	Reliability      float64 `json:"reliability2"`
	InetDownCost     float64 `json:"inet_down_cost"`
	InetUpCost       float64 `json:"inet_up_cost"`
	InetDown         int     `json:"inet_down"`
	InetUp           int     `json:"inet_up"`
	Verified         bool    `json:"verified"`
	Rentable         bool    `json:"rentable"`
	CPUCores         int     `json:"cpu_cores"`
	CPUCoresEffective int    `json:"cpu_cores_effective"`
	Ram              int     `json:"ram"`
	DiskSpace        int     `json:"disk_space"`
	StartupScript    string  `json:"startup_script"`
	HostRunTime      int     `json:"host_run_time"`
}

// Instance represents a running Vast.ai instance
type Instance struct {
	ID              int                `json:"id"`
	PublicIP        string             `json:"public_ipaddr"`
	Status          InstanceStatus     `json:"actual_status"`
	Ports           map[int]int        `json:"ports"` // internal -> external
	SSHHost         string             `json:"ssh_host"`
	SSHPort         int                `json:"ssh_port"`
	CreatedAt       time.Time          `json:"start_date"`
	GPUName         string             `json:"gpu_name"`
	GPURam          int                `json:"gpu_ram"`
	DPH             float64            `json:"dph_total"`
	Geolocation     string             `json:"geolocation"`
	Label           string             `json:"label"`
}

// CreateInstanceRequest represents the request to create a new instance
type CreateInstanceRequest struct {
	ClientID      string            `json:"client_id"`
	Image         string            `json:"image"`
	DiskGB        int               `json:"disk"`
	DockerOptions string            `json:"args"`
	EnvVars       map[string]string `json:"env"`
	OnStart       string            `json:"onstart"`
	RunType       string            `json:"runtype"` // "ssh" or "jupyter"
}

// CreateInstanceResponse represents the response from instance creation
type CreateInstanceResponse struct {
	Success     bool   `json:"success"`
	NewContract int    `json:"new_contract"`
	Message     string `json:"msg"`
}

// ContainerLogOpts represents options for container logs (Virtual Kubelet interface)
type ContainerLogOpts struct {
	Tail         int
	SinceSeconds *int64
	SinceTime    *time.Time
	Timestamps   bool
	Follow       bool
	Previous     bool
	LimitBytes   *int64
}

// InstanceScore represents a scored instance for selection
type InstanceScore struct {
	Offer InstanceOffer
	Score float64
	Notes []string // Debugging info about scoring
}