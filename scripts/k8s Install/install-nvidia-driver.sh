# Update package list
apt update

# Install NVIDIA drivers
apt install -y nvidia-driver-535

# Or for latest:
apt install -y ubuntu-drivers-common
ubuntu-drivers devices
ubuntu-drivers autoinstall

# Reboot required after driver installation
reboot