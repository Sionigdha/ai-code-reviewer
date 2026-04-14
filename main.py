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

        # Skip files with no diff
        if not file.patch:
            skipped_files.append(file.filename + " (no diff)")
            continue

        # Skip diffs that are too large
        if len(file.patch) > MAX_DIFF_CHARS:
            skipped_files.append(file.filename + " (diff too large)")
            print(f"Skipping {file.filename} — diff too large")
            continue

        print(f"Reviewing: {file.filename}")

        # ── LEVEL 1: FULL FILE CONTEXT ───────────────────
        # Get the complete current file — not just the diff
        # This lets Gemini see what surrounds the changed lines
        # e.g. if a function is inconsistent with others in the file
        full_file_content = ""
        try:
            file_obj = repo.get_contents(file.filename, ref=pr.head.sha)
            full_content = file_obj.decoded_content.decode("utf-8")
            # Limit to 3000 chars so we don't blow Gemini's context
            if len(full_content) > 3000:
                full_file_content = full_content[:3000] + "\n... (truncated)"
            else:
                full_file_content = full_content
        except Exception as e:
            print(f"Could not fetch full file: {e}")
            full_file_content = "(full file unavailable)"

        # ── LEVEL 2: REPO CONTEXT ────────────────────────
        # Read the repo's README to understand conventions
        # Only fetch once — store it outside loop for efficiency
        repo_context = ""
        try:
            readme = repo.get_contents("README.md")
            readme_text = readme.decoded_content.decode("utf-8")
            # Take first 1500 chars — enough for purpose + conventions
            repo_context = readme_text[:1500]
        except Exception:
            repo_context = "(no README found)"

        # ── IMPROVED PROMPT WITH FULL CONTEXT ────────────
        prompt = (
            "You are an expert software engineer doing a thorough code review.\n\n"

            # Level 2 — repo context
            f"REPOSITORY CONTEXT (from README):\n{repo_context}\n\n"

            # Level 1 — full file
            f"FULL CURRENT FILE ({file.filename}):\n"
            f"```\n{full_file_content}\n```\n\n"

            # The actual diff
            f"GIT DIFF (lines with + are newly added):\n"
            f"```\n{file.patch}\n```\n\n"

            "Review the ADDED lines (+) in the diff.\n"
            "Use the full file and README context to:\n"
            "1. Check if the change is consistent with existing patterns\n"
            "2. Check if the change follows repo conventions\n"
            "3. Find bugs, security issues, or bad practices\n\n"

            "For each issue use EXACTLY this format:\n\n"
            "ISSUE [number]:\n"
            "- Severity: [CRITICAL / WARNING / SUGGESTION]\n"
            "- Line: [line number]\n"
            "- Problem: [what is wrong and why it matters]\n"
            "- Fix:\n"
            "```\n"
            "[corrected code]\n"
            "```\n\n"

            "Severity guide:\n"
            "CRITICAL = crashes, security holes, data loss\n"
            "WARNING  = bad practice, potential bugs, performance\n"
            "SUGGESTION = style, readability, minor improvements\n\n"

            "After all issues add:\n"
            "SUMMARY: [one line overall assessment]\n\n"

            "If no issues: reply exactly:\n"
            "LGTM — No issues found. Code looks clean and consistent with the repo."
        )

        # ── RETRY LOGIC ──────────────────────────────────
        review_text = None
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=prompt
                )
                review_text = response.text
                break
            except Exception as e:
                print(f"Attempt {attempt + 1} failed: {e}")
                if attempt < 2:
                    wait = (attempt + 1) * 15
                    print(f"Waiting {wait}s before retry...")
                    time.sleep(wait)
                else:
                    review_text = "Could not review — Gemini unavailable after 3 attempts."

        all_reviews.append({
            "file": file.filename,
            "review": review_text,
            "additions": file.additions,
            "deletions": file.deletions
        })

    # ── COUNT ISSUES BY SEVERITY ─────────────────────────
    # Parse each review to count CRITICAL / WARNING / SUGGESTION
    total_critical = 0
    total_warning = 0
    total_suggestion = 0

    for r in all_reviews:
        text = r["review"].upper()
        total_critical   += text.count("CRITICAL")
        total_warning    += text.count("WARNING")
        total_suggestion += text.count("SUGGESTION")

    total_issues = total_critical + total_warning + total_suggestion

    # ── CALCULATE HEALTH SCORE ────────────────────────────
    # Score starts at 100, deduct by severity
    # CRITICAL = -20, WARNING = -8, SUGGESTION = -2
    score = 100
    score -= total_critical   * 20
    score -= total_warning    * 8
    score -= total_suggestion * 2
    score = max(0, score)  # never go below 0

    # Score label
    if score >= 85:
        score_label = "Excellent"
    elif score >= 70:
        score_label = "Good"
    elif score >= 50:
        score_label = "Needs Work"
    else:
        score_label = "Poor"

    # ── BUILD POLISHED GITHUB COMMENT ────────────────────
    from datetime import datetime
    now = datetime.utcnow().strftime("%B %d, %Y at %H:%M UTC")

    review_body  = "# AI Code Review\n\n"

    # Score card
    review_body += f"## PR Health Score: {score}/100 — {score_label}\n\n"
    review_body += f"> **{pr_title}**\n\n"

    # Summary table
    review_body += "| Metric | Count |\n"
    review_body += "|--------|-------|\n"
    review_body += f"| Files reviewed | {len(all_reviews)} |\n"
    if skipped_files:
        review_body += f"| Files skipped | {len(skipped_files)} |\n"
    review_body += f"| CRITICAL issues | {total_critical} |\n"
    review_body += f"| WARNING issues | {total_warning} |\n"
    review_body += f"| SUGGESTION issues | {total_suggestion} |\n"
    review_body += f"| Total issues | {total_issues} |\n\n"
    review_body += "---\n\n"

    # Detailed file reviews
    for r in all_reviews:
        review_body += f"## `{r['file']}`\n"
        review_body += f"*+{r['additions']} lines added, -{r['deletions']} lines removed*\n\n"
        review_body += f"{r['review']}\n\n"
        review_body += "---\n\n"

    # Skipped files
    if skipped_files:
        review_body += "### Files skipped\n"
        for f in skipped_files:
            review_body += f"- `{f}`\n"
        review_body += "\n---\n\n"

    # Footer
    review_body += f"*Reviewed by AI Code Reviewer v1.0 • {now}*\n"
    review_body += "*Powered by Gemini 2.0 Flash*"

    # Post the comment on the PR
    pr.create_issue_comment(review_body)
    print(f"Review posted on PR #{pr_number}! Score: {score}/100")

    return {
        "status": "review posted",
        "pr": pr_number,
        "score": score,
        "files_reviewed": len(all_reviews),
        "files_skipped": len(skipped_files),
        "total_issues": total_issues
    }