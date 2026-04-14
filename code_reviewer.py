# ============================================================
# code_reviewer.py
# PURPOSE: Practice file — our second ever file.
# Tests sending HARDCODED buggy Python code to Gemini for review.
# This is where we learned prompt engineering — forcing Gemini
# to always reply in a structured BUG / Line / Issue / Fix format.
# Not part of final project — the logic lives in main.py now.
# ============================================================

import os
from google import genai
from dotenv import load_dotenv

load_dotenv()

# Connect to Gemini using API key from .env
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# This is fake buggy code we wrote ourselves just to test Gemini.
# In the real project, this gets replaced by the actual git diff
# from a real GitHub PR — but here we're hardcoding it to practice.
# 
# BUG 1 (line 6): no check for empty list — divide by zero crash
# BUG 2 (line 9): "Average is: " + result — can't add string + float
# These are the 2 bugs Gemini should catch.
buggy_code = """
def calculate_average(numbers):
    total = 0
    for num in numbers:
        total = total + num
    average = total / len(numbers)  # BUG: crashes if numbers = []
    return average

result = calculate_average([10, 20, 30])
print("Average is: " + result)  # BUG: can't add string + float
"""

# This is the prompt — our instruction to Gemini.
# It uses an f-string so {buggy_code} gets replaced with
# the actual code above when Python runs this line.
#
# Good prompt engineering has 3 parts:
#   1. ROLE: "You are a senior Python developer" 
#      — tells Gemini how to behave and what expertise to use
#   2. DATA: the actual code to review (injected via f-string)
#   3. FORMAT: exact template to follow for every bug found
#      — without this, Gemini gives different formats every time
#      — with this, we always get predictable structured output
prompt = f"""
You are a senior Python developer doing a code review.
Analyze this code and find all bugs:

{buggy_code}

Reply in this EXACT format for each bug:
BUG 1:
- Line: (line number)
- Issue: (what is wrong)
- Fix: (corrected code)

BUG 2:
- Line: (line number)
- Issue: (what is wrong)
- Fix: (corrected code)

If no bugs found, reply: NO BUGS FOUND
"""

# Send the prompt to Gemini and wait for reply
# The prompt contains the buggy code injected via f-string
# Gemini reads it and returns bugs in our requested format
response = client.models.generate_content(
    model="gemini-2.5-flash",  # free tier — change 2.5 to 
    contents=prompt
)

# Print what Gemini found
# Should show BUG 1 and BUG 2 in the exact format we asked for
print(response.text)