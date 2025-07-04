MODEL_DIR=/runpod-volume/comfyui/models/
mkdir -p $MODEL_DIR
chmod -R 777 /runpod-volume/comfyui/models
# https://huggingface.co/realung/flux1-dev.safetensors/resolve/main/flux1-dev.safetensors
if [ ! -f "$MODEL_DIR/unet/flux/flux1-dev.safetensors" ]; then
    wget -c $1 -P "$MODEL_DIR/unet/flux/"
fi

# if [ ! -f "$MODEL_DIR/loras/flux_tools/42lux-UltimateAtHome-flux-highresfix.safetensors" ]; then
#     wget -c https://huggingface.co/okaris/flux-hires/resolve/618a72cc96bedf98f86837f28810cd73276753d9/42lux-UltimateAtHome-flux-highresfix.safetensors  -P "$MODEL_DIR/loras/flux_tools/"
# fi

if [ ! -f "$MODEL_DIR/upscale_models/4xNomos8kHAT-L_otf.safetensors" ]; then
    wget -c https://huggingface.co/Phips/4xNomos8kHAT-L_otf/resolve/main/4xNomos8kHAT-L_otf.safetensors -P "$MODEL_DIR/upscale_models/"
fi

if [ ! -f "$MODEL_DIR/clip/t5xxl_fp16.safetensors" ]; then
    wget -c https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp16.safetensors -P "$MODEL_DIR/clip/"
fi

if [ ! -f "$MODEL_DIR/clip/clip_l.safetensors" ]; then
    wget -c https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors -P "$MODEL_DIR/clip/"
fi

if [ ! -f "$MODEL_DIR/vae/FLUX1/ae.safetensors" ]; then
    wget -c https://huggingface.co/black-forest-labs/FLUX.1-schnell/resolve/main/ae.safetensors -P "$MODEL_DIR/vae/FLUX1/"
fi

echo "runpod-worker-comfy: Starting ComfyUI"
python3 ./comfyui/main.py --disable-auto-launch --disable-metadata --listen &