# ============================================================
# diff_reviewer.py
# PURPOSE: Practice file — tests reviewing a FAKE git diff.
# This taught us what a git diff looks like and how to tell
# Gemini to only review the + lines (newly added code).
# Not part of final project — the logic lives in main.py now.
# ============================================================

import os
from google import genai
from dotenv import load_dotenv

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# This is a FAKE git diff we made up to practice with.
# In a real GitHub PR, this exact format is what GitHub gives us.
# --- a/file = the OLD version of the file
# +++ b/file = the NEW version of the file
# Lines starting with + = newly ADDED code (what we review)
# Lines starting with - = removed code (we ignore these)
# @@ -1,5 +1,10 @@ = tells us which line numbers changed (ignore for now)
sample_diff = """
--- a/calculator.py
+++ b/calculator.py
@@ -1,5 +1,10 @@
+def divide(a, b):
+    result = a / b   # BUG: no check if b is zero — will crash
+    return result
+
+def get_user_input():
+    age = input("Enter your age: ")   # input() returns a STRING not a number
+    if age > 18:                      # BUG: comparing string to int = TypeError
+        print("Adult")
"""

# f-string prompt — the f means variables inside {} get replaced with real values
# {sample_diff} gets replaced with the actual diff text above
# This is called "prompt engineering" — we give Gemini:
#   1. A role ("you are a senior developer")
#   2. The data to review (the diff)
#   3. Exact output format (BUG/ISSUE 1, Line, Issue, Fix)
# Without the format instruction, Gemini gives random inconsistent replies
prompt = f"""
You are a senior Python developer reviewing a pull request.
Below is the git diff showing what code was added (lines starting with +):

{sample_diff}

Review ONLY the added lines (starting with +).
Find all bugs, issues, or bad practices.

For each issue reply in this format:
BUG/ISSUE 1:
- Line: (what line)
- Issue: (what is wrong)
- Fix: (corrected code)

If no issues found, reply: LGTM (Looks Good To Me)
"""

# Send the prompt to Gemini and get back a review
# Every time sample_diff changes, Gemini sees different code = unique review
response = client.models.generate_content(
    model="gemini-2.5-flash",  # free tier model
    contents=prompt             # the full prompt with diff injected
)

# Print Gemini's reply — should show BUG/ISSUE format we asked for
print(response.text)