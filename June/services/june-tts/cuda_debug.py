import torch
import os
import subprocess

print("🔍 CUDA Debug Report")
print("=" * 50)

# Basic CUDA info
print(f"PyTorch version: {torch.__version__}")
print(f"CUDA available: {torch.cuda.is_available()}")

if torch.cuda.is_available():
    print(f"CUDA version: {torch.version.cuda}")
    print(f"cuDNN version: {torch.backends.cudnn.version()}")
    print(f"Device count: {torch.cuda.device_count()}")
    print(f"Current device: {torch.cuda.current_device()}")
    print(f"Device name: {torch.cuda.get_device_name(0)}")
    print(f"Device properties: {torch.cuda.get_device_properties(0)}")
    
    # Memory info
    memory_info = torch.cuda.mem_get_info(0)
    print(f"Free memory: {memory_info[0] / 1024**3:.2f} GB")
    print(f"Total memory: {memory_info[1] / 1024**3:.2f} GB")
    
    # Test CUDA context creation
    print("\n🧪 Testing CUDA context creation...")
    try:
        # Enable detailed debug
        os.environ['CUDA_LAUNCH_BLOCKING'] = '1'
        os.environ['TORCH_USE_CUDA_DSA'] = '1'
        
        # Simple test
        x = torch.tensor([1.0], device='cuda')
        y = x + 1
        print(f"✅ Basic CUDA test: {y}")
        
        # Memory allocation test
        large_tensor = torch.zeros(1000, 1000, device='cuda')
        print("✅ Large tensor allocation successful")
        del large_tensor
        torch.cuda.empty_cache()
        
    except Exception as e:
        print(f"❌ CUDA test failed: {e}")
        print(f"Exception type: {type(e).__name__}")
        
        # Get more detailed error info
        import traceback
        traceback.print_exc()

# Environment variables
print("\n🌍 Environment Variables:")
cuda_vars = ['CUDA_VISIBLE_DEVICES', 'CUDA_LAUNCH_BLOCKING', 'PYTORCH_CUDA_ALLOC_CONF']
for var in cuda_vars:
    print(f"{var}: {os.environ.get(var, 'Not set')}")

# Check processes using GPU
print("\n🔍 GPU Process Check:")
try:
    result = subprocess.run(['nvidia-smi', '-q'], capture_output=True, text=True)
    if "No running processes found" in result.stdout:
        print("✅ No processes using GPU")
    else:
        print("⚠️  Processes found using GPU")
        # Extract process info
        lines = result.stdout.split('\n')
        for i, line in enumerate(lines):
            if "Process ID" in line:
                print(f"   Process: {lines[i:i+3]}")
except:
    print("❌ Could not check GPU processes")

# Driver/Runtime versions
print("\n🚗 Driver Info:")
try:
    result = subprocess.run(['nvidia-smi', '--query-gpu=driver_version,cuda_version', '--format=csv'], 
                          capture_output=True, text=True)
    print(result.stdout)
except:
    print("❌ Could not get driver info")
