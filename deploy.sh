#!/bin/bash
# Deploy Solana Narrative Radar to DigitalOcean droplet
set -e

SERVER="165.22.76.28"
APP_DIR="/opt/solana-narrative-radar"

echo "📦 Deploying to DigitalOcean..."

# Sync code to server
ssh root@$SERVER "mkdir -p $APP_DIR"
rsync -avz --exclude='.git' --exclude='node_modules' --exclude='__pycache__' --exclude='.env' --exclude='backend/data' \
  ./ root@$SERVER:$APP_DIR/

# Install deps and start on server
ssh root@$SERVER << 'REMOTE'
cd /opt/solana-narrative-radar/backend
pip install -r requirements.txt --break-system-packages -q 2>/dev/null

# Create systemd service
cat > /etc/systemd/system/narrative-radar.service << 'SERVICE'
[Unit]
Description=Solana Narrative Radar
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/solana-narrative-radar/backend
EnvironmentFile=/opt/solana-narrative-radar/backend/.env
ExecStart=/usr/local/bin/uvicorn main:app --host 0.0.0.0 --port 8899
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable narrative-radar
systemctl restart narrative-radar
echo "✅ Service started!"
REMOTE

echo "🚀 Deployed! Access at http://$SERVER:8899"
