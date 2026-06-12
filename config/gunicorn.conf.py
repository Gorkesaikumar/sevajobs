import multiprocessing
import os

# The IP address and port to bind to
port = os.getenv("PORT", "8000")
bind = f"0.0.0.0:{port}"

# Number of worker processes for handling requests
workers = multiprocessing.cpu_count() * 2 + 1

# Worker class for handling requests
worker_class = "gthread"

# Number of threads per worker
threads = 4

# Maximum number of pending connections
backlog = 2048

# Maximum number of requests a worker will process before restarting
max_requests = 1000

# Randomize max_requests to prevent all workers restarting at the same time
max_requests_jitter = 50

# Timeout for graceful workers restart
timeout = 120

# Logging
accesslog = "-" # stdout
errorlog = "-"  # stderr
loglevel = "info"

# Security
limit_request_line = 4094
limit_request_fields = 100
limit_request_field_size = 8190

# Preload application code before worker processes are forked
preload_app = True
