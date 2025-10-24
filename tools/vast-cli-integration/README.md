# Clean Vast.ai CLI Integration for June Services

This directory contains a clean implementation for deploying June TTS/STT services on Vast.ai GPU instances using the official Vast.ai CLI.

## Overview

This implementation replaces the previous flawed virtual-kubelet approach with a clean, simple, and reliable method that:

1. Uses the official `vastai` CLI tool correctly
2. Follows Vast.ai documentation and best practices
3. Provides proper error handling and logging
4. Supports Tailscale networking for secure access
5. Includes comprehensive testing

## Files

- `vast-setup.sh` - Sets up and configures the Vast.ai CLI
- `vast_client.py` - Clean Python wrapper for the Vast.ai CLI
- `june-stack.yml` - Docker Compose file for June services
- `startup-june.sh` - Instance startup script for automated deployment
- `test_vast_integration.py` - Complete integration test suite
- `README.md` - This file

## Quick Start

### 1. Prerequisites

- Python 3.8+
- A Vast.ai account with API key
- (Optional) Tailscale account for networking

### 2. Setup

```bash
# Set your Vast.ai API key
export VAST_API_KEY="your_vast_api_key_here"

# (Optional) Set Tailscale auth key for networking
export TAILSCALE_AUTH_KEY="your_tailscale_auth_key"

# Install and setup Vast.ai CLI
chmod +x vast-setup.sh
./vast-setup.sh
```

### 3. Test the Integration

```bash
# Run basic tests (no instance creation)
python3 test_vast_integration.py

# Run full tests including instance creation (costs money!)
python3 test_vast_integration.py --create-instance
```

### 4. Use the Client

```python
from vast_client import VastCliClient, find_cheapest_gpu

# Create client
client = VastCliClient()

# Find offers
offers = client.search_offers('gpu_name=RTX_3060 dph_total<=0.50')

# Create instance
if offers:
    result = client.create_instance(
        offer_id=offers[0].id,
        image='pytorch/pytorch:2.0.1-cuda11.7-cudnn8-devel',
        disk=50,
        ssh=True,
        direct=True,
        onstart_cmd=open('startup-june.sh').read()
    )
```

## Deployment Workflow

### Automated Deployment

The complete workflow to deploy June services:

```python
from vast_client import VastCliClient

client = VastCliClient()

# 1. Find suitable GPU
offers = client.search_offers(
    query='gpu_ram>=8 dph_total<=0.40 rentable=true verified=true',
    order='dph_total+',
    limit=5
)

if not offers:
    print("No suitable offers found")
    exit(1)

# 2. Prepare startup script
startup_script = open('startup-june.sh', 'r').read()

# 3. Create instance
result = client.create_instance(
    offer_id=offers[0].id,
    image='pytorch/pytorch:2.0.1-cuda11.7-cudnn8-devel',
    disk=50,
    ssh=True,
    direct=True,
    env='-p 8000:8000 -p 8001:8001',
    onstart_cmd=startup_script,
    label='june-tts-stt'
)

print(f"Instance created: {result}")
```

### Manual Steps

1. **Search for offers:**
   ```bash
   vastai search offers 'gpu_name=RTX_3060 dph_total<=0.40 rentable=true'
   ```

2. **Create instance:**
   ```bash
   vastai create instance OFFER_ID \
     --image pytorch/pytorch:2.0.1-cuda11.7-cudnn8-devel \
     --disk 50 \
     --ssh \
     --direct \
     --env '-p 8000:8000 -p 8001:8001' \
     --onstart startup-june.sh
   ```

3. **Monitor instance:**
   ```bash
   vastai show instances
   ```

## Configuration

### Environment Variables

- `VAST_API_KEY` - Your Vast.ai API key (required)
- `TAILSCALE_AUTH_KEY` - Tailscale auth key for networking (optional)
- `TTS_PORT` - Port for TTS service (default: 8000)
- `STT_PORT` - Port for STT service (default: 8001)

### Search Parameters

Common search queries for different use cases:

```bash
# Budget GPU (RTX 3060)
'gpu_name=RTX_3060 dph_total<=0.30 rentable=true verified=true'

# Performance GPU (RTX 4090)  
'gpu_name=RTX_4090 gpu_ram>=24 dph_total<=1.00 rentable=true'

# Datacenter only
'datacenter=true verified=true reliability>=0.95'

# Specific regions
'geolocation=US dph_total<=0.50 rentable=true'
```

## Troubleshooting

### Common Issues

1. **API Key Authentication Failed**
   ```
   Error: API key verification failed
   ```
   - Ensure your API key is correct
   - Check that you have sufficient credits
   - Verify the key has proper permissions

2. **No Offers Found**
   ```
   No suitable offers found
   ```
   - Adjust your search criteria (price, GPU type, etc.)
   - Try different regions
   - Check during off-peak hours

3. **Instance Creation Failed**
   ```
   CLI command failed: offer no longer available
   ```
   - The offer was taken by another user
   - Try a different offer ID
   - Use automated retry logic

4. **Services Not Starting**
   - Check instance logs: `vastai logs INSTANCE_ID`
   - Verify Docker images are accessible
   - Ensure sufficient GPU memory

### Debug Mode

Enable debug logging:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Manual Instance Access

Connect to your instance via SSH:

```bash
# Get SSH details
vastai show instance INSTANCE_ID

# Connect
ssh -p SSH_PORT root@SSH_HOST
```

## Costs and Optimization

### Cost Estimation

- RTX 3060: ~$0.15-0.30/hour
- RTX 4060: ~$0.25-0.40/hour  
- RTX 4090: ~$0.60-1.20/hour

### Optimization Tips

1. **Use interruptible instances** for development
2. **Stop instances** when not in use
3. **Monitor usage** with `vastai show invoices`
4. **Set price limits** in search queries
5. **Use smaller disk sizes** when possible

## Integration with Kubernetes

This client can be integrated into your existing Kubernetes infrastructure:

1. **ConfigMap** for configuration
2. **Secrets** for API keys  
3. **Jobs** for automated deployment
4. **Services** for networking

See your existing virtual-kubelet implementation for Kubernetes integration patterns.

## Security Notes

- API keys should be stored securely (Kubernetes secrets, environment variables)
- Use Tailscale or VPN for secure access to services
- Regularly rotate API keys
- Monitor for unauthorized usage

## Support

For issues with:
- **This implementation**: Check logs and troubleshooting section
- **Vast.ai platform**: Visit https://vast.ai/docs or contact support  
- **June services**: Check the main repository documentation

## Migration from Previous Implementation

To migrate from the old virtual-kubelet approach:

1. Stop the old virtual-kubelet deployment
2. Install this clean implementation
3. Update your scripts to use the new client
4. Test thoroughly before production use

The API is simpler and more reliable than the previous implementation.