import runpod
from runpod.serverless.utils import rp_upload
import json
import urllib.request
import urllib.parse
import time
import os
import requests
import base64
from io import BytesIO
import zipfile
import tempfile

# Time to wait between API check attempts in milliseconds
COMFY_API_AVAILABLE_INTERVAL_MS = 50
# Maximum number of API check attempts
COMFY_API_AVAILABLE_MAX_RETRIES = 500
# Time to wait between poll attempts in milliseconds
COMFY_POLLING_INTERVAL_MS = int(
    os.environ.get("COMFY_POLLING_INTERVAL_MS", 250))
# Maximum number of poll attempts
COMFY_POLLING_MAX_RETRIES = int(
    os.environ.get("COMFY_POLLING_MAX_RETRIES", 500))
# Host where ComfyUI is running
COMFY_HOST = "127.0.0.1:8188"
# Enforce a clean state after each job is done
# see https://docs.runpod.io/docs/handler-additional-controls#refresh-worker
REFRESH_WORKER = os.environ.get("REFRESH_WORKER", "false").lower() == "true"

def validate_input(job_input):
    """
    Validates the input for the handler function.

    Args:
        job_input (dict): The input data to validate.

    Returns:
        tuple: A tuple containing the validated data and an error message, if any.
               The structure is (validated_data, error_message).
    """
    if job_input is None:
        return None, "Please provide input"

    if isinstance(job_input, str):
        try:
            job_input = json.loads(job_input)
        except json.JSONDecodeError:
            return None, "Invalid JSON format in input"

    workflow = job_input.get("workflow")
    if workflow is None:
        return None, "Missing 'workflow' parameter"

    images = job_input.get("images")
    if images is not None:
        if not isinstance(images, list) or not all(
            "name" in image and "image" in image for image in images
        ):
            return (
                None,
                "'images' must be a list of objects with 'name' and 'image' keys",
            )
    image_zip_url = job_input.get("image_zip_url")
    if image_zip_url and not isinstance(image_zip_url, str):
        return None, "'image_zip_url' must be a string"
    uid = job_input.get("uid")
    return {"uid": uid, "workflow": workflow, "images": images, "image_zip_url": image_zip_url}, None

def check_server(url, retries=500, delay=50):
    """
    Check if a server is reachable via HTTP GET request
    """
    for i in range(retries):
        try:
            response = requests.get(url)
            if response.status_code == 200:
                print(f"runpod-worker-comfy - API is reachable")
                return True
        except requests.RequestException:
            pass
        time.sleep(delay / 1000)
    print(f"runpod-worker-comfy - Failed to connect to server at {url} after {retries} attempts.")
    return False

def download_and_extract_images(zip_url):
    """
    Download the ZIP file from the specified URL and extract images to a temporary directory.

    Args:
        zip_url (str): The URL of the ZIP file containing images.

    Returns:
        list: A list of dictionaries containing 'name' and 'image' (base64-encoded) for each image.
    """
    if not zip_url:
        return []

    print(f"runpod-worker-comfy - Downloading ZIP from {zip_url}")
    try:
        with urllib.request.urlopen(zip_url) as response:
            with tempfile.TemporaryDirectory() as temp_dir:
                zip_path = os.path.join(temp_dir, "images.zip")
                with open(zip_path, "wb") as zip_file:
                    zip_file.write(response.read())

                print(f"runpod-worker-comfy - Extracting ZIP to {temp_dir}")
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(temp_dir)

                images = []
                for file_name in os.listdir(temp_dir):
                    if file_name.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                        file_path = os.path.join(temp_dir, file_name)
                        with open(file_path, "rb") as image_file:
                            base64_image = base64.b64encode(image_file.read()).decode("utf-8")
                            images.append({"name": file_name, "image": base64_image})

                print(f"runpod-worker-comfy - Extracted {len(images)} images")
                return images
    except Exception as e:
        print(f"runpod-worker-comfy - Error downloading or extracting ZIP: {str(e)}")
        return []

def upload_images(images):
    """
    Upload a list of base64 encoded images to the ComfyUI server using the /upload/image endpoint.
    """
    if not images:
        return {"status": "success", "message": "No images to upload", "details": []}

    responses = []
    upload_errors = []
    print(f"runpod-worker-comfy - image(s) upload")

    for image in images:
        name = image["name"]
        image_data = image["image"]
        blob = base64.b64decode(image_data)
        files = {
            "image": (name, BytesIO(blob), "image/png"),
            "overwrite": (None, "true"),
        }
        response = requests.post(f"http://{COMFY_HOST}/upload/image", files=files)
        if response.status_code != 200:
            upload_errors.append(f"Error uploading {name}: {response.text}")
        else:
            responses.append(f"Successfully uploaded {name}")

    if upload_errors:
        print(f"runpod-worker-comfy - image(s) upload with errors")
        return {
            "status": "error",
            "message": "Some images failed to upload",
            "details": upload_errors,
        }

    print(f"runpod-worker-comfy - image(s) upload complete")
    return {
        "status": "success",
        "message": "All images uploaded successfully",
        "details": responses,
    }

def queue_workflow(workflow):
    """
    Queue a workflow to be processed by ComfyUI
    """
    data = json.dumps({"prompt": workflow}).encode("utf-8")
    req = urllib.request.Request(f"http://{COMFY_HOST}/prompt", data=data)
    return json.loads(urllib.request.urlopen(req).read())

def get_history(prompt_id):
    """
    Retrieve the history of a given prompt using its ID
    """
    with urllib.request.urlopen(f"http://{COMFY_HOST}/history/{prompt_id}") as response:
        return json.loads(response.read())

def base64_encode(img_path):
    """
    Returns base64 encoded image.
    """
    with open(img_path, "rb") as image_file:
        encoded_string = base64.b64encode(image_file.read()).decode("utf-8")
        return f"{encoded_string}"

def process_output_images(outputs, job_id):
    """
    Process and return generated images as URL or base64.
    """
    COMFY_OUTPUT_PATH = os.environ.get("COMFY_OUTPUT_PATH", "/ComfyUI/output")
    output_images = {}

    for node_id, node_output in outputs.items():
        if "images" in node_output:
            for image in node_output["images"]:
                output_images = os.path.join(image["subfolder"], image["filename"])

    local_image_path = f"{COMFY_OUTPUT_PATH}/{output_images}"
    print(f"runpod-worker-comfy - {local_image_path}")

    if os.path.exists(local_image_path):
        if os.environ.get("BUCKET_ENDPOINT_URL", False):
            image = rp_upload.upload_image(job_id, local_image_path)
            print("runpod-worker-comfy - the image was generated and uploaded to AWS S3")
        else:
            image = base64_encode(local_image_path)
            print("runpod-worker-comfy - the image was generated and converted to base64")
        return {
            "status": "success",
            "message": image,
        }
    else:
        print("runpod-worker-comfy - the image does not exist in the output folder")
        return {
            "status": "error",
            "message": f"the image does not exist in the specified output folder: {local_image_path}",
        }

def handler(job):
    """
    The main function that handles a job of generating an image.
    """
    print(f"runpod-worker-comfy - received job: {job}")
    print("Executing runpod-worker-comfy handler")

    job_input = job["input"]
    print(f"runpod-worker-comfy - job input: {job_input}")

    validated_data, error_message = validate_input(job_input)
    if error_message:
        print(f"runpod-worker-comfy - input validation failed: {error_message}")
        return {"error": error_message}

    workflow = validated_data["workflow"]
    print(f"runpod-worker-comfy - workflow: {workflow}")
    images = validated_data.get("images")
    print(f"runpod-worker-comfy - images: {images}")
    UID = validated_data.get("uid")
    image_zip_url = validated_data.get("image_zip_url")
    BUCKET_NAME = os.getenv('BUCKET_NAME')
    OBJECT_KEY = os.getenv('OBJECT_KEY')

    # Download models
    print(f"runpod-worker-comfy - downloading models")
    os.system("chmod +x download_model.sh")
    os.system(f"./download_model.sh")

    # Download and extract images from ZIP if URL is provided
    downloaded_images = download_and_extract_images(image_zip_url) if image_zip_url else []
    if image_zip_url and not downloaded_images:
        return {"error": "Failed to download or extract images from the provided URL"}

    # Merge downloaded images with any provided images
    if images:
        images.extend(downloaded_images)
    else:
        images = downloaded_images

    # Make sure that the ComfyUI API is available
    check_server(f"http://{COMFY_HOST}", COMFY_API_AVAILABLE_MAX_RETRIES, COMFY_API_AVAILABLE_INTERVAL_MS)

    # Upload images
    print("images", images)
    upload_result = upload_images(images)
    if upload_result["status"] == "error":
        return upload_result

    # Queue the workflow
    try:
        print(f"runpod-worker-comfy - queueing workflow")
        queued_workflow = queue_workflow(workflow)
        prompt_id = queued_workflow["prompt_id"]
        print(f"runpod-worker-comfy - queued workflow with ID {prompt_id}")
    except Exception as e:
        return {"error": f"Error queuing workflow: {str(e)}"}

    # Poll for completion
    print(f"runpod-worker-comfy - wait until image generation is complete")
    retries = 0
    try:
        while True:
            history = get_history(prompt_id)
            if prompt_id in history and history[prompt_id].get("outputs"):
                break
            time.sleep(COMFY_POLLING_INTERVAL_MS / 1000)
            retries += 1
            if retries > COMFY_POLLING_MAX_RETRIES:
                return {"error": "Max retries reached while waiting for image generation"}
    except Exception as e:
        return {"error": f"Error waiting for image generation: {str(e)}"}

    # Get the generated image and return it
    images_result = process_output_images(history[prompt_id].get("outputs"), job["id"])
    result = {**images_result, "refresh_worker": REFRESH_WORKER}
    return result

if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})