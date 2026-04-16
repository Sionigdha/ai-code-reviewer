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

        # ── IMPROVED PROMPT WITH CONSISTENCY FOCUS ────────────
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

            "ANALYSIS FRAMEWORK:\n"
            "First, analyze existing patterns in the full file:\n"
            "- Function/variable naming conventions (camelCase vs snake_case)\n"
            "- Parameter formatting and type hints\n"
            "- Documentation style (docstrings, comments)\n"
            "- Error handling patterns (try/except, return values)\n"
            "- Import organization and structure\n\n"

            "Then review ONLY the added lines (+) in the diff.\n"
            "NEW CODE MUST MATCH EXISTING PATTERNS EXACTLY.\n\n"

            "Categorize issues by severity:\n"
            "CRITICAL = Security vulnerabilities, crashes, data loss, logic errors\n"
            "STYLE_VIOLATION = Inconsistent with existing code patterns in this file\n"
            "   - Different naming convention than rest of file\n"
            "   - Different parameter style\n" 
            "   - Missing/inconsistent documentation\n"
            "   - Different error handling approach\n"
            "WARNING = Bad practices, potential bugs, performance issues\n"
            "SUGGESTION = Minor readability, optimization improvements\n\n"

            "CRITICAL RULE: Any deviation from existing file patterns = STYLE_VIOLATION\n"
            "Style consistency is NOT optional - it's essential for team productivity.\n\n"

            "For each issue use EXACTLY this format:\n\n"
            "ISSUE [number]:\n"
            "- Severity: [CRITICAL / STYLE_VIOLATION / WARNING / SUGGESTION]\n"
            "- Line: [line number]\n"
            "- Problem: [what is wrong and why it matters for maintainability]\n"
            "- Fix:\n"
            "```\n"
            "[corrected code that matches existing file patterns]\n"
            "```\n\n"

            "After all issues add:\n"
            "SUMMARY: [one line overall assessment]\n\n"

            "If no issues: reply exactly:\n"
            "LGTM — No issues found. Code is clean and follows existing patterns consistently."
        )

        # ── RETRY LOGIC ──────────────────────────────────
        review_text = None
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
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

    # ── COUNT ISSUES BY SEVERITY (Professional Categories) ─────────────────────────
    total_critical = 0
    total_style = 0
    total_suggestions = 0

    for r in all_reviews:
        text = r["review"].upper()
        total_critical   += text.count("CRITICAL")
        total_style      += text.count("STYLE_VIOLATION") + text.count("INCONSISTENT")
        total_suggestions += text.count("WARNING") + text.count("SUGGESTION")

    total_issues = total_critical + total_style + total_suggestions

    # ── PROFESSIONAL STATUS DETERMINATION (No arbitrary 100-point BS) ────────────────────────────
    # Check if any file couldn't be reviewed
    unreviewed = sum(1 for r in all_reviews if "unavailable" in r["review"].lower() or "could not review" in r["review"].lower())

    if unreviewed == len(all_reviews) and len(all_reviews) > 0:
        status_emoji = "❓"
        status_text = "Review Unavailable"
        status_description = "Gemini was unavailable to complete the review"
    elif total_critical > 0:
        status_emoji = "🔴"
        status_text = "❌ NEEDS WORK"
        status_description = f"Found {total_critical} critical issue{'s' if total_critical != 1 else ''} that must be fixed before merge"
    elif total_style > 0:
        status_emoji = "🟡"
        status_text = "⚠️ APPROVE WITH CHANGES"
        status_description = f"Found {total_style} style consistency issue{'s' if total_style != 1 else ''} - should be fixed"
    elif total_suggestions > 0:
        status_emoji = "🟢"
        status_text = "✅ LGTM WITH SUGGESTIONS"
        status_description = f"Code looks good with {total_suggestions} minor improvement{'s' if total_suggestions != 1 else ''}"
    else:
        status_emoji = "🔥"
        status_text = "✅ EXCELLENT"
        status_description = "Clean, consistent, and well-written code"

    # ── BUILD CONCISE PROFESSIONAL COMMENT (Like Real Senior Devs) ────────────────────
    from datetime import datetime
    now = datetime.utcnow().strftime("%B %d, %Y at %H:%M UTC")

    review_body = f"## Code Review\n\n"
    review_body += f"**{status_text}**\n\n"

    # Quick summary line
    if total_critical > 0:
        review_body += f"🔴 **{total_critical} critical** | 🟡 {total_style} style | 💡 {total_suggestions} suggestions\n\n"
    elif total_style > 0:
        review_body += f"🟡 **{total_style} style issue{'s' if total_style != 1 else ''}** | 💡 {total_suggestions} suggestions\n\n"
    elif total_suggestions > 0:
        review_body += f"💡 **{total_suggestions} suggestion{'s' if total_suggestions != 1 else ''}**\n\n"
    else:
        review_body += f"🔥 **Clean code** - no issues found\n\n"

    # Critical issues (blocking - most important)
    if total_critical > 0:
        review_body += "### 🔴 Must Fix\n"
        for r in all_reviews:
            if "CRITICAL" in r["review"].upper():
                # Extract just the critical parts, not the full review
                lines = r["review"].split('\n')
                for line in lines:
                    if 'CRITICAL' in line.upper() or (line.strip().startswith('- Problem:') and any('CRITICAL' in prev_line for prev_line in lines[max(0, lines.index(line)-3):lines.index(line)])):
                        if line.strip().startswith('- Problem:'):
                            problem = line.replace('- Problem:', '').strip()
                            review_body += f"**`{r['file']}`** - {problem}\n"
                        elif 'Line:' in line:
                            line_info = line.replace('- Line:', '').strip()
                            review_body += f"  *Line {line_info}*\n"
        review_body += "\n"

    # Style issues (should fix)  
    if total_style > 0:
        review_body += "### 🟡 Style Issues\n"
        for r in all_reviews:
            if "STYLE_VIOLATION" in r["review"].upper() or "INCONSISTENT" in r["review"].upper():
                lines = r["review"].split('\n')
                for line in lines:
                    if line.strip().startswith('- Problem:') and any('STYLE_VIOLATION' in prev_line or 'INCONSISTENT' in prev_line for prev_line in lines[max(0, lines.index(line)-3):lines.index(line)]):
                        problem = line.replace('- Problem:', '').strip()
                        review_body += f"**`{r['file']}`** - {problem}\n"
        review_body += "\n"

    # Suggestions (consider)
    if total_suggestions > 0:
        review_body += "### 💡 Consider\n"
        for r in all_reviews:
            if ("WARNING" in r["review"].upper() or "SUGGESTION" in r["review"].upper()) and "CRITICAL" not in r["review"].upper() and "STYLE_VIOLATION" not in r["review"].upper():
                lines = r["review"].split('\n')
                for line in lines:
                    if line.strip().startswith('- Problem:'):
                        problem = line.replace('- Problem:', '').strip()
                        review_body += f"**`{r['file']}`** - {problem}\n"
        review_body += "\n"

    # Clean files (quick acknowledgment)
    clean_files = [r['file'] for r in all_reviews if "LGTM" in r["review"].upper()]
    if clean_files:
        if len(clean_files) <= 3:
            review_body += f"✅ Clean: {', '.join(f'`{f}`' for f in clean_files)}\n\n"
        else:
            review_body += f"✅ {len(clean_files)} files clean\n\n"

    # Skipped files (if any)
    if skipped_files:
        review_body += f"⚠️ Skipped {len(skipped_files)} files (too large)\n\n"

    # Action required (clear next steps)
    if total_critical > 0:
        review_body += "**Action:** Fix critical issues above\n"
    elif total_style > 0:
        review_body += "**Action:** Address style consistency\n"
    elif total_suggestions > 0:
        review_body += "**Action:** Ready to merge (consider suggestions)\n"
    else:
        review_body += "**Action:** Ready to merge ✅\n"

    # Simple footer
    review_body += f"\n---\n*AI Review • {now}*"

    # Post the comment on the PR (keeping your original working logic)
    pr.create_issue_comment(review_body)
    print(f"Review posted on PR #{pr_number}! Status: {status_text}")

    return {
        "status": "review posted",
        "pr": pr_number,
        "pr_status": status_text,
        "files_reviewed": len(all_reviews),
        "files_skipped": len(skipped_files),
        "issues": {
            "critical": total_critical,
            "style": total_style,
            "suggestions": total_suggestions,
            "total": total_issues
        }
    }