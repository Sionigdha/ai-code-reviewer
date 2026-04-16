# ============================================================
# main.py — AI Code Reviewer (Production Ready v2.0)
# FastAPI server that receives GitHub PR webhooks,
# reviews code with Gemini AI, and posts professional comments.
# Run with: uvicorn main:app --reload
# ============================================================

import os
import time
import hmac
import hashlib
import re
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
MAX_DIFF_CHARS = 6000


# ── ENDPOINT 1: Health check ──────────────────────────────
@app.get("/")
def home():
    return {"status": "AI Code Reviewer v2.0 is running!"}


# ── HELPER: Parse Gemini Response ─────────────────────────
def parse_review_response(review_text, filename):
    """Parse Gemini's structured response into categorized issues"""
    
    issues = {
        'critical': [],
        'style': [],
        'suggestions': [],
        'lgtm': False
    }
    
    # Check if it's a clean review
    if 'LGTM' in review_text.upper() or 'no issues found' in review_text.lower():
        issues['lgtm'] = True
        return issues
    
    # Parse structured issues using regex
    issue_pattern = r'(ISSUE|BUG)\s*(\d+):\s*\n?-\s*Severity:\s*(CRITICAL|STYLE_VIOLATION|WARNING|SUGGESTION)\s*\n?-\s*Line:\s*(.+?)\n?-\s*Problem:\s*(.+?)\n?-\s*Fix:\s*\n?```\n?(.*?)\n?```'
    
    matches = re.findall(issue_pattern, review_text, re.DOTALL | re.IGNORECASE)
    
    for match in matches:
        issue_type, issue_num, severity, line, problem, fix = match
        
        issue_data = {
            'line': line.strip(),
            'problem': problem.strip(),
            'fix': fix.strip() if fix.strip() else 'See problem description',
            'file': filename
        }
        
        severity_clean = severity.upper()
        if severity_clean == 'CRITICAL':
            issues['critical'].append(issue_data)
        elif severity_clean == 'STYLE_VIOLATION':
            issues['style'].append(issue_data)
        else:  # WARNING or SUGGESTION
            issues['suggestions'].append(issue_data)
    
    return issues


# ── HELPER: Determine PR Status ──────────────────────────
def determine_pr_status(all_issues):
    """Determine overall PR status based on issues found"""
    
    total_critical = sum(len(issues['critical']) for issues in all_issues.values())
    total_style = sum(len(issues['style']) for issues in all_issues.values())
    total_suggestions = sum(len(issues['suggestions']) for issues in all_issues.values())
    
    if total_critical > 0:
        return {
            'status': '❌ NEEDS WORK',
            'emoji': '🔴',
            'label': 'Blocking issues found',
            'description': 'Critical issues must be fixed before merge'
        }
    elif total_style > 0:
        return {
            'status': '⚠️ APPROVE WITH CHANGES',
            'emoji': '🟡', 
            'label': 'Style issues found',
            'description': 'Minor issues should be addressed'
        }
    elif total_suggestions > 0:
        return {
            'status': '✅ LGTM WITH SUGGESTIONS',
            'emoji': '🟢',
            'label': 'Ready to merge',
            'description': 'Code looks good with minor improvement opportunities'
        }
    else:
        return {
            'status': '✅ EXCELLENT',
            'emoji': '🔥',
            'label': 'Above expectations', 
            'description': 'Clean, consistent, and well-written code'
        }


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
    pr_branch = payload["pull_request"]["head"]["ref"]

    print(f"\n{'='*50}")
    print(f"Reviewing PR #{pr_number}: {pr_title}")
    print(f"Repo: {repo_name} • Branch: {pr_branch}")
    print(f"{'='*50}")

    repo  = github_client.get_repo(repo_name)
    pr    = repo.get_pull(pr_number)
    files = list(pr.get_files())

    # Edge case: too many files — only review first MAX_FILES
    if len(files) > MAX_FILES:
        print(f"PR has {len(files)} files — reviewing first {MAX_FILES} only")
        files = files[:MAX_FILES]

    all_file_issues = {}
    skipped_files = []

    # Get repo context once
    repo_context = ""
    try:
        readme = repo.get_contents("README.md")
        readme_text = readme.decoded_content.decode("utf-8")
        repo_context = readme_text[:1500]
    except Exception:
        repo_context = "(no README found)"

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

        # Get full file content for context
        full_file_content = ""
        try:
            file_obj = repo.get_contents(file.filename, ref=pr.head.sha)
            full_content = file_obj.decoded_content.decode("utf-8")
            if len(full_content) > 3000:
                full_file_content = full_content[:3000] + "\n... (truncated)"
            else:
                full_file_content = full_content
        except Exception as e:
            print(f"Could not fetch full file: {e}")
            full_file_content = "(full file unavailable)"

        # Enhanced prompt for professional review
        prompt = (
            "You are a senior software engineer conducting a thorough code review.\n\n"

            f"REPOSITORY CONTEXT (from README):\n{repo_context}\n\n"

            f"FULL CURRENT FILE ({file.filename}):\n"
            f"```\n{full_file_content}\n```\n\n"

            f"GIT DIFF (lines with + are newly added):\n"
            f"```\n{file.patch}\n```\n\n"

            "ANALYSIS FRAMEWORK:\n"
            "First, analyze existing patterns in the full file:\n"
            "- Function/variable naming conventions\n"
            "- Code structure and organization\n"
            "- Documentation style\n"
            "- Error handling patterns\n"
            "- Import organization\n\n"

            "Then review ONLY the added lines (+) in the diff.\n"
            "Categorize issues by severity:\n\n"

            "CRITICAL = Security vulnerabilities, crashes, data loss, logic errors\n"
            "STYLE_VIOLATION = Inconsistent with existing code patterns in this file/repo\n"
            "SUGGESTION = Best practices, performance, readability improvements\n\n"

            "IMPORTANT RULES:\n"
            "1. NEW CODE MUST MATCH existing patterns in the file exactly\n"
            "2. Any deviation from file conventions = STYLE_VIOLATION\n"
            "3. Focus on maintainability and team consistency\n"
            "4. Provide concrete code examples in fixes\n"
            "5. Don't raise multiple issues for the same root cause\n\n"

            "Use EXACTLY this format for each issue:\n\n"
            "ISSUE [number]:\n"
            "- Severity: [CRITICAL / STYLE_VIOLATION / SUGGESTION]\n"
            "- Line: [line number or range]\n"
            "- Problem: [what is wrong and why it matters for this codebase]\n"
            "- Fix:\n"
            "```\n"
            "[corrected code that matches existing patterns]\n"
            "```\n\n"

            "After all issues add:\n"
            "SUMMARY: [one line assessment]\n\n"

            "If no issues found, reply exactly:\n"
            "LGTM — Code is clean and follows existing patterns consistently."
        )

        # Retry logic for Gemini API calls
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

        # Parse the review into structured issues
        file_issues = parse_review_response(review_text, file.filename)
        all_file_issues[file.filename] = {
            'issues': file_issues,
            'raw_review': review_text,
            'additions': file.additions,
            'deletions': file.deletions
        }

    # Determine overall PR status
    pr_status = determine_pr_status({f: data['issues'] for f, data in all_file_issues.items()})
    
    # Count total issues
    total_critical = sum(len(data['issues']['critical']) for data in all_file_issues.values())
    total_style = sum(len(data['issues']['style']) for data in all_file_issues.values())
    total_suggestions = sum(len(data['issues']['suggestions']) for data in all_file_issues.values())
    total_issues = total_critical + total_style + total_suggestions

    # Build professional GitHub comment
    from datetime import datetime
    now = datetime.utcnow().strftime("%B %d, %Y at %H:%M UTC")

    review_body = f"## AI Code Review • `{pr_branch}`\n\n"
    review_body += f"**Status: {pr_status['status']}**\n\n"
    review_body += f"> {pr_status['description']}\n\n"
    review_body += "---\n\n"

    # Critical Issues Section
    if total_critical > 0:
        review_body += f"### 🔴 Critical Issues ({total_critical})\n"
        review_body += "*Must be fixed before merge*\n\n"
        
        for filename, data in all_file_issues.items():
            for issue in data['issues']['critical']:
                review_body += f"**`{filename}` line {issue['line']}** - {issue['problem']}\n"
                if issue['fix'] != 'See problem description':
                    review_body += f"```python\n{issue['fix']}\n```\n\n"
                else:
                    review_body += "\n"
        review_body += "---\n\n"

    # Style Issues Section  
    if total_style > 0:
        review_body += f"### 🟡 Style Issues ({total_style})\n"
        review_body += "*Should be fixed for consistency*\n\n"
        
        for filename, data in all_file_issues.items():
            for issue in data['issues']['style']:
                review_body += f"**`{filename}` line {issue['line']}** - {issue['problem']}\n"
                if issue['fix'] != 'See problem description':
                    review_body += f"```python\n{issue['fix']}\n```\n\n"
                else:
                    review_body += "\n"
        review_body += "---\n\n"

    # Suggestions Section
    if total_suggestions > 0:
        review_body += f"### 💡 Suggestions ({total_suggestions})\n"
        review_body += "*Consider these improvements*\n\n"
        
        for filename, data in all_file_issues.items():
            for issue in data['issues']['suggestions']:
                review_body += f"**`{filename}` line {issue['line']}** - {issue['problem']}\n"
                if issue['fix'] != 'See problem description':
                    review_body += f"```python\n{issue['fix']}\n```\n\n"
                else:
                    review_body += "\n"
        review_body += "---\n\n"

    # Files Summary
    review_body += "### Files Analyzed\n"
    for filename, data in all_file_issues.items():
        issues = data['issues']
        if issues['lgtm']:
            review_body += f"- ✅ `{filename}` - Clean, follows repo patterns\n"
        elif len(issues['critical']) > 0:
            review_body += f"- 🔴 `{filename}` - {len(issues['critical'])} critical issues\n"
        elif len(issues['style']) > 0:
            review_body += f"- 🟡 `{filename}` - {len(issues['style'])} style issues\n"
        else:
            review_body += f"- 💡 `{filename}` - Minor suggestions only\n"

    # Skipped files
    if skipped_files:
        review_body += f"\n**Skipped ({len(skipped_files)}):** " + ", ".join(f"`{f}`" for f in skipped_files)

    review_body += "\n\n"

    # Next Steps
    if total_critical > 0:
        review_body += "**Next Steps:** Fix critical issues, then this is ready to merge.\n\n"
    elif total_style > 0:
        review_body += "**Next Steps:** Address style consistency, then we're good to go.\n\n"
    else:
        review_body += "**Next Steps:** Ready to merge! 🚀\n\n"

    # Footer
    review_body += "---\n"
    review_body += f"*AI Code Reviewer v2.0 • {now}*\n"
    review_body += "*Powered by Gemini AI*"

    # Post the comment on the PR
    pr.create_issue_comment(review_body)
    print(f"Professional review posted on PR #{pr_number}! Status: {pr_status['status']}")

    return {
        "status": "review posted",
        "pr": pr_number,
        "pr_status": pr_status['label'],
        "files_reviewed": len(all_file_issues),
        "files_skipped": len(skipped_files),
        "issues": {
            "critical": total_critical,
            "style": total_style, 
            "suggestions": total_suggestions,
            "total": total_issues
        }
    }
