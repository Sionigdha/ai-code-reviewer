# ============================================================
# real_pr_reviewer.py
# PURPOSE: Practice file — connects to a REAL GitHub PR,
# reads its actual diff, and sends it to Gemini for review.
# This is where we first used PyGithub to talk to GitHub.
# Not part of final project — all this logic lives in main.py now.
# ============================================================

import os
from google import genai

# Github = the main PyGithub class to connect to GitHub
# Auth = handles authentication (proving who we are to GitHub)
from github import Github, Auth

from dotenv import load_dotenv

load_dotenv()

# Connect to Gemini AI using our API key from .env
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# Connect to GitHub using our Personal Access Token from .env
# Auth.Token() = the new correct way to authenticate with PyGithub
# GITHUB_TOKEN is stored in .env — never hardcoded here
auth = Auth.Token(os.getenv("GITHUB_TOKEN"))
github_client = Github(auth=auth)

# This function takes a repo name and PR number and reviews it
# repo_name example: "django/django"
# pr_number example: 18700
def review_pr(repo_name, pr_number):

    # get_repo() fetches the repository object from GitHub
    # like opening a specific GitHub repo page, but in code
    repo = github_client.get_repo(repo_name)

    # get_pull() fetches the specific PR from that repo
    # pr now contains everything about that PR — title, files, comments etc
    pr = repo.get_pull(pr_number)

    # Just printing info so we know which PR we're reviewing
    print(f"Reviewing PR: {pr.title}")
    print(f"By: {pr.user.login}")
    print("---")

    # get_files() returns a list of every file changed in this PR
    # each file object has: filename, patch (the diff), status etc
    files = pr.get_files()

    # Loop through every changed file one by one
    for file in files:
        print(f"\nReviewing file: {file.filename}")

        # file.patch = the actual git diff for this file
        # contains all the + and - lines showing what changed
        diff = file.patch

        # Some files have no diff (e.g. binary files, deleted files)
        # If patch is empty, skip this file and move to the next
        if not diff:
            print("No changes to review")
            continue  # skip to next file in the loop

        # Build the prompt by joining strings with +
        # We use string joining instead of f-string to avoid
        # issues with triple quotes and special characters in diffs
        # Each line adds more context for Gemini to understand the task
        prompt = "You are a senior Python developer reviewing a PR.\n"
        prompt += "File: " + file.filename + "\n"  # tell Gemini which file
        prompt += "Git diff:\n" + diff + "\n"       # inject the real diff
        prompt += "Find bugs in added lines (+). Format:\n"
        prompt += "BUG 1:\n- Line:\n- Issue:\n- Fix:\n"
        prompt += "If no issues reply: LGTM"        # tell it what to say if clean

        # Send the unique prompt (with this file's real diff) to Gemini
        # Every file gets a different prompt because diff is different each time
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )

        # Print Gemini's review for this file
        print(response.text)

        # Print a separator line between files for readability
        print("=" * 50)

# Actually call the function with a real Django PR
# This triggers the whole flow — fetch PR → build prompt → call Gemini → print review
review_pr("django/django", 18700)