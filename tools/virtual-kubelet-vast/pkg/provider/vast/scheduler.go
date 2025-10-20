package scheduler

import (
	"context"
	"fmt"
	"math"
	"sort"
	"strings"

	corev1 "k8s.io/api/core/v1"
	"k8s.io/klog/v2"

	"github.com/ozzuworld/June/tools/virtual-kubelet-vast/pkg/provider/vast/api"
)

// InstanceScheduler handles intelligent selection of Vast.ai instances
type InstanceScheduler struct {
	client  *api.VastClient
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
func NewInstanceScheduler(client *api.VastClient) *InstanceScheduler {
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
func (s *InstanceScheduler) SelectAndLaunchInstance(ctx context.Context, pod *corev1.Pod) (*api.Instance, error) {
	log := klog.FromContext(ctx)
	log.Info("Selecting Vast.ai instance for North America deployment")

	// Build search criteria
	criteria := api.SearchCriteria{
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
		bestOffer.ID, bestOffer.Score, bestOffer.Offer.Geolocation, bestOffer.Offer.DPH))

	// Launch the selected instance
	instance, err := s.client.CreateInstance(ctx, bestOffer.Offer, pod)
	if err != nil {
		return nil, fmt.Errorf("failed to create instance: %w", err)
	}

	log.Info(fmt.Sprintf("Instance %d launched successfully at %s", instance.ID, instance.PublicIP))
	return instance, nil
}

// selectBestInstance scores offers and returns the best match
func (s *InstanceScheduler) selectBestInstance(ctx context.Context, offers []api.InstanceOffer) (*api.InstanceScore, error) {
	var scores []api.InstanceScore

	for _, offer := range offers {
		score := s.scoreInstance(ctx, offer)
		scores = append(scores, api.InstanceScore{
			Offer: offer,
			Score: score.Score,
			Notes: score.Notes,
		})
	}

	// Sort by score (highest first)
	sort.Slice(scores, func(i, j int) bool {
		return scores[i].Score > scores[j].Score
	})

	if len(scores) == 0 {
		return nil, fmt.Errorf("no instances scored")
	}

	// Log top 3 candidates for debugging
	for i, score := range scores {
		if i >= 3 {
			break
		}
		klog.Info(fmt.Sprintf("Candidate %d: Instance %d, Score %.3f, %s, $%.3f/hr, %s",
			i+1, score.Offer.ID, score.Score, score.Offer.Geolocation, 
			score.Offer.DPH, strings.Join(score.Notes, ", ")))
	}

	return &scores[0], nil
}

// scoreInstance calculates a score for an instance offer
func (s *InstanceScheduler) scoreInstance(ctx context.Context, offer api.InstanceOffer) api.InstanceScore {
	score := 0.0
	var notes []string

	// Base scoring
	
	// Price score (25% weight, inverse relationship - lower price = higher score)
	priceScore := math.Max(0, (s.config.MaxPricePerHour-offer.DPH)/s.config.MaxPricePerHour)
	score += priceScore * s.weights.Price
	notes = append(notes, fmt.Sprintf("price: %.3f", priceScore))

	// Reliability score (15% weight)
	reliabilityScore := offer.Reliability
	score += reliabilityScore * s.weights.Reliability
	notes = append(notes, fmt.Sprintf("reliability: %.3f", reliabilityScore))

	// GPU match score (20% weight)
	gpuScore := 0.0
	if strings.ToUpper(offer.GPUName) == strings.ToUpper(s.config.GPUType) {
		gpuScore = 1.0
		score += s.weights.ExactGPUMatch // Bonus for exact match
		notes = append(notes, "exact GPU match bonus")
	} else if strings.Contains(strings.ToUpper(offer.GPUName), "RTX") {
		gpuScore = 0.7 // Partial score for RTX family
	}
	score += gpuScore * s.weights.GPUMatch
	notes = append(notes, fmt.Sprintf("gpu: %.3f", gpuScore))

	// Geographic bonuses (North America optimization)
	location := strings.ToUpper(offer.Geolocation)
	if strings.HasPrefix(location, "US-CA") || strings.HasPrefix(location, "US-WA") || strings.HasPrefix(location, "US-OR") {
		score += s.weights.USWestCoast
		notes = append(notes, "US West Coast bonus")
	} else if strings.HasPrefix(location, "US-TX") || strings.HasPrefix(location, "US-CO") || strings.HasPrefix(location, "US-AZ") {
		score += s.weights.USCentral
		notes = append(notes, "US Central bonus")
	} else if strings.HasPrefix(location, "US-NY") || strings.HasPrefix(location, "US-FL") || strings.HasPrefix(location, "US-VA") {
		score += s.weights.USEastCoast
		notes = append(notes, "US East Coast bonus")
	} else if strings.HasPrefix(location, "CA-") {
		score += s.weights.Canada
		notes = append(notes, "Canada bonus")
	} else if location == "US" {
		score += s.weights.USCentral * 0.5 // General US bonus
		notes = append(notes, "US general bonus")
	} else {
		// Non-North America penalty
		if !contains([]string{"US", "CA", "MX"}, location) {
			score += s.weights.NonNALocation
			notes = append(notes, "non-NA penalty")
		}
	}

	// Bandwidth bonus
	if offer.InetDown >= 200 {
		score += s.weights.HighBandwidth
		notes = append(notes, "high bandwidth bonus")
	}

	// Verified host bonus
	if offer.Verified {
		score += s.weights.VerifiedHost
		notes = append(notes, "verified host bonus")
	}

	// New host penalty (low runtime)
	if offer.HostRunTime < 30*24*3600 { // Less than 30 days
		score += s.weights.NewHost
		notes = append(notes, "new host penalty")
	}

	return api.InstanceScore{
		Offer: offer,
		Score: score,
		Notes: notes,
	}
}

// contains checks if slice contains string
func contains(slice []string, item string) bool {
	for _, s := range slice {
		if strings.ToUpper(s) == strings.ToUpper(item) {
			return true
		}
	}
	return false
}