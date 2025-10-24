#!/usr/bin/env python3
"""
Vast.ai Integration Test Suite
Tests the complete workflow from CLI setup to instance creation
"""

import os
import sys
import time
import logging
from typing import Optional, Dict, Any
from vast_client import VastCliClient, VastOffer, test_connection

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class VastIntegrationTester:
    """Complete integration test suite for Vast.ai CLI integration"""
    
    def __init__(self):
        self.client = VastCliClient()
        self.test_results = {}
        self.created_instances = []
    
    def run_all_tests(self, create_instance: bool = False) -> Dict[str, bool]:
        """
        Run the complete test suite
        
        Args:
            create_instance: Whether to actually create a test instance
            
        Returns:
            Dictionary of test results
        """
        logger.info("🚀 Starting Vast.ai Integration Test Suite")
        logger.info("=" * 60)
        
        # Test 1: CLI Installation and Setup
        self.test_results['cli_setup'] = self._test_cli_setup()
        
        # Test 2: Authentication
        self.test_results['authentication'] = self._test_authentication()
        
        # Test 3: Search Functionality
        self.test_results['search_offers'] = self._test_search_offers()
        
        # Test 4: User Information
        self.test_results['user_info'] = self._test_user_info()
        
        # Test 5: Instance Management (optional)
        if create_instance:
            self.test_results['instance_creation'] = self._test_instance_creation()
        
        # Summary
        self._print_test_summary()
        
        return self.test_results
    
    def _test_cli_setup(self) -> bool:
        """Test CLI installation and basic functionality"""
        logger.info("🔧 Testing CLI setup...")
        
        try:
            # Check if vastai CLI is available
            import subprocess
            result = subprocess.run(['vastai', '--version'], 
                                  capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                logger.info("✅ CLI installation: PASSED")
                return True
            else:
                logger.error("❌ CLI installation: FAILED")
                return False
                
        except Exception as e:
            logger.error(f"❌ CLI setup error: {e}")
            return False
    
    def _test_authentication(self) -> bool:
        """Test API authentication"""
        logger.info("🔐 Testing authentication...")
        
        try:
            if test_connection():
                logger.info("✅ Authentication: PASSED")
                return True
            else:
                logger.error("❌ Authentication: FAILED")
                return False
                
        except Exception as e:
            logger.error(f"❌ Authentication error: {e}")
            return False
    
    def _test_search_offers(self) -> bool:
        """Test search functionality with different queries"""
        logger.info("🔍 Testing search offers...")
        
        try:
            # Test 1: Basic search
            offers = self.client.search_offers(
                query='rentable=true verified=true',
                limit=5
            )
            
            if not offers:
                logger.warning("⚠️ No offers found with basic query")
                return False
            
            logger.info(f"✅ Basic search: Found {len(offers)} offers")
            
            # Test 2: GPU-specific search
            gpu_offers = self.client.search_offers(
                query='gpu_name=RTX_3060 rentable=true',
                limit=3
            )
            
            logger.info(f"✅ GPU search: Found {len(gpu_offers)} RTX 3060 offers")
            
            # Test 3: Price-filtered search
            cheap_offers = self.client.search_offers(
                query='dph_total<=0.30 rentable=true verified=true',
                order='dph_total+',
                limit=3
            )
            
            logger.info(f"✅ Price search: Found {len(cheap_offers)} offers under $0.30/hr")
            
            if cheap_offers:
                cheapest = cheap_offers[0]
                logger.info(f"   Cheapest: {cheapest.gpu_name} @ ${cheapest.dph_total:.4f}/hr")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Search offers error: {e}")
            return False
    
    def _test_user_info(self) -> bool:
        """Test user information retrieval"""
        logger.info("👤 Testing user information...")
        
        try:
            user_info = self.client.show_user()
            
            username = user_info.get('username', 'unknown')
            balance = user_info.get('credit', 'unknown')
            
            logger.info(f"✅ User info: {username} (Balance: ${balance})")
            return True
            
        except Exception as e:
            logger.error(f"❌ User info error: {e}")
            return False
    
    def _test_instance_creation(self) -> bool:
        """Test instance creation and management"""
        logger.info("🖥️  Testing instance creation...")
        
        try:
            # Find a cheap offer for testing
            offers = self.client.search_offers(
                query='dph_total<=0.20 rentable=true verified=true gpu_ram>=4',
                order='dph_total+',
                limit=3
            )
            
            if not offers:
                logger.warning("⚠️ No suitable offers found for instance creation test")
                return False
            
            test_offer = offers[0]
            logger.info(f"Using offer: {test_offer.gpu_name} @ ${test_offer.dph_total:.4f}/hr")
            
            # Create startup script content
            startup_script = '''#!/bin/bash
echo "Test instance started at $(date)" > /tmp/test_result.txt
echo "GPU Info:" >> /tmp/test_result.txt
nvidia-smi >> /tmp/test_result.txt 2>&1 || echo "No NVIDIA GPU detected" >> /tmp/test_result.txt
echo "Instance test complete" >> /tmp/test_result.txt
'''
            
            # Create instance
            result = self.client.create_instance(
                offer_id=test_offer.id,
                image='pytorch/pytorch:2.0.1-cuda11.7-cudnn8-devel',
                disk=20,
                ssh=True,
                direct=True,
                label='test-june-integration',
                onstart_cmd=startup_script
            )
            
            if result.get('success'):
                instance_id = result.get('new_contract')
                logger.info(f"✅ Instance created: ID {instance_id}")
                self.created_instances.append(instance_id)
                
                # Wait for instance to start
                self._wait_for_instance(instance_id)
                
                return True
            else:
                logger.error(f"❌ Instance creation failed: {result}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Instance creation error: {e}")
            return False
    
    def _wait_for_instance(self, instance_id: int, timeout: int = 300) -> bool:
        """Wait for instance to become ready"""
        logger.info(f"⏳ Waiting for instance {instance_id} to start...")
        
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                instance = self.client.show_instance(instance_id)
                if instance and 'running' in instance.status_msg.lower():
                    logger.info(f"✅ Instance {instance_id} is running")
                    logger.info(f"   SSH: {instance.ssh_host}:{instance.ssh_port}")
                    return True
                else:
                    status = instance.status_msg if instance else "unknown"
                    logger.info(f"   Status: {status}")
                    
            except Exception as e:
                logger.debug(f"Error checking instance status: {e}")
            
            time.sleep(15)
        
        logger.warning(f"⚠️ Instance {instance_id} did not start within {timeout}s")
        return False
    
    def _print_test_summary(self):
        """Print test results summary"""
        logger.info("=" * 60)
        logger.info("📊 TEST SUMMARY")
        logger.info("=" * 60)
        
        total_tests = len(self.test_results)
        passed_tests = sum(1 for result in self.test_results.values() if result)
        
        for test_name, result in self.test_results.items():
            status = "✅ PASSED" if result else "❌ FAILED"
            logger.info(f"{test_name.replace('_', ' ').title()}: {status}")
        
        logger.info("-" * 40)
        logger.info(f"Total: {passed_tests}/{total_tests} tests passed")
        
        if passed_tests == total_tests:
            logger.info("🎉 All tests passed! Integration is working correctly.")
        else:
            logger.warning("⚠️ Some tests failed. Check the logs above for details.")
    
    def cleanup(self):
        """Clean up any created test instances"""
        if self.created_instances:
            logger.info("🧹 Cleaning up test instances...")
            
            for instance_id in self.created_instances:
                try:
                    self.client.destroy_instance(instance_id)
                    logger.info(f"✅ Destroyed test instance {instance_id}")
                except Exception as e:
                    logger.error(f"❌ Failed to destroy instance {instance_id}: {e}")

def main():
    """Main test runner"""
    # Check for required environment variables
    if not os.getenv('VAST_API_KEY'):
        logger.error("❌ VAST_API_KEY environment variable is required")
        logger.info("Please set your API key: export VAST_API_KEY='your_key_here'")
        sys.exit(1)
    
    # Parse arguments
    create_instance = '--create-instance' in sys.argv
    
    if create_instance:
        logger.warning("⚠️ Instance creation test enabled. This will incur charges!")
        response = input("Continue? (y/N): ")
        if response.lower() != 'y':
            logger.info("Test cancelled.")
            sys.exit(0)
    
    # Run tests
    tester = VastIntegrationTester()
    
    try:
        results = tester.run_all_tests(create_instance=create_instance)
        
        # Exit with appropriate code
        all_passed = all(results.values())
        sys.exit(0 if all_passed else 1)
        
    except KeyboardInterrupt:
        logger.info("\n🛑 Tests interrupted by user")
        sys.exit(1)
    
    finally:
        # Always cleanup
        tester.cleanup()

if __name__ == "__main__":
    main()