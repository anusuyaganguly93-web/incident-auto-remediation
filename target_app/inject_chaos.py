"""
Demo trigger: python3 target_app/inject_chaos.py --latency on
             python3 target_app/inject_chaos.py --latency off --errors off
"""
import argparse
import requests

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--latency", choices=["on", "off"])
    parser.add_argument("--errors", choices=["on", "off"])
    parser.add_argument("--url", default="http://localhost:8080")
    args = parser.parse_args()

    payload = {}
    if args.latency:
        payload["latency"] = args.latency == "on"
    if args.errors:
        payload["errors"] = args.errors == "on"

    if not payload:
        print("nothing to change - pass --latency on/off and/or --errors on/off")
    else:
        resp = requests.post(f"{args.url}/chaos", json=payload, timeout=5)
        resp.raise_for_status()
        print(resp.json())
