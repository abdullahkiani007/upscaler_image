#!/usr/bin/env bash

# Use libtcmalloc for better memory management
TCMALLOC="$(ldconfig -p | grep -Po "libtcmalloc.so.\d" | head -n 1)"
export LD_PRELOAD="${TCMALLOC}"

set -e

# Add a condition here to check if comfyui is available or next command will fail

echo "runpod-worker-comfy: Starting RunPod Handler"
python3 -u /rp_handler.py