import runpod
from runpod.serverless.utils import rp_upload
from comfy_runner.inf import ComfyRunner
import json
import urllib.request
import urllib.parse
import time
import os
import requests
import base64
from io import BytesIO
import zipfile

# Time to wait between API check attempts in milliseconds
COMFY_API_AVAILABLE_INTERVAL_MS = 50
# Maximum number of API check attempts
COMFY_API_AVAILABLE_MAX_RETRIES = 500
# Time to wait between poll attempts in milliseconds
COMFY_POLLING_INTERVAL_MS = int(os.environ.get("COMFY_POLLING_INTERVAL_MS", 250))
# Maximum number of poll attempts
COMFY_POLLING_MAX_RETRIES = int(os.environ.get("COMFY_POLLING_MAX_RETRIES", 500))
# Host where ComfyUI is running
COMFY_HOST = "127.0.0.1:4333"
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
    # Validate if job_input is provided
    if job_input is None:
        return None, "Please provide input"

    # Check if input is a string and try to parse it as JSON
    if isinstance(job_input, str):
        try:
            job_input = json.loads(job_input)
        except json.JSONDecodeError:
            return None, "Invalid JSON format in input"

    # Validate 'workflow' in input
    workflow = job_input.get("workflow")
    if workflow is None:
        return None, "Missing 'workflow' parameter"
    uid = job_input.get("uid")
    customModels = job_input.get("customModels")    #customModels will be an array containing dicts of the following format {filename:,url:,dest:}
    customNodes = job_input.get("customNodes")
    images = job_input.get("images")
    # Return validated data and no error
    return {"uid": uid ,"workflow": workflow, "images": images,"customModels":customModels,"customNodes":customNodes}, None


def check_server(url, retries=500, delay=50):
    """
    Check if a server is reachable via HTTP GET request

    Args:
    - url (str): The URL to check
    - retries (int, optional): The number of times to attempt connecting to the server. Default is 50
    - delay (int, optional): The time in milliseconds to wait between retries. Default is 500

    Returns:
    bool: True if the server is reachable within the given number of retries, otherwise False
    """

    for i in range(retries):
        try:
            response = requests.get(url)

            # If the response status code is 200, the server is up and running
            if response.status_code == 200:
                print(f"runpod-worker-comfy - API is reachable")
                return True
        except requests.RequestException as e:
            # If an exception occurs, the server may not be ready
            pass

        # Wait for the specified delay before retrying
        time.sleep(delay / 1000)

    print(
        f"runpod-worker-comfy - Failed to connect to server at {url} after {retries} attempts."
    )
    return False


def upload_images(images):
    """
    Upload a list of base64 encoded images to the ComfyUI server using the /upload/image endpoint.

    Args:
        images (list): A list of dictionaries, each containing the 'name' of the image and the 'image' as a base64 encoded string.
        server_address (str): The address of the ComfyUI server.

    Returns:
        list: A list of responses from the server for each image upload.
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

        # Prepare the form data
        files = {
            "image": (name, BytesIO(blob), "image/png"),
            "overwrite": (None, "true"),
        }

        # POST request to upload the image
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


def queue_workflow(workflow,customModels,customNodes,images):
    """
    Queue a workflow to be processed by ComfyUI and load any custom models(if any)

    Args:
        workflow (dict): A dictionary containing the workflow to be processed
        customModels (array): An array containing the dicts of the models filename, url and dest
        customNodes (array): An array containing the dicts of the node names and urls
        images : A s3 url of the zip folder of the images [optional]

    Returns:
        dict: The JSON response from ComfyUI after processing the workflow
    """

    filePathList = []
    if images is not None:
        s3_url = images
        # Download the ZIP file from S3
        with urllib.request.urlopen(s3_url) as response:
            with open("images.zip", "wb") as f:
                f.write(response.read())

        # Set your desired extraction folder
        extraction_folder = "./images"
        os.makedirs(extraction_folder, exist_ok=True)

        # Extract the ZIP file into the desired folder
        with zipfile.ZipFile("images.zip", "r") as zip_ref:
            zip_ref.extractall(extraction_folder)
        os.remove("images.zip")

        # Build a list of file paths for the extracted images
        filePathList = [os.path.join(extraction_folder, filename)
                        for filename in os.listdir(extraction_folder)
                        if os.path.isfile(os.path.join(extraction_folder, filename))]

        print("the files path list in the rp_handler",filePathList)
    # Store the workflow in a file
    with open("workflow.json", "w") as f:
        json.dump(workflow, f)
    runner = ComfyRunner()
    output = runner.predict(
        workflow_input="workflow.json",
        extra_models_list = customModels,
        extra_node_urls = customNodes,
        file_path_list=filePathList,
        stop_server_after_completion=True,
    )

    return output


def get_history(prompt_id):
    """
    Retrieve the history of a given prompt using its ID

    Args:
        prompt_id (str): The ID of the prompt whose history is to be retrieved

    Returns:
        dict: The history of the prompt, containing all the processing steps and results
    """
    with urllib.request.urlopen(f"http://{COMFY_HOST}/history/{prompt_id}") as response:
        return json.loads(response.read())


def base64_encode(img_path):
    """
    Returns base64 encoded image.

    Args:
        img_path (str): The path to the image

    Returns:
        str: The base64 encoded image
    """
    with open(img_path, "rb") as image_file:
        encoded_string = base64.b64encode(image_file.read()).decode("utf-8")
        return f"{encoded_string}"


def process_output_images(queued_workflow, job_id):
    """
    Processes multiple output images from the workflow result.

    Args:
        queued_workflow (dict): The output from queue_workflow containing file paths
        job_id (str): The unique identifier for the job

    Returns:
        dict: A dictionary containing status and list of processed images with their data and file types
    """
    COMFY_OUTPUT_PATH = os.environ.get("COMFY_OUTPUT_PATH", "/output")
    processed_images = []

    # Extract file paths from the workflow output
    file_paths = queued_workflow.get('file_paths', [])

    for file_path in file_paths:
        full_path = os.path.join(COMFY_OUTPUT_PATH, file_path)

        if os.path.exists(full_path):
            # Determine file type from extension
            file_type = os.path.splitext(file_path)[1].lower().replace('.', '')

            if os.environ.get("BUCKET_ENDPOINT_URL", False) and os.environ.get("BUCKET_ACCESS_KEY_ID", False) and os.environ.get("BUCKET_SECRET_ACCESS_KEY", False) :
                # Upload to S3 and get URL
                try:
                    image_data = rp_upload.upload_image(job_id, full_path)
                    image_format = "url"
                except Exception as e:
                    print(f"Error uploading image to S3: {str(e)}")
                    image_data = base64_encode(full_path)
                    image_format = "base64"
            else:
                # Convert to base64
                print("S3 Environment Variables are not set, sending image as base64")
                image_data = base64_encode(full_path)
                image_format = "base64"

            processed_images.append({
                "data": image_data,
                "file_type": file_type,
                "format": image_format
            })
        else:
            print(f"runpod-worker-comfy - image not found: {full_path}")

    if not processed_images:
        return {
            "status": "error",
            "message": "No images were successfully processed"
        }

    return {
        "status": "success",
        "images": processed_images
    }


def handler(job):
    """
    The main function that handles a job of generating an image.

    This function validates the input, sends a prompt to ComfyUI for processing,
    polls ComfyUI for result, and retrieves generated images.

    Args:
        job (dict): A dictionary containing job details and input parameters.

    Returns:
        dict: A dictionary containing either an error message or a success status with generated images.
    """
    job_input = job["input"]
    # Make sure that the input is valid
    validated_data, error_message = validate_input(job_input)
    if error_message:
        return {"error": error_message}

    # Extract validated data
    workflow = validated_data["workflow"]

    images = validated_data.get("images")
    customModels = validated_data["customModels"]
    customNodes =  validated_data["customNodes"]
    try:
        queued_workflow = queue_workflow(workflow,customModels,customNodes,images)
        result = process_output_images(queued_workflow, job["id"])
        result["refresh_worker"] = REFRESH_WORKER
    except Exception as e:
        return {"error": f"Error queuing workflow: {str(e)}"}

    return result


# Start the handler only if this script is run directly
if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})