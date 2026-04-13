# ============================================================
# test_gemini.py
# PURPOSE: Just a test file to check Gemini API is working.
# This was our very first file — not part of the actual project.
# Run it to verify your API key and library are set up correctly.
# ============================================================

# os = built-in Python library to read environment variables
import os

# genai = Google's official Python library to talk to Gemini AI
from google import genai

# load_dotenv = reads your .env file and loads the keys into memory
from dotenv import load_dotenv

# This line actually reads the .env file
# After this runs, os.getenv("GEMINI_API_KEY") will work
load_dotenv()

# Create a "client" — think of this as logging into Gemini with your API key
# os.getenv("GEMINI_API_KEY") reads the key from .env — never hardcoded here
# If this line fails, your API key is wrong or .env is not set up correctly
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# Send a message to Gemini and wait for a reply
# model = which AI model to use (gemini-2.0-flash is free and fast)
# contents = the actual message you're sending to Gemini
response = client.models.generate_content(
    model="gemini-2.5-flash",  # free tier model — works without paying
    contents="Say hello and tell me you are ready to review code"
)

# response is the full reply object from Gemini
# .text extracts just the text part from it
# like opening a parcel and taking out only the letter inside
print(response.text)