# ============================================================
# main.py — AI Code Reviewer (Production Ready)
# FastAPI server that receives GitHub PR webhooks,
# reviews code with Gemini AI, and posts structured comments.
# Run with: uvicorn main:app --reload
# ============================================================

import os
import time
import hmac
import hashlib
from fastapi import FastAPI, Request
from google import genai
from github import Github, Auth
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

# Connect to Gemini and GitHub using keys from .env
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
auth = Auth.Token(os.getenv("GITHUB_TOKEN"))
github_client = Github(auth=auth)

# Max files to review per PR — avoids reviewing 50 files at once
MAX_FILES = 10

# Max diff size per file — Gemini has token limits
# If diff is longer than this, we skip the file
MAX_DIFF_CHARS = 6000


# ── ENDPOINT 1: Health check ──────────────────────────────
@app.get("/")
def home():
    return {"status": "AI Code Reviewer is running!"}


# ── ENDPOINT 2: Webhook receiver ──────────────────────────
@app.post("/review")
async def review_pr(request: Request):

    payload = await request.json()

    # Only review when PR is opened or new commits pushed
    action = payload.get("action")
    if action not in ["opened", "synchronize"]:
        return {"status": "ignored"}

    repo_name = payload["repository"]["full_name"]
    pr_number = payload["pull_request"]["number"]
    pr_title  = payload["pull_request"]["title"]

    print(f"\n{'='*50}")
    print(f"Reviewing PR #{pr_number}: {pr_title}")
    print(f"Repo: {repo_name}")
    print(f"{'='*50}")

    repo  = github_client.get_repo(repo_name)
    pr    = repo.get_pull(pr_number)
    files = list(pr.get_files())

    # Edge case: too many files — only review first MAX_FILES
    if len(files) > MAX_FILES:
        print(f"PR has {len(files)} files — reviewing first {MAX_FILES} only")
        files = files[:MAX_FILES]

    all_reviews = []
    skipped_files = []

    for file in files:

        # Skip files with no diff (binary, deleted etc)
        if not file.patch:
            skipped_files.append(file.filename + " (no diff)")
            continue

        # Edge case: diff too large — skip to avoid Gemini token errors
        if len(file.patch) > MAX_DIFF_CHARS:
            skipped_files.append(file.filename + " (diff too large)")
            print(f"Skipping {file.filename} — diff too large ({len(file.patch)} chars)")
            continue

        print(f"Reviewing: {file.filename}")

        # ── IMPROVED PROMPT ───────────────────────────────
        # Better prompt with:
        # 1. Clear role and expertise level
        # 2. Severity rating for each issue
        # 3. Strict output format for consistency
        # 4. Asks for positive feedback too (more balanced)
        prompt = (
            "You are an expert software engineer doing a thorough code review. "
            "You have 10+ years of experience and care deeply about code quality, "
            "security, and best practices.\n\n"

            f"File being reviewed: {file.filename}\n\n"

            "Git diff (lines starting with + are newly added code to review):\n"
            f"{file.patch}\n\n"

            "Review ONLY the added lines (starting with +).\n\n"

            "For each issue found, use EXACTLY this format:\n\n"
            "ISSUE [number]:\n"
            "- Severity: [CRITICAL / WARNING / SUGGESTION]\n"
            "- Line: [line number or range]\n"
            "- Problem: [clear explanation of what is wrong and why it matters]\n"
            "- Fix:\n"
            "```\n"
            "[corrected code here]\n"
            "```\n\n"

            "Severity guide:\n"
            "CRITICAL = will cause crashes, security holes, or data loss\n"
            "WARNING  = bad practice, potential bugs, or performance issues\n"
            "SUGGESTION = code style, readability, or minor improvements\n\n"

            "After listing all issues, add a one-line summary:\n"
            "SUMMARY: [overall assessment of the code quality]\n\n"

            "If the code has no issues at all, reply with exactly:\n"
            "LGTM — No issues found. Code looks clean and well-written."
        )

        # ── RETRY LOGIC ──────────────────────────────────
        # Try up to 3 times if Gemini is busy (503 errors)
        review_text = None
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt
                )
                review_text = response.text
                break  # success — stop retrying
            except Exception as e:
                print(f"Attempt {attempt + 1} failed: {e}")
                if attempt < 2:
                    wait = (attempt + 1) * 15  # 15s, then 30s
                    print(f"Waiting {wait}s before retry...")
                    time.sleep(wait)
                else:
                    review_text = "Could not review — Gemini unavailable after 3 attempts."

        all_reviews.append({
            "file": file.filename,
            "review": review_text,
            "additions": file.additions,   # how many lines added
            "deletions": file.deletions    # how many lines removed
        })

    # ── BUILD PROFESSIONAL GITHUB COMMENT ────────────────
    # Clean markdown formatting that looks great on GitHub
    review_body = "# AI Code Review\n\n"
    review_body += f"**PR:** {pr_title}\n"
    review_body += f"**Files reviewed:** {len(all_reviews)}"

    if skipped_files:
        review_body += f" | **Skipped:** {len(skipped_files)}"

    review_body += "\n\n---\n\n"

    # Add each file's review as a clean section
    for r in all_reviews:
        review_body += f"## `{r['file']}`\n"
        review_body += f"*+{r['additions']} lines added, -{r['deletions']} lines removed*\n\n"
        review_body += f"{r['review']}\n\n"
        review_body += "---\n\n"

    # List skipped files at the bottom
    if skipped_files:
        review_body += "### Files skipped\n"
        for f in skipped_files:
            review_body += f"- `{f}`\n"
        review_body += "\n"

    review_body += "*Reviewed by AI Code Reviewer — powered by Gemini 2.5 Flash*"

    # Post the comment on the PR
    pr.create_issue_comment(review_body)
    print(f"Review posted on PR #{pr_number}!")

    return {
        "status": "review posted",
        "pr": pr_number,
        "files_reviewed": len(all_reviews),
        "files_skipped": len(skipped_files)
    }