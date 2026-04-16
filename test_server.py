# ============================================================
# test_server.py
# PURPOSE: Enhanced testing tool to simulate GitHub webhooks
# Tests the new professional code review format with traffic
# light status system instead of arbitrary 100-point scoring.
# Run this while main.py server is running to test locally.
# ============================================================

import requests
import json

def test_basic_pr():
    """Test basic PR webhook simulation"""
    
    print("🧪 Testing AI Code Reviewer v2.0")
    print("=" * 50)
    
    # Simulate GitHub webhook payload
    payload = {
        "action": "opened",
        "repository": {
            "full_name": "django/django"
        },
        "pull_request": {
            "number": 18745,
            "title": "Fix authentication middleware bug",
            "head": {
                "ref": "feature/auth-fix"
            }
        }
    }
    
    try:
        print("📡 Sending webhook to local server...")
        response = requests.post(
            "http://127.0.0.1:8000/review",
            json=payload,
            timeout=60  # Allow time for AI processing
        )
        
        print(f"📊 Status Code: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print("✅ SUCCESS! Review posted")
            print(f"   📄 PR: #{result['pr']}")
            print(f"   🎯 Status: {result['pr_status']}")
            print(f"   📁 Files reviewed: {result['files_reviewed']}")
            print(f"   ⚠️  Issues found:")
            print(f"      🔴 Critical: {result['issues']['critical']}")
            print(f"      🟡 Style: {result['issues']['style']}")
            print(f"      💡 Suggestions: {result['issues']['suggestions']}")
            print(f"   📊 Total issues: {result['issues']['total']}")
            
        else:
            print(f"❌ FAILED: {response.status_code}")
            print(f"Response: {response.text}")
            
    except requests.exceptions.ConnectionError:
        print("❌ CONNECTION ERROR")
        print("Make sure your server is running with:")
        print("uvicorn main:app --reload")
        
    except requests.exceptions.Timeout:
        print("⏱️  TIMEOUT - AI processing took too long")
        print("This is normal for large PRs or slow AI responses")
        
    except Exception as e:
        print(f"❌ UNEXPECTED ERROR: {e}")

def test_health_check():
    """Test server health endpoint"""
    
    print("\n🏥 Testing health check endpoint...")
    
    try:
        response = requests.get("http://127.0.0.1:8000/")
        print(f"Status: {response.status_code}")
        print(f"Response: {response.json()}")
        
    except Exception as e:
        print(f"❌ Health check failed: {e}")

def test_multiple_scenarios():
    """Test different PR scenarios"""
    
    scenarios = [
        {
            "name": "Small PR",
            "repo": "python/cpython", 
            "pr": 32100,
            "branch": "fix/small-bug"
        },
        {
            "name": "Large PR", 
            "repo": "django/django",
            "pr": 18700,
            "branch": "feature/major-refactor"
        }
    ]
    
    for scenario in scenarios:
        print(f"\n🧪 Testing: {scenario['name']}")
        print("-" * 30)
        
        payload = {
            "action": "synchronize",  # Test PR update
            "repository": {
                "full_name": scenario["repo"]
            },
            "pull_request": {
                "number": scenario["pr"],
                "title": f"Test PR - {scenario['name']}",
                "head": {
                    "ref": scenario["branch"]
                }
            }
        }
        
        try:
            response = requests.post(
                "http://127.0.0.1:8000/review",
                json=payload,
                timeout=90
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"✅ {scenario['name']}: {result['pr_status']}")
            else:
                print(f"❌ {scenario['name']}: Failed ({response.status_code})")
                
        except Exception as e:
            print(f"❌ {scenario['name']}: {e}")

if __name__ == "__main__":
    print("🚀 AI Code Reviewer v2.0 - Test Suite")
    print("=" * 50)
    
    # Test health first
    test_health_check()
    
    # Test basic functionality  
    test_basic_pr()
    
    # Test multiple scenarios
    # test_multiple_scenarios()  # Uncomment to test multiple PRs
    
    print("\n✨ Testing complete!")
    print("\nTo run your server:")
    print("uvicorn main:app --reload --port 8000")
