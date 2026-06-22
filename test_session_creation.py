#!/usr/bin/env python3
"""Quick test script to check session creation API"""
import requests
import json
import sys

API_URL = "http://localhost:8000"

def test_signup():
    """Test user signup"""
    print("\n=== Testing Signup ===")
    response = requests.post(
        f"{API_URL}/auth/signup",
        json={"name": "Test User", "email": "test@example.com", "password": "Test@123"}
    )
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    return response.json()

def test_login():
    """Test user login"""
    print("\n=== Testing Login ===")
    response = requests.post(
        f"{API_URL}/auth/login",
        json={"email": "test@example.com", "password": "Test@123"}
    )
    print(f"Status: {response.status_code}")
    data = response.json()
    print(f"Response: {json.dumps(data, indent=2)}")
    return data

def test_create_session(token):
    """Test session creation"""
    print("\n=== Testing Session Creation ===")
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.post(
        f"{API_URL}/sessions",
        headers=headers,
        json={"title": "Test Session", "lang": "en"}
    )
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    return response.json()

if __name__ == "__main__":
    try:
        # Try signup
        signup_resp = test_signup()
        
        if signup_resp.get("success"):
            token = signup_resp["data"]["access_token"]
            print(f"\n✅ Got access token from signup: {token[:20]}...")
            
            # Create session
            session_resp = test_create_session(token)
            if session_resp.get("success"):
                print(f"\n✅ Session created successfully!")
                print(f"Session ID: {session_resp['data'].get('session_id')}")
            else:
                print(f"\n❌ Session creation failed!")
                print(f"Error: {session_resp.get('error')}")
        else:
            print(f"\n❌ Signup failed!")
            print(f"Error: {signup_resp.get('error')}")
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
