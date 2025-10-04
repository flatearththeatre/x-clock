#!/usr/bin/env bash
set -euo pipefail

PREFIX=/usr/local/xclock

MATRIX_LIB_VERSION=59a5e0574ec1528298ad25111a9bbdf2a2fa7a67
HARDWARE_DESC=adafruit-hat-pwm
FONT=VCROSDMono-42

# Install dependencies
apt-get update
apt-get install -y --no-install-recommends \
    git \
    python3-dev \
    python3-venv \
    cython3

# Set up Python virtual environment
mkdir -p $PREFIX
python3 -m venv $PREFIX/venv
source $PREFIX/venv/bin/activate

# Install Python dependencies
pip3 install --no-cache-dir -r requirements.txt

# Install rpi-rgb-led-matrix library
mkdir -p $PREFIX/matrix
curl -sSfL https://github.com/hzeller/rpi-rgb-led-matrix/archive/${MATRIX_LIB_VERSION}.tar.gz | \
    tar xz --strip 1 -C $PREFIX
pushd $PREFIX/matrix
make install-python PYTHON=$(which python3) HARDWARE_DESC=$HARDWARE_DESC
popd

# Blacklist snd_bcm2835
echo "blacklist snd_bcm2835" > /etc/modprobe.d/disable-snd-bcm2835.conf

# Convert and install fonts
python3 font/convert.py
cp -a font $PREFIX/font

# Install xclock application
mkdir -p $PREFIX/bin
cp -a x_clock.py web_controller.py $PREFIX/bin

# Install systemd units
mkdir -p /etc/systemd/system
cat <<EOF >/etc/systemd/system/xclock.service
[Unit]
Description=X Clock Service
After=network.target
After=time-sync.target
StartLimitIntervalSec=0

[Service]
Type=simple
Restart=always
RestartSec=1
User=root
ExecStart=${PREFIX}/venv/bin/python3 ${PREFIX}/bin/x_clock.py --font ${PREFIX}/font/${FONT}.pil

[Install]
WantedBy=multi-user.target
EOF

cat <<EOF >/etc/systemd/system/xclock-web.service
[Unit]
Description=X Clock Controller
After=network.target
After=time-sync.target
StartLimitIntervalSec=0

[Service]
Type=simple
Restart=always
RestartSec=1
User=root
ExecStart=${PREFIX}/venv/bin/python3 ${PREFIX}/bin/web_controller.py --host 0.0.0.0 --port 80

[Install]
WantedBy=multi-user.target
EOF

# Enable services
systemctl daemon-reload
systemctl enable xclock.service
systemctl enable xclock-web.service

echo "Installation complete. You should reboot now."
