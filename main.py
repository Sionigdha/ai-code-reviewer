# ============================================================
# main.py — AI Code Reviewer (Fixed Version)
# Back to basics - closer to your original working version
# with added debug logging to find the GitHub posting issue
# ============================================================

import os
import time
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

MAX_FILES = 10
MAX_DIFF_CHARS = 6000

@app.get("/")
def home():
    return {"status": "AI Code Reviewer (Fixed) is running!"}

@app.post("/review")
async def review_pr(request: Request):
    
    try:
        print("🟢 WEBHOOK RECEIVED - Starting processing...")
        
        # Basic error handling for JSON
        try:
            print("🔍 DEBUG: Attempting to parse JSON...")
            payload = await request.json()
            print(f"✅ JSON parsed successfully! Keys: {list(payload.keys()) if payload else 'None'}")
        except Exception as e:
            print(f"❌ JSON parsing failed: {e}")
            return {"error": f"JSON parsing failed: {e}"}
        
        if not payload or "action" not in payload:
            print("❌ Invalid payload structure")
            return {"error": "Invalid payload"}
        
        print(f"🔍 DEBUG: Action = {payload.get('action')}")
            
        action = payload.get("action")
        if action not in ["opened", "synchronize"]:
            print(f"⚠️  Ignoring action: {action}")
            return {"status": "ignored", "reason": f"Action '{action}' not supported"}

        try:
            print("🔍 DEBUG: Extracting PR info...")
            repo_name = payload["repository"]["full_name"]
            pr_number = payload["pull_request"]["number"]
            pr_title = payload["pull_request"]["title"]
            pr_branch = payload.get("pull_request", {}).get("head", {}).get("ref", "unknown")
            print(f"✅ PR Info extracted: {repo_name} #{pr_number}")
        except KeyError as e:
            print(f"❌ Missing required field: {e}")
            return {"error": f"Missing required field: {e}"}
        except Exception as e:
            print(f"❌ Unexpected error extracting PR info: {e}")
            return {"error": f"Payload structure error: {e}"}
            
    except Exception as e:
        print(f"💥 WEBHOOK HANDLER CRASHED: {e}")
        print(f"💥 Error type: {type(e).__name__}")
        import traceback
        print(f"💥 Full traceback: {traceback.format_exc()}")
        return {"error": f"Webhook handler crashed: {e}"}

    print(f"\n{'='*50}")
    print(f"🔍 DEBUG: Reviewing PR #{pr_number}: {pr_title}")
    print(f"🔍 DEBUG: Repo: {repo_name} • Branch: {pr_branch}")
    print(f"🔍 DEBUG: GitHub Token Present: {'Yes' if os.getenv('GITHUB_TOKEN') else 'No'}")
    print(f"🔍 DEBUG: Gemini Key Present: {'Yes' if os.getenv('GEMINI_API_KEY') else 'No'}")
    print(f"{'='*50}")

    # Connect to GitHub with detailed error handling
    try:
        repo = github_client.get_repo(repo_name)
        print(f"✅ Successfully connected to repo: {repo.full_name}")
    except Exception as e:
        error_msg = f"Failed to access repository '{repo_name}': {e}"
        print(f"❌ {error_msg}")
        return {"error": error_msg}
        
    try:
        pr = repo.get_pull(pr_number)
        print(f"✅ Successfully fetched PR #{pr_number}: {pr.title}")
    except Exception as e:
        error_msg = f"Failed to access PR #{pr_number}: {e}"
        print(f"❌ {error_msg}")
        return {"error": error_msg}
        
    try:
        files = list(pr.get_files())
        print(f"✅ Found {len(files)} changed files")
    except Exception as e:
        error_msg = f"Failed to get PR files: {e}"
        print(f"❌ {error_msg}")
        return {"error": error_msg}

    # Limit files 
    if len(files) > MAX_FILES:
        print(f"⚠️  Limiting to first {MAX_FILES} files")
        files = files[:MAX_FILES]

    all_reviews = []
    skipped_files = []

    # Get repo context
    repo_context = ""
    try:
        readme = repo.get_contents("README.md")
        readme_text = readme.decoded_content.decode("utf-8")
        repo_context = readme_text[:1500]
        print(f"✅ Got README context ({len(repo_context)} chars)")
    except Exception as e:
        repo_context = "(no README found)"
        print(f"⚠️  No README found: {e}")

    for file in files:
        if not file.patch:
            skipped_files.append(file.filename + " (no diff)")
            continue

        if len(file.patch) > MAX_DIFF_CHARS:
            skipped_files.append(file.filename + " (diff too large)")
            print(f"⚠️  Skipping {file.filename} — diff too large")
            continue

        print(f"🔍 Reviewing: {file.filename}")

        # Get full file content
        full_file_content = ""
        try:
            file_obj = repo.get_contents(file.filename, ref=pr.head.sha)
            full_content = file_obj.decoded_content.decode("utf-8")
            if len(full_content) > 3000:
                full_file_content = full_content[:3000] + "\n... (truncated)"
            else:
                full_file_content = full_content
        except Exception as e:
            print(f"⚠️  Could not fetch full file: {e}")
            full_file_content = "(full file unavailable)"

        # Simplified prompt (closer to original)
        prompt = f"""
You are a senior software engineer doing a code review.

REPOSITORY CONTEXT:
{repo_context}

FULL FILE ({file.filename}):
```
{full_file_content}
```

GIT DIFF (+ lines are new code):
```
{file.patch}
```

Review the added lines (+) in the diff.
Check if new code is consistent with existing patterns in the file.
Find bugs, security issues, and style inconsistencies.

For each issue use this format:
ISSUE 1:
- Severity: [CRITICAL / STYLE_VIOLATION / SUGGESTION]  
- Line: [line number]
- Problem: [what is wrong]
- Fix: [suggested correction]

If no issues: reply "LGTM — Code looks clean and consistent."
"""

        # Call Gemini with retry logic
        review_text = None
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt
                )
                review_text = response.text
                print(f"✅ Got Gemini review for {file.filename} ({len(review_text)} chars)")
                break
            except Exception as e:
                print(f"⚠️  Gemini attempt {attempt + 1} failed: {e}")
                if attempt < 2:
                    time.sleep((attempt + 1) * 10)
                else:
                    review_text = f"Could not review {file.filename} — Gemini unavailable after 3 attempts."

        all_reviews.append({
            "file": file.filename,
            "review": review_text,
            "additions": file.additions,
            "deletions": file.deletions
        })

    # Simple issue counting (like original)
    total_critical = 0
    total_style = 0
    total_suggestions = 0

    for r in all_reviews:
        text = r["review"].upper()
        total_critical += text.count("CRITICAL")
        total_style += text.count("STYLE_VIOLATION")
        total_suggestions += text.count("SUGGESTION") + text.count("WARNING")

    total_issues = total_critical + total_style + total_suggestions

    # Determine status (simple logic)
    if total_critical > 0:
        status_emoji = "🔴"
        status_text = "❌ NEEDS WORK"
        status_label = "Critical issues found"
    elif total_style > 0:
        status_emoji = "🟡"
        status_text = "⚠️ APPROVE WITH CHANGES"
        status_label = "Style issues found"
    elif total_suggestions > 0:
        status_emoji = "🟢"
        status_text = "✅ LGTM WITH SUGGESTIONS"
        status_label = "Minor suggestions"
    else:
        status_emoji = "🔥"
        status_text = "✅ EXCELLENT"
        status_label = "Clean code"

    print(f"📊 Review Summary: {status_text}")
    print(f"   🔴 Critical: {total_critical}")
    print(f"   🟡 Style: {total_style}")
    print(f"   💡 Suggestions: {total_suggestions}")

    # Build comment (simplified format)
    from datetime import datetime
    now = datetime.utcnow().strftime("%B %d, %Y at %H:%M UTC")

    comment_body = f"## AI Code Review • `{pr_branch}`\n\n"
    comment_body += f"**Status: {status_text}**\n\n"
    comment_body += f"{status_emoji} **Summary:** {status_label}\n\n"
    comment_body += "---\n\n"

    # Add individual file reviews
    for r in all_reviews:
        comment_body += f"### `{r['file']}`\n"
        comment_body += f"*+{r['additions']} lines, -{r['deletions']} lines*\n\n"
        comment_body += f"{r['review']}\n\n"
        comment_body += "---\n\n"

    # Summary stats
    comment_body += f"**Files Reviewed:** {len(all_reviews)}\n"
    if skipped_files:
        comment_body += f"**Files Skipped:** {len(skipped_files)}\n"
    comment_body += f"**Issues Found:** {total_critical} critical, {total_style} style, {total_suggestions} suggestions\n\n"
    comment_body += f"*Reviewed by AI Code Reviewer • {now}*"

    # POST COMMENT TO GITHUB (with detailed debugging)
    print(f"🔍 DEBUG: About to post comment to GitHub...")
    print(f"🔍 DEBUG: Comment length: {len(comment_body)} characters")
    print(f"🔍 DEBUG: PR object type: {type(pr)}")
    
    try:
        print(f"🔍 DEBUG: Calling pr.create_issue_comment()...")
        comment = pr.create_issue_comment(comment_body)
        print(f"🎉 SUCCESS! Comment posted successfully!")
        print(f"🔗 Comment URL: {comment.html_url}")
        print(f"💬 Comment ID: {comment.id}")
        
        return {
            "status": "review posted",
            "pr": pr_number,
            "pr_status": status_label,
            "files_reviewed": len(all_reviews),
            "files_skipped": len(skipped_files),
            "comment_url": comment.html_url,
            "comment_id": comment.id,
            "issues": {
                "critical": total_critical,
                "style": total_style,
                "suggestions": total_suggestions,
                "total": total_issues
            }
        }
        
    except Exception as e:
        error_msg = f"Failed to post GitHub comment: {e}"
        print(f"❌ {error_msg}")
        print(f"🔍 DEBUG: Error type: {type(e).__name__}")
        print(f"🔍 DEBUG: Error details: {str(e)}")
        
        # Try to get more specific error info
        if hasattr(e, 'status'):
            print(f"🔍 DEBUG: HTTP Status: {e.status}")
        if hasattr(e, 'data'):
            print(f"🔍 DEBUG: Response data: {e.data}")
            
        return {
            "error": error_msg,
            "debug": {
                "repo": repo_name,
                "pr": pr_number,
                "error_type": type(e).__name__,
                "has_github_token": bool(os.getenv('GITHUB_TOKEN')),
                "comment_length": len(comment_body)
            }
        }