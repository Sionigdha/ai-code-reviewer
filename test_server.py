# ============================================================
# test_server.py
# PURPOSE: A testing tool to simulate GitHub sending a webhook
# to our FastAPI server — without needing a real GitHub PR event.
# Run this while main.py server is running (uvicorn main:app --reload)
# to test the full pipeline manually from your laptop.
# This is exactly what GitHub does automatically in production.
# ============================================================

# requests = Python library to send HTTP requests from code
# like a browser but for Python scripts
import requests

# This is a FAKE webhook payload that mimics exactly what
# GitHub sends to our server when a PR is opened.
# In production, GitHub builds this automatically — we're
# building it manually here just to test our server works.
# "action": "opened" = tells our server a new PR was opened
# "full_name" = which repo the PR is in
# "number" = which PR number to review
payload = {
    "action": "opened",           # triggers our review logic in main.py
    "repository": {
        "full_name": "django/django"  # real public repo we're testing on
    },
    "pull_request": {
        "number": 18745           # real PR number in django/django
    }
}

# Send an HTTP POST request to our locally running FastAPI server
# http://127.0.0.1:8000 = our server running on this laptop
# /review = the endpoint in main.py decorated with @app.post("/review")
# json=payload = sends our fake payload as JSON in the request body
# This is IDENTICAL to what GitHub sends — just done manually by us
response = requests.post(
    "http://127.0.0.1:8000/review",
    json=payload
)

# Print the HTTP status code
# 200 = success, server processed it correctly
# 422 = bad request, payload format was wrong
# 500 = server crashed while processing
print("Status code:", response.status_code)

# Print the raw response text from the server
# Should show: {"status": "review posted", "pr": 18745}
# if everything worked correctly
print("Response text:", response.text)