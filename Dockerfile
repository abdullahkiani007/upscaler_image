# start from a clean base image (replace <version> with the desired release)
FROM runpod/worker-comfyui:5.1.1-base

# install custom nodes using comfy-cli
RUN comfy-node-install ComfyUI_LayerStyle WAS_Node_Suite_Revised

#trigger