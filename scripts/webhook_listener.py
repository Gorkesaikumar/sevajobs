#!/usr/bin/env python3
import os
import hmac
import hashlib
import json
import subprocess
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer

# Configuration
PORT = int(os.environ.get("WEBHOOK_PORT", 9000))
SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
DEPLOY_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "deploy.sh")

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs", "webhook.log"))
    ]
)

class WebhookHandler(BaseHTTPRequestHandler):
    def verify_signature(self, payload_body: bytes, header_signature: str) -> bool:
        if not SECRET:
            logging.warning("No GITHUB_WEBHOOK_SECRET configured! Ignoring signature validation.")
            return True

        if not header_signature:
            return False

        hash_object = hmac.new(SECRET.encode('utf-8'), msg=payload_body, digestmod=hashlib.sha256)
        expected_signature = "sha256=" + hash_object.hexdigest()
        return hmac.compare_digest(expected_signature, header_signature)

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        payload_body = self.rfile.read(content_length)
        header_signature = self.headers.get('X-Hub-Signature-256')

        if not self.verify_signature(payload_body, header_signature):
            logging.error("Signature verification failed.")
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"Forbidden: Signature mismatch.")
            return

        try:
            payload = json.loads(payload_body)
            event = self.headers.get('X-GitHub-Event', 'ping')

            if event == "ping":
                logging.info("Received ping event from GitHub.")
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"Pong")
                return

            if event == "push":
                ref = payload.get('ref', '')
                if ref == 'refs/heads/main':
                    logging.info("Push to main detected. Triggering deployment asynchronously...")
                    # Trigger the deployment script asynchronously so we don't block the webhook response
                    subprocess.Popen(
                        ["bash", DEPLOY_SCRIPT],
                        stdout=open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs", "deploy.log"), "a"),
                        stderr=subprocess.STDOUT
                    )
                    
                    self.send_response(202)
                    self.end_headers()
                    self.wfile.write(b"Deployment accepted and started.")
                else:
                    logging.info(f"Push to {ref} ignored. Only main branch triggers deployment.")
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"Ignored: Not main branch.")
                return

        except json.JSONDecodeError:
            logging.error("Failed to parse JSON payload.")
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Bad Request: Invalid JSON.")
            return

        # Default handler
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Unhandled event type.")

def run_server():
    server_address = ('0.0.0.0', PORT)
    httpd = HTTPServer(server_address, WebhookHandler)
    logging.info(f"Webhook listener started on port {PORT}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    httpd.server_close()
    logging.info("Webhook listener stopped.")

if __name__ == '__main__':
    run_server()
