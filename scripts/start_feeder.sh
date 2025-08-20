#!/usr/bin/env bash
set -euo pipefail
# Cria loopback /dev/video30 se não existir
sudo modprobe -r v4l2loopback || true
sudo modprobe v4l2loopback devices=1 video_nr=30 card_label="rpicam" exclusive_caps=0 max_buffers=64

# Injeta frames da câmera real no /dev/video30
gst-launch-1.0 -v \
  libcamerasrc ! \
  video/x-raw,width=1280,height=720,framerate=30/1,format=NV12 ! \
  videoconvert ! video/x-raw,format=YUY2 ! \
  v4l2sink device=/dev/video30 sync=false io-mode=mmap
