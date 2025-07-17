import socket
import os
import sys
import subprocess
import json

CONFIG_PATH = os.path.expanduser("~/.render_client_config.json")

def log(msg):
    print(f"[CLIENT] {msg}")

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'r') as f:
            return json.load(f)
    return {}

def save_config(config):
    with open(CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=2)

def ensure_config():
    config = load_config()

    if "server_host" not in config:
        config["server_host"] = input("Enter server IP (e.g. 192.168.1.132): ").strip()
    if "server_port" not in config:
        config["server_port"] = int(input("Enter server port (e.g. 5555): ").strip())
    if "remote_addons_dir" not in config:
        config["remote_addons_dir"] = "~/.config/blender/4.5/scripts/addons/"
    if "local_addons_dir" not in config:
        config["local_addons_dir"] = os.path.expanduser("~/Library/Application Support/Blender/4.1/scripts/addons/")
    if "render_output_dir" not in config:
        default_out = os.path.expanduser("~/Rendered")
        config["render_output_dir"] = input(f"Local output directory (default: {default_out}): ").strip() or default_out

    save_config(config)
    return config

def auto_download(server_host, job_id, local_folder):
    remote_path = f"wys@{server_host}:~/render_jobs/{job_id}/"
    log(f"Attempting to auto-download render output from {remote_path}")
    os.makedirs(local_folder, exist_ok=True)

    try:
        rsync_cmd = ["rsync", "-avz", remote_path, f"{local_folder}/"]
        result = subprocess.run(rsync_cmd)
        if result.returncode == 0:
            log("Render output downloaded successfully.")
        else:
            raise Exception("rsync failed.")
    except Exception as e:
        log(f"Auto-download failed: {e}")
        log("To manually retrieve your render:")
        log(f"  rsync -avz {remote_path} {local_folder}/")

# === Load config ===
config = ensure_config()
SERVER_HOST = config["server_host"]
SERVER_PORT = config["server_port"]
LOCAL_ADDONS_DIR = config["local_addons_dir"]
REMOTE_ADDONS_DIR = config["remote_addons_dir"]
RENDER_OUTPUT_DIR = os.path.abspath(os.path.expanduser(config["render_output_dir"]))

# === Args ===
if len(sys.argv) < 2:
    print("Usage: python3 send_render_job.py <file.blend> [--animation] [--format PNG|FFMPEG|JPEG]")
    sys.exit(1)

blend_path = sys.argv[1]
render_type = "animation" if "--animation" in sys.argv else "image"
output_format = "PNG"
for i, arg in enumerate(sys.argv):
    if arg == "--format" and i + 1 < len(sys.argv):
        output_format = sys.argv[i + 1].upper()

blend_name = os.path.basename(blend_path)
file_size = os.path.getsize(blend_path)

# === Sync add-ons ===
log("Syncing Blender add-ons...")
if os.path.exists(LOCAL_ADDONS_DIR):
    rsync_cmd = [
        "rsync", "-avz", LOCAL_ADDONS_DIR,
        f"wys@{SERVER_HOST}:{REMOTE_ADDONS_DIR}"
    ]
    result = subprocess.run(rsync_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log("Add-on sync failed:")
        print(result.stderr)
    else:
        log("Add-ons synced.")
else:
    log("Local add-ons directory not found.")

# === Connect & send ===
log(f"Connecting to render server at {SERVER_HOST}:{SERVER_PORT}...")
try:
    with socket.create_connection((SERVER_HOST, SERVER_PORT)) as s:
        log("Connected to server.")

        header = f"{blend_name}\n{render_type}\n{file_size}\n{output_format}\n===END===\n"
        s.sendall(header.encode())

        with open(blend_path, "rb") as f:
            while True:
                chunk = f.read(4096)
                if not chunk:
                    break
                s.sendall(chunk)

        log("Blend file sent. Waiting for response...")

        try:
            buffer = ""
            job_id = None
            while True:
                chunk = s.recv(1024)
                if not chunk:
                    break

                decoded = chunk.decode(errors="ignore")
                buffer += decoded
                lines = buffer.split("\n")

                # Keep the last partial line
                buffer = lines.pop() if not decoded.endswith("\n") else ""

                for line in lines:
                  line = line.strip()

                  # Progress / rendering lines
                  if "Fra:" in line or "Rendering" in line:
                      sys.stdout.write(f"\r[Blender] {line[:100]:<100}")
                      sys.stdout.flush()

                  # Queue message
                  elif line.startswith("QUEUED:"):
                      sys.stdout.write(f"\r[Queue]   {line:<100}")
                      sys.stdout.flush()

                  # Processing message
                  elif line.startswith("PROCESSING:"):
                      sys.stdout.write(f"\r[Status]  {line:<100}")
                      sys.stdout.flush()

                  # Job ID
                  if line.startswith("JOB_ID:"):
                      job_id = line.split(":", 1)[1].strip()

                  # Done
                  if "DONE: OK" in line or "DONE: ERROR" in line:
                      result_status = "success" if "DONE: OK" in line else "failure"
                      print()  # Print newline to avoid overwriting
                
            if job_id:
                output_folder = os.path.join(RENDER_OUTPUT_DIR, job_id)
                log(f"Render job {job_id} complete. Attempting to fetch results...")
                auto_download(SERVER_HOST, job_id, output_folder)
            else:
                log("No job ID received. Cannot download results.")

        except Exception as e:
            log(f"Error receiving log: {e}")

        response = b""
        while True:
            chunk = s.recv(1024)
            if not chunk:
                break
            response += chunk
            if b"DONE:" in response:
                break

        decoded = response.decode(errors="ignore")
        log("Server response:")
        print(decoded)

        if "DONE: OK" in decoded:
            job_id = None
            for line in decoded.splitlines():
                if line.startswith("JOB_ID:"):
                    job_id = line.split(":", 1)[1].strip()
                    break

            if job_id:
                output_folder = os.path.join(RENDER_OUTPUT_DIR, job_id)
                log(f"Render complete. Retrieving files into {output_folder}")
                auto_download(SERVER_HOST, job_id, output_folder)
            else:
                log("JOB_ID not found in response.")
        else:
            log("Render failed or unexpected response.")

except Exception as e:
    log(f"Connection error: {e}")
