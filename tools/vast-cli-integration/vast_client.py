#!/usr/bin/env python3
"""
Clean Vast.ai CLI Client
Properly wraps the official vast.ai CLI with correct command usage
"""
import json
import subprocess
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class VastOffer:
    """Represents a vast.ai offer"""
    id: int
    gpu_name: str
    num_gpus: int
    dph_total: float
    gpu_ram: float
    reliability: float
    datacenter: bool
    verified: bool
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'VastOffer':
        return cls(
            id=data['id'],
            gpu_name=data.get('gpu_name', ''),
            num_gpus=data.get('num_gpus', 0),
            dph_total=data.get('dph_total', 0.0),
            gpu_ram=data.get('gpu_ram', 0.0),
            reliability=data.get('reliability', 0.0),
            datacenter=data.get('datacenter', False),
            verified=data.get('verified', False)
        )

@dataclass 
class VastInstance:
    """Represents a vast.ai instance"""
    id: int
    machine_id: int
    status_msg: str
    public_ipaddr: Optional[str]
    ssh_host: Optional[str]
    ssh_port: Optional[int]
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'VastInstance':
        return cls(
            id=data['id'],
            machine_id=data.get('machine_id', 0),
            status_msg=data.get('status_msg', ''),
            public_ipaddr=data.get('public_ipaddr'),
            ssh_host=data.get('ssh_host'),
            ssh_port=data.get('ssh_port')
        )

class VastCliClient:
    """
    Clean wrapper around the official vast.ai CLI
    Uses subprocess to call the official vastai commands
    """
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        if api_key:
            self._set_api_key(api_key)
    
    def _set_api_key(self, api_key: str) -> None:
        """Set the API key using the CLI"""
        try:
            result = subprocess.run(
                ['vastai', 'set', 'api-key', api_key],
                capture_output=True,
                text=True,
                check=True
            )
            logger.info("API key set successfully")
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to set API key: {e.stderr}")
            raise
    
    def _run_command(self, cmd: List[str], expect_json: bool = True) -> Any:
        """Run a vastai command and return the result"""
        try:
            # Always add --raw for JSON output when expecting JSON
            if expect_json and '--raw' not in cmd:
                cmd.append('--raw')
            
            logger.debug(f"Running command: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
            
            if expect_json:
                if result.stdout.strip():
                    return json.loads(result.stdout)
                else:
                    return {}
            else:
                return result.stdout
                
        except subprocess.CalledProcessError as e:
            logger.error(f"Command failed: {' '.join(cmd)}")
            logger.error(f"Error: {e.stderr}")
            raise VastCliError(f"CLI command failed: {e.stderr}")
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            logger.error(f"Raw output: {result.stdout}")
            raise VastCliError(f"Invalid JSON response: {e}")
    
    def search_offers(
        self,
        query: str = 'rentable=true verified=true',
        order: str = 'dph_total+',
        limit: int = 10
    ) -> List[VastOffer]:
        """
        Search for available offers
        
        Args:
            query: Search query (e.g., 'gpu_name=RTX_3090 num_gpus=1')
            order: Sort order (e.g., 'dph_total+' for ascending price)
            limit: Maximum number of results
        
        Returns:
            List of VastOffer objects
        """
        cmd = ['vastai', 'search', 'offers']
        if query:
            cmd.append(query)
        if order:
            cmd.extend(['-o', order])
        
        data = self._run_command(cmd, expect_json=True)
        
        # Handle both list and dict responses
        if isinstance(data, list):
            offers = data[:limit]
        elif isinstance(data, dict):
            offers = [data]
        else:
            offers = []
        
        return [VastOffer.from_dict(offer) for offer in offers]
    
    def create_instance(
        self,
        offer_id: int,
        image: str,
        disk: int = 50,
        ssh: bool = True,
        direct: bool = True,
        env: Optional[str] = None,
        onstart_cmd: Optional[str] = None,
        label: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create an instance from an offer
        
        Args:
            offer_id: ID from search_offers
            image: Docker image to use
            disk: Disk size in GB
            ssh: Enable SSH access
            direct: Use direct connection
            env: Environment variables (e.g., '-p 8000:8000 -e VAR=value')
            onstart_cmd: Command to run on startup
            label: Instance label
        
        Returns:
            Dict with instance creation result
        """
        cmd = ['vastai', 'create', 'instance', str(offer_id)]
        cmd.extend(['--image', image])
        cmd.extend(['--disk', str(disk)])
        
        if ssh:
            cmd.append('--ssh')
        if direct:
            cmd.append('--direct')
        if env:
            cmd.extend(['--env', env])
        if onstart_cmd:
            cmd.extend(['--onstart-cmd', onstart_cmd])
        if label:
            cmd.extend(['--label', label])
        
        return self._run_command(cmd, expect_json=True)
    
    def show_instances(self) -> List[VastInstance]:
        """Get all user instances"""
        cmd = ['vastai', 'show', 'instances']
        data = self._run_command(cmd, expect_json=True)
        
        if isinstance(data, list):
            instances = data
        else:
            instances = [data] if data else []
        
        return [VastInstance.from_dict(inst) for inst in instances]
    
    def show_instance(self, instance_id: int) -> Optional[VastInstance]:
        """Get details of a specific instance"""
        cmd = ['vastai', 'show', 'instance', str(instance_id)]
        try:
            data = self._run_command(cmd, expect_json=True)
            return VastInstance.from_dict(data) if data else None
        except VastCliError:
            return None
    
    def destroy_instance(self, instance_id: int) -> Dict[str, Any]:
        """Destroy an instance"""
        cmd = ['vastai', 'destroy', 'instance', str(instance_id)]
        return self._run_command(cmd, expect_json=True)
    
    def start_instance(self, instance_id: int) -> Dict[str, Any]:
        """Start a stopped instance"""
        cmd = ['vastai', 'start', 'instance', str(instance_id)]
        return self._run_command(cmd, expect_json=True)
    
    def stop_instance(self, instance_id: int) -> Dict[str, Any]:
        """Stop a running instance"""
        cmd = ['vastai', 'stop', 'instance', str(instance_id)]
        return self._run_command(cmd, expect_json=True)
    
    def show_user(self) -> Dict[str, Any]:
        """Get current user information"""
        cmd = ['vastai', 'show', 'user']
        return self._run_command(cmd, expect_json=True)

class VastCliError(Exception):
    """Custom exception for Vast CLI errors"""
    pass

# Example usage and testing functions
def test_connection():
    """Test the vast.ai CLI connection"""
    client = VastCliClient()
    
    try:
        user_info = client.show_user()
        print(f"✓ Connected as user: {user_info.get('username', 'unknown')}")
        return True
    except Exception as e:
        print(f"✗ Connection failed: {e}")
        return False

def find_cheapest_gpu(gpu_type: str = "RTX_3060", max_price: float = 0.50) -> Optional[VastOffer]:
    """Find the cheapest available GPU of a specific type"""
    client = VastCliClient()
    
    # Build query
    query = f'gpu_name={gpu_type} dph_total<={max_price} rentable=true verified=true'
    
    try:
        offers = client.search_offers(query=query, order='dph_total+', limit=5)
        if offers:
            cheapest = offers[0]
            print(f"Found {gpu_type} for ${cheapest.dph_total:.4f}/hr (ID: {cheapest.id})")
            return cheapest
        else:
            print(f"No {gpu_type} found under ${max_price}/hr")
            return None
    except Exception as e:
        print(f"Search failed: {e}")
        return None

if __name__ == "__main__":
    # Test the client
    print("Testing Vast.ai CLI client...")
    
    if test_connection():
        print("\n" + "="*50)
        print("Searching for available GPUs...")
        offer = find_cheapest_gpu("RTX_3060", 0.30)
        
        if offer:
            print(f"\nFound offer: {offer}")
            # Don't actually create instance in test mode
            print("(Would create instance here in production)")