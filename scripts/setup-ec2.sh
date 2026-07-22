#!/bin/bash
# EC2 t2.micro setup script
# Run this once after launching your EC2 instance
# AMI: Ubuntu 22.04 LTS

set -e

echo "=== Installing k3s ==="
curl -sfL https://get.k3s.io | sh -

echo "=== Waiting for k3s to be ready ==="
sleep 15
sudo k3s kubectl get nodes

echo "=== Installing Docker ==="
sudo apt-get update -q
sudo apt-get install -y docker.io
sudo usermod -aG docker $USER

echo "=== Done ==="
echo "Next steps:"
echo "  1. Copy your project to EC2: scp -r . ubuntu@<ec2-ip>:~/driftguard"
echo "  2. Build image: docker build -t driftguard:latest ."
echo "  3. Import to k3s: docker save driftguard:latest | sudo k3s ctr images import -"
echo "  4. Deploy: sudo k3s kubectl apply -f k8s/"
echo "  5. Check: sudo k3s kubectl get pods -n driftguard"
