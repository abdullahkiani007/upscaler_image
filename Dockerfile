# Stage 1: Base image with common dependencies
FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04 as base

# Prevents prompts from packages asking for user input during installation
ENV DEBIAN_FRONTEND=noninteractive
# Prefer binary wheels over source distributions for faster pip installations
ENV PIP_PREFER_BINARY=1
# Ensures output from python is printed immediately to the terminal without buffering
ENV PYTHONUNBUFFERED=1
# Speed up some cmake builds
ENV CMAKE_BUILD_PARALLEL_LEVEL=8

# Install Python, git and other necessary tools
RUN apt-get update && apt-get install -y \
    python3.10 \
    python3-pip \
    git \
    wget \
    libgl1 \
    libglib2.0-0 \
    && ln -sf /usr/bin/python3.10 /usr/bin/python \
    && ln -sf /usr/bin/pip3 /usr/bin/pip

# Clean up to reduce image size
RUN apt-get autoremove -y && apt-get clean -y && rm -rf /var/lib/apt/lists/*

# Install comfy-cli
RUN pip install comfy-cli

# Install ComfyUI
RUN /usr/bin/yes | comfy --workspace /ComfyUI install --cuda-version 11.8 --nvidia

RUN comfy update all

EXPOSE 8188

WORKDIR /ComfyUI

# Install requirements
RUN pip install runpod requests opencv-python-headless
RUN pip install -r requirements.txt

# WORKDIR /workspace
ADD src/extra_model_paths.yaml ./

WORKDIR /

# RUN comfy node install --mode remote https://github.com/lodestone-rock/ComfyUI_FluxMod.git
# RUN comfy node install --mode remote https://github.com/logtd/ComfyUI-Fluxtapoz
# RUN comfy node install --mode remote https://github.com/42lux/ComfyUI-42lux.git
# RUN comfy node install --mode remote https://github.com/Jonseed/ComfyUI-Detail-Daemon.git
# RUN comfy node install --mode remote https://github.com/ltdrdata/ComfyUI-Inspire-Pack
# RUN comfy node install --mode remote https://github.com/pamparamm/ComfyUI-ppm
RUN comfy node install --mode remote https://github.com/ltdrdata/ComfyUI-Manager.git
RUN echo "current directory is " && pwd && echo "directories" && ls && cd /ComfyUI/custom_nodes
RUN echo "clonning wav speed " && ls && git clone https://github.com/chengzeyi/Comfy-WaveSpeed.git
RUN cd /ComfyUI
# Add scripts
ADD src/start.sh src/download_model.sh src/restore_snapshot.sh src/rp_handler.py src/snapshot.json test_input.json ./
RUN chmod +x /start.sh /restore_snapshot.sh

# Restore the snapshot to install custom nodes
RUN /restore_snapshot.sh

# # Start container
CMD ["/start.sh"]