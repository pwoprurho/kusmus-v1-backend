import requests
import time
import sys

BASE_URL = "http://127.0.0.1:8000"

def check_health():
    print("Verifying KUSMUS Backend Health...")
    for i in range(5):
        try:
            resp = requests.get(f"{BASE_URL}/api/market/trend")
            if resp.status_code == 200:
                print("Backend is ONLINE.")
                return True
        except:
            pass
        print("Waiting for server...")
        time.sleep(2)
    return False

if __name__ == "__main__":
    if check_health():
        print("CI Validation PASSED.")
        sys.exit(0)
    else:
        print("CI Validation FAILED.")
        sys.exit(1)
