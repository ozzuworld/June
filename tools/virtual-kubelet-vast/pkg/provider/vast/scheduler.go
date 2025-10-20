package vast

import (
	"context"
	"fmt"
	"math"
	"sort"
	"strings"

	corev1 "k8s.io/api/core/v1"
	"k8s.io/klog/v2"

	vapi "github.com/ozzuworld/June/tools/virtual-kubelet-vast/pkg/provider/vast/api"
)

// InstanceScheduler handles intelligent selection of Vast.ai instances
type InstanceScheduler struct {
	client  *vapi.VastClient
	config  *SchedulerConfig
	weights *ScoringWeights
}

// SchedulerConfig holds configuration for instance selection
type SchedulerConfig struct {
	// GPU requirements
	GPUType        string
	MinGPUMemoryGB int
	
	// Performance requirements
	MaxPricePerHour  float64
	MinReliability   float64
	MinDownloadMbps  int
	MinUploadMbps    int
	VerifiedOnly     bool
	
	// Geographic preferences (North America optimized)
	PreferredRegions []string
	FallbackRegions  []string
	BlockedRegions   []string
	
	// Latency optimization
	MaxLatencyMS       int
	LatencyCheckEnabled bool
}

// ScoringWeights defines how instances are scored
type ScoringWeights struct {
	Latency      float64 // 35% for North America optimization
	Price        float64 // 25%
	GPUMatch     float64 // 20%
	Reliability  float64 // 15%
	Availability float64 // 5%
	
	// Bonuses/penalties
	USWestCoast    float64 // +0.20
	USCentral      float64 // +0.15
	USEastCoast    float64 // +0.10
	Canada         float64 // +0.05
	ExactGPUMatch  float64 // +0.15
	VerifiedHost   float64 // +0.10
	HighBandwidth  float64 // +0.08
	NewHost        float64 // -0.05
	HighLatency    float64 // -0.30
	NonNALocation  float64 // -0.25
}

// NewInstanceScheduler creates a new scheduler with North America optimized defaults
func NewInstanceScheduler(client *vapi.VastClient) *InstanceScheduler {
	return &InstanceScheduler{
		client: client,
		config: &SchedulerConfig{
			GPUType:             "RTX_3060",
			MinGPUMemoryGB:      12,
			MaxPricePerHour:     0.50,
			MinReliability:      0.95,
			MinDownloadMbps:     100,
			MinUploadMbps:       100,
			VerifiedOnly:        true,
			PreferredRegions:    []string{"US", "CA", "MX"}, // North America
			FallbackRegions:     []string{"EU"},
			BlockedRegions:      []string{"RU", "CN", "KP"},
			MaxLatencyMS:        50,
			LatencyCheckEnabled: true,
		},
		weights: &ScoringWeights{
			Latency:       0.35, // Increased for NA optimization
			Price:        0.25,
			GPUMatch:     0.20,
			Reliability:  0.15,
			Availability: 0.05,
			// Bonuses
			USWestCoast:   0.20,
			USCentral:     0.15,
			USEastCoast:   0.10,
			Canada:        0.05,
			ExactGPUMatch: 0.15,
			VerifiedHost:  0.10,
			HighBandwidth: 0.08,
			NewHost:       -0.05,
			HighLatency:   -0.30,
			NonNALocation: -0.25,
		},
	}
}

// SelectAndLaunchInstance finds the best instance and launches it
func (s *InstanceScheduler) SelectAndLaunchInstance(ctx context.Context, pod *corev1.Pod) (*vapi.Instance, error) {
	log := klog.FromContext(ctx)
	log.Info("Selecting Vast.ai instance for North America deployment")

	// Build search criteria
	criteria := vapi.SearchCriteria{
		GPUType:          s.config.GPUType,
		MinGPUMemoryGB:   s.config.MinGPUMemoryGB,
		MaxPricePerHour:  s.config.MaxPricePerHour,
		MinReliability:   s.config.MinReliability,
		MinDownloadMbps:  s.config.MinDownloadMbps,
		MinUploadMbps:    s.config.MinUploadMbps,
		PreferredRegions: s.config.PreferredRegions,
		VerifiedOnly:     s.config.VerifiedOnly,
		RentableOnly:     true,
	}

	// Search for available instances
	offers, err := s.client.SearchInstances(ctx, criteria)
	if err != nil {
		return nil, fmt.Errorf("failed to search instances: %w", err)
	}

	if len(offers) == 0 {
		return nil, fmt.Errorf("no instances found matching criteria")
	}

	log.Info(fmt.Sprintf("Found %d instance offers, scoring for North America optimization...", len(offers)))

	// Score and select best instance
	bestOffer, err := s.selectBestInstance(ctx, offers)
	if err != nil {
		return nil, fmt.Errorf("failed to select instance: %w", err)
	}

	log.Info(fmt.Sprintf("Selected instance %d (Score: %.3f) in %s for $%.3f/hr",
		bestOffer.Offer.ID, bestOffer.Score, bestOffer.Offer.Geolocation, bestOffer.Offer.DPH))

	// Launch the selected instance
	instance, err := s.client.CreateInstance(ctx, bestOffer.Offer, pod)
	if err != nil {
		return nil, fmt.Errorf("failed to create instance: %w", err)
	}

	log.Info(fmt.Sprintf("Instance %d launched successfully at %s", instance.ID, instance.PublicIP))
	return instance, nil
}

// selectBestInstance scores offers and returns the best match
func (s *InstanceScheduler) selectBestInstance(ctx context.Context, offers []vapi.InstanceOffer) (*vapi.InstanceScore, error) {
	var scores []vapi.InstanceScore

	for _, offer := range offers {
		is := s.scoreInstance(ctx, offer)
		scores = append(scores, is)
	}

	// Sort by score (highest first)
	sort.Slice(scores, func(i, j int) bool { return scores[i].Score > scores[j].Score })

	if len(scores) == 0 {
		return nil, fmt.Errorf("no instances scored")
	}

	// Log top 3 candidates
	for i := 0; i < len(scores) && i < 3; i++ {
		cand := scores[i]
		klog.Info(fmt.Sprintf("Candidate %d: Offer %d, Score %.3f, %s, $%.3f/hr, %s",
			i+1, cand.Offer.ID, cand.Score, cand.Offer.Geolocation, cand.Offer.DPH, strings.Join(cand.Notes, ", ")))
	}

	best := scores[0]
	return &best, nil
}

// scoreInstance calculates a score for an instance offer
func (s *InstanceScheduler) scoreInstance(ctx context.Context, offer vapi.InstanceOffer) vapi.InstanceScore {
	score := 0.0
	notes := []string{}

	// Price (lower is better)
	if s.config.MaxPricePerHour > 0 {
		priceScore := math.Max(0, (s.config.MaxPricePerHour-offer.DPH)/s.config.MaxPricePerHour)
		score += priceScore * s.weights.Price
		notes = append(notes, fmt.Sprintf("price: %.3f", priceScore))
	}

	// Reliability
	relScore := offer.Reliability
	score += relScore * s.weights.Reliability
	notes = append(notes, fmt.Sprintf("reliability: %.3f", relScore))

	// GPU match
	gpuScore := 0.0
	if strings.EqualFold(offer.GPUName, s.config.GPUType) {
		gpuScore = 1.0
		score += s.weights.ExactGPUMatch
		notes = append(notes, "exact GPU match bonus")
	} else if strings.Contains(strings.ToUpper(offer.GPUName), "RTX") {
		gpuScore = 0.7
	}
	score += gpuScore * s.weights.GPUMatch
	notes = append(notes, fmt.Sprintf("gpu: %.3f", gpuScore))

	// Geography bonuses
	loc := strings.ToUpper(offer.Geolocation)
	switch {
	case strings.HasPrefix(loc, "US-CA") || strings.HasPrefix(loc, "US-WA") || strings.HasPrefix(loc, "US-OR"):
		score += s.weights.USWestCoast
		notes = append(notes, "US West Coast bonus")
	case strings.HasPrefix(loc, "US-TX") || strings.HasPrefix(loc, "US-CO") || strings.HasPrefix(loc, "US-AZ"):
		score += s.weights.USCentral
		notes = append(notes, "US Central bonus")
	case strings.HasPrefix(loc, "US-NY") || strings.HasPrefix(loc, "US-FL") || strings.HasPrefix(loc, "US-VA"):
		score += s.weights.USEastCoast
		notes = append(notes, "US East Coast bonus")
	case strings.HasPrefix(loc, "CA-"):
		score += s.weights.Canada
		notes = append(notes, "Canada bonus")
	case loc == "US":
		score += s.weights.USCentral * 0.5
		notes = append(notes, "US general bonus")
	default:
		if loc != "US" && loc != "CA" && loc != "MX" {
			score += s.weights.NonNALocation
			notes = append(notes, "non-NA penalty")
		}
	}

	// Bandwidth bonus
	if offer.InetDown >= 200 {
		score += s.weights.HighBandwidth
		notes = append(notes, "high bandwidth bonus")
	}

	// Verified bonus / new host penalty
	if offer.Verified {
		score += s.weights.VerifiedHost
		notes = append(notes, "verified host bonus")
	}

	if offer.HostRunTime < 30*24*3600 {
		score += s.weights.NewHost
		notes = append(notes, "new host penalty")
	}

	return vapi.InstanceScore{Offer: offer, Score: score, Notes: notes}
}