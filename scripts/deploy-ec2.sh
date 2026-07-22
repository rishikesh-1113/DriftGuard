#!/bin/bash
# Run this ONCE on a fresh EC2 instance
# Usage: bash deploy-ec2.sh
set -e

echo "=== Step 1: Swap ==="
if [ ! -f /swapfile ]; then
  sudo fallocate -l 2G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
fi
free -h

echo "=== Step 2: Docker ==="
if ! command -v docker &> /dev/null; then
  sudo apt-get update -y
  sudo apt-get install -y docker.io
  sudo systemctl enable docker
  sudo systemctl start docker
  sudo usermod -aG docker ubuntu
fi
docker --version

echo "=== Step 3: k3s ==="
if ! command -v k3s &> /dev/null; then
  curl -sfL https://get.k3s.io | sh -
  sleep 10
fi
sudo k3s kubectl get nodes

echo "=== Step 4: Build Docker image ==="
cd ~/driftguard-app
sudo docker build -t driftguard:latest .

echo "=== Step 5: Import into k3s ==="
sudo docker save driftguard:latest | sudo k3s ctr images import -

echo "=== Step 6: Deploy ==="
sudo k3s kubectl apply -f k8s/namespace.yaml
sudo k3s kubectl apply -f k8s/rbac.yaml
sudo k3s kubectl apply -f k8s/deployment.yaml
sudo k3s kubectl apply -f k8s/service.yaml

echo "=== Done! Waiting for pod... ==="
sudo k3s kubectl rollout status deployment/driftguard -n driftguard --timeout=120s
sudo k3s kubectl get pods -n driftguard
