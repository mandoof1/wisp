"""Test the C2 server's crypto and API."""
import sys
sys.path.insert(0, "/home/meowman/c2-framework")

from server.crypto import encrypt_json, decrypt_json
import requests

# 1. Test crypto roundtrip
data = {"hello": "world", "num": 42}
encrypted = encrypt_json(data)
print("Encrypted:", encrypted[:60], "...")
decrypted = decrypt_json(encrypted)
print("Decrypted:", decrypted)
assert decrypted == data, f"Mismatch: {decrypted} != {data}"
print("[PASS] Crypto roundtrip OK")

# 2. Test registration
enc_reg = encrypt_json({
    "id": "test-uuid-001",
    "hostname": "test-pc",
    "username": "testuser",
    "os": "linux",
    "arch": "amd64",
    "pid": 1234,
})
resp = requests.post("http://127.0.0.1:8443/api/v1/register", json={"payload": enc_reg})
print("Register status:", resp.status_code)
reg_data = decrypt_json(resp.json()["payload"])
print("Register response:", reg_data)

# 3. Verify beacon appears
resp2 = requests.get("http://127.0.0.1:8443/api/v1/beacons")
beacons = resp2.json().get("beacons", [])
print(f"Beacons count: {len(beacons)}")
for b in beacons:
    print(f"  - {b['id'][:8]}... {b['hostname']} ({b['os']}/{b['arch']})")

print("\n[ALL PASS]")
