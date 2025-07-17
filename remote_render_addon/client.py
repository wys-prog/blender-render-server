import socket
import os
import sys
import subprocess
import json

CONFIG_PATH = os.path.expanduser("~/.render_client_config.json")

def default_log(msg):
    print(f"[CLIENT] {msg}")

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'r') as f:
            return json.load(f)
    return {}

def save_config(config):
    with open(CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=2)

def ensure_config(config=None, log=default_log):
    """
    Ensure config dict has all required keys.
    If config is None, load from disk or defaults.
    """
    if config is None:
        config = load_config()

    changed = False
    # If keys missing, prompt user or set default if possible
    if "server_host" not in config:
        raise ValueError("Missing 'server_host' in config")
    if "server_port" not in config:
        raise ValueError("Missing 'server_port' in config")
    if "remote_addons_dir" not in config:
        config["remote_addons_dir"] = "~/.config/blender/4.5/scripts/addons/"
        changed = True
    if "local_addons_dir" not in config:
        config["local_addons_dir"] = os.path.expanduser("~/Library/Application Support/Blender/4.1/scripts/addons/")
        changed = True
    if "render_output_dir" not in config:
        config["render_output_dir"] = os.path.expanduser("~/Rendered")
        changed = True

    if changed:
        save_config(config)
        log("Config updated and saved.")

    return config

def auto_download(server_host, job_id, local_folder, log=default_log):
    remote_path = f"wys@{server_host}:~/render_jobs/{job_id}/"
    log(f"Attempting to auto-download render output from {remote_path}")
    os.makedirs(local_folder, exist_ok=True)

    try:
        rsync_cmd = ["rsync", "-avz", remote_path, f"{local_folder}/"]
        result = subprocess.run(rsync_cmd)
        if result.returncode == 0:
            log("Render output downloaded successfully.")
            return True
        else:
            raise Exception("rsync failed.")
    except Exception as e:
        log(f"Auto-download failed: {e}")
        log("To manually retrieve your render:")
        log(f"  rsync -avz {remote_path} {local_folder}/")
        return False

def send_render_job(
    blend_path,
    render_type="image",
    output_format="PNG",
    config=None,
    log=default_log,
):
    """
    Send the blend file to the remote render server.

    Parameters:
      - blend_path: full path to .blend file to render
      - render_type: "image" or "animation"
      - output_format: "PNG", "FFMPEG", "JPEG"
      - config: dict with keys:
         server_host, server_port, remote_addons_dir, local_addons_dir, render_output_dir
      - log: callable(msg) for logging output

    Returns:
      - job_id (str) if successful, None otherwise
    """

    config = ensure_config(config, log)
    SERVER_HOST = config["server_host"]
    SERVER_PORT = config["server_port"]
    LOCAL_ADDONS_DIR = config["local_addons_dir"]
    REMOTE_ADDONS_DIR = config["remote_addons_dir"]
    RENDER_OUTPUT_DIR = os.path.abspath(os.path.expanduser(config["render_output_dir"]))

    if not os.path.isfile(blend_path):
        log(f"Blend file does not exist: {blend_path}")
        return None

    blend_name = os.path.basename(blend_path)
    file_size = os.path.getsize(blend_path)

    # Sync add-ons
    log("Syncing Blender add-ons...")
    if os.path.exists(LOCAL_ADDONS_DIR):
        rsync_cmd = [
            "rsync", "-avz", LOCAL_ADDONS_DIR,
            f"wys@{SERVER_HOST}:{REMOTE_ADDONS_DIR}"
        ]
        result = subprocess.run(rsync_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            log("Add-on sync failed:")
            log(result.stderr)
        else:
            log("Add-ons synced.")
    else:
        log("Local add-ons directory not found.")

    # Connect & send
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

            buffer = ""
            job_id = None
            done_received = False
            while True:
                chunk = s.recv(1024)
                if not chunk:
                    # connexion fermée : traiter le dernier buffer s’il reste
                    if buffer:
                        lines = buffer.split("\n")
                        for line in lines:
                            log(f"[Server] {line.strip()}")
                    break
                decoded = chunk.decode(errors="ignore")
                print(f"[DEBUG received chunk]: {repr(decoded)}")

                decoded = chunk.decode(errors="ignore")
                buffer += decoded
                lines = buffer.split("\n")

                buffer = lines.pop() if not decoded.endswith("\n") else ""

                for line in lines:
                    line = line.strip()
                    log(f"[Server] {line}")  # afficher toutes les lignes reçues

                    if "Fra:" in line or "Rendering" in line:
                        log(f"[Blender] {line[:100]}")

                    elif line.startswith("QUEUED:"):
                        log(f"[Queue] {line}")

                    elif line.startswith("PROCESSING:"):
                        log(f"[Status] {line}")

                    if line.startswith("JOB_ID:"):
                        job_id = line.split(":", 1)[1].strip()
                        done_received = True
                        log(f"job_id={job_id}")

                    if "DONE: OK" in line or "DONE: ERROR" in line:
                        status = "success" if "DONE: OK" in line else "failure"
                        log(f"Render finished with status: {status}")
                        #break
                
                if done_received and job_id is not None:
                    log(f"done_received=True, job_id={job_id}")
                    
            if job_id is not None:
                output_folder = os.path.join(RENDER_OUTPUT_DIR, job_id)
                log(f"Render job {job_id} complete. Attempting to fetch results...")
                auto_download(SERVER_HOST, job_id, output_folder, log)
                return job_id
            else:
                log(f"No job ID received. Cannot download results. (value:{job_id})")
                return None

    except Exception as e:
        log(f"Connection error: {e}")
        return None
