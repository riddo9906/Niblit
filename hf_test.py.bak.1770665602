#!/usr/bin/env python3
import os
import requests

# 1️⃣ Check if token is present
hf_token = os.getenv("HF_TOKEN")
if not hf_token:
    print("[Error] HF_TOKEN not found in environment.")
    exit(1)
print("[OK] HF_TOKEN found.")

# 2️⃣ Quick test with Hugging Face API
headers = {"Authorization": f"Bearer {hf_token}"}
model = "gpt2"  # simple model for testing
payload = {"inputs": "Hello, Hugging Face!"}

try:
    response = requests.post(f"https://router.huggingface.co/models/{model}", headers=headers, json=payload, timeout=10)
    if response.status_code == 200:
        print("[OK] Hugging Face API reachable.")
        print("Response snippet:", response.json())
    else:
        print(f"[Error] API request failed with status code {response.status_code}")
        print("Response:", response.text)
except Exception as e:
    print("[Error] Exception while connecting to HF API:", e)
if __name__ == "__main__":
    print('Running hf_test.py')
