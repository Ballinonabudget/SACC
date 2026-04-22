import os
import json
import time
import google.generativeai as genai
from dotenv import load_dotenv

# Load environment logic
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))
api_key = os.getenv("GEMINI_API_KEY")

if api_key:
    genai.configure(api_key=api_key)

def analyze_sneaker_video(video_path):
    """
    Uploads a sneaker video to Gemini, waits for active state,
    and prompts it to identify the model and extract the SKU/Size/Price.
    Returns a dictionary of parsed JSON.
    """
    if not api_key:
        return {"error": "GEMINI_API_KEY not set"}

    try:
        print(f"Uploading {video_path} to Gemini...")
        video_file = genai.upload_file(path=video_path)
        
        # Wait for file processing to complete
        while video_file.state.name == "PROCESSING":
            print('.', end='', flush=True)
            time.sleep(2)
            video_file = genai.get_file(video_file.name)
        
        if video_file.state.name == "FAILED":
            raise ValueError("Video processing failed.")

        print(f"\nProcessing complete for {video_path}. Analyzing...")

        # Initialize the chosen model
        model = genai.GenerativeModel(model_name="models/gemini-2.5-pro")

        prompt = """
        Watch this short video clip of a sneaker. 
        Extract and output a strictly formatted JSON payload with the following fields: 
        Model Name, Size, Price, and SKU (Style Code) of the shoe shown.
        Base your extraction purely on the visual details shown. 
        Only return the JSON. No markdown blocking.
        Example: 
        { "Model": "Air Jordan 1 High OG Chicago", "Size": "10.5", "Price": "$180", "SKU": "555088-101" }
        """

        response = model.generate_content([video_file, prompt], request_options={"timeout": 60})
        
        # Clean the response to ensure plain JSON
        response_text = response.text.replace("```json", "").replace("```", "").strip()
        parsed_data = json.loads(response_text)
        
        # Clean up file from Gemini to save space
        genai.delete_file(video_file.name)
        
        return parsed_data

    except Exception as e:
        print(f"Error during video analysis: {e}")
        return {"error": str(e)}

if __name__ == "__main__":
    # Test execution block
    print("Gemini Pipeline initialized.")
