package vast

import (
	"context"
)

// Ping implements node.NodeProvider liveness probe for VK v1.11
func (p *VastProvider) Ping(ctx context.Context) error {
	return nil
}
