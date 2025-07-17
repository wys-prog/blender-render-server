import socket
import threading
import os
import datetime
import subprocess
import time
import shutil
import signal
import sys
import queue
import uuid

# === CONFIGURATION ===
HOST = "0.0.0.0"
PORT = 5555
RENDER_ROOT = os.path.expanduser("~/render_jobs")
BLENDER_DOWNLOAD_URL = "https://ftp.nluug.nl/pub/graphics/blender/release/Blender4.0/blender-4.0.2-linux-x64.tar.xz"
BLENDER_INSTANCE_DIR = os.path.abspath("BlenderServerInstance")
BLENDER_PATH = os.path.join(BLENDER_INSTANCE_DIR, "blender")
MAX_CONCURRENT_JOBS = 2
job_queue = queue.Queue()

active_connections = []
shutdown_requested = False

# === LOG UTILS ===
def step(msg): print(f"\n@STEP: {msg}")
def info(msg): print(f"   ↳ {msg}")
def success(msg): print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] @SUCCESS: {msg}")
def error(msg): print(f"\n[{datetime.datetime.now().strftime('%H:%M:%S')}] @ERROR:\n>>{msg}")
def verbose(msg): print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}")
def shutdown_log(msg): print(f"@SHUTDOWN: {msg}")

# === INSTALL BLENDER LOCALLY ===
def install_blender():
    step("Installing Blender to local server instance")
    if os.path.exists(BLENDER_INSTANCE_DIR):
        shutil.rmtree(BLENDER_INSTANCE_DIR)
    os.makedirs(BLENDER_INSTANCE_DIR, exist_ok=True)

    archive_path = os.path.join(BLENDER_INSTANCE_DIR, "blender.tar.xz")
    info("Downloading Blender...")
    result = subprocess.run([
        "curl", "-L", "-o", archive_path, BLENDER_DOWNLOAD_URL
    ], capture_output=True)
    if result.returncode != 0:
        error("Failed to download Blender.")
        exit(1)

    info("Extracting Blender...")
    result = subprocess.run([
        "tar", "-xf", archive_path, "--strip-components=1", "-C", BLENDER_INSTANCE_DIR
    ], capture_output=True)
    if result.returncode != 0:
        error("Failed to extract Blender.")
        exit(1)

    blender_bin = os.path.join(BLENDER_INSTANCE_DIR, "blender")
    if not os.path.isfile(blender_bin):
        error("Blender binary not found after extraction.")
        exit(1)
    os.chmod(blender_bin, 0o755)
    success("Blender installed successfully.")

# === CLEANUP ===
def cleanup():
    shutdown_log("Cleaning up server state...")
    shutdown_log("Closing all active connections.")
    for conn in active_connections:
        try:
            conn.sendall(b"ERR: Server Stop Requested\n")
            conn.close()
        except:
            pass

    shutdown_log("Removing BlenderServerInstance folder.")
    try:
        shutil.rmtree(BLENDER_INSTANCE_DIR)
    except Exception as e:
        shutdown_log(f"Failed to remove Blender instance: {e}")

    shutdown_log("Shutdown complete.")

# === HANDLE CTRL+C ===
def handle_shutdown(signum, frame):
    global shutdown_requested
    shutdown_requested = True
    shutdown_log("KeyboardInterrupt received. Shutting down...")
    cleanup()
    os._exit(0)

signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)

# === CLIENT HANDLING ===
def handle_client(conn, addr):
    if shutdown_requested:
        conn.sendall(b"ERR: Server not accepting connections.\n")
        conn.close()
        return

    active_connections.append(conn)
    job_data = {
        "conn": conn,
        "addr": addr,
        "timestamp": datetime.datetime.now()
    }
    job_queue.put(job_data)
    position = job_queue.qsize()
    verbose(f"Job queued from {addr}, position {position}")
    try:
        conn.sendall(f"QUEUED: Your request has been added to the queue. Current position: {position}\n".encode())
    except:
        conn.close()

# === SERVER SETUP ===
def start_server():
    step("Starting Render Server Setup")
    install_blender()

    step("Creating render job output root")
    os.makedirs(RENDER_ROOT, exist_ok=True)
    success(f"Render root ready: {RENDER_ROOT}")

    print("\n@READY: RenderServer running on", f"{HOST}:{PORT}")
    print("========================================")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, PORT))
        s.listen()
        while not shutdown_requested:
            try:
                conn, addr = s.accept()
                threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()
            except Exception as e:
                verbose(f"Socket error: {e}")

def process_render_job(conn, addr):
    try:
        buffer = b""
        while b"===END===\n" not in buffer:
            chunk = conn.recv(1024)
            if not chunk:
                raise Exception("Client disconnected before sending header.")
            buffer += chunk

        header_data, remaining = buffer.split(b"===END===\n", 1)
        header_lines = header_data.decode().strip().split("\n")
        if len(header_lines) < 4:
            conn.send(b"ERR: Invalid header format.\n")
            verbose("Invalid header format.")
            return

        blend_name = header_lines[0]
        render_type = header_lines[1]
        file_size = int(header_lines[2])
        output_format = header_lines[3].upper()

        job_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_" + str(uuid.uuid4())[:8]
        job_dir = os.path.join(RENDER_ROOT, job_id)
        os.makedirs(job_dir, exist_ok=True)
        blend_path = os.path.join(job_dir, blend_name)

        with open(blend_path, "wb") as f:
            f.write(remaining)
            received = len(remaining)
            while received < file_size:
                chunk = conn.recv(min(4096, file_size - received))
                if not chunk:
                    break
                f.write(chunk)
                received += len(chunk)

        verbose(f"Blend file received: {blend_path}")
        output_path = os.path.join(job_dir, "frame_#####")

        render_cmd = [
            BLENDER_PATH, "-b", blend_path,
            "-o", output_path,
            "-F", output_format,
        ]
        if render_type == "animation":
            render_cmd.append("-a")
        else:
            render_cmd += ["-f", "1"]

        conn.sendall(b"PROCESSING: Your job is now rendering.\n")

        verbose(f"Launching Blender render job: {' '.join(render_cmd)}")
        proc = subprocess.Popen(render_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

        current_line = ""
        for line in proc.stdout:
            if shutdown_requested:
                conn.sendall(b"ERR: Server Stop Requested\n")
                break

            try:
                conn.send(line.encode())
            except Exception as e:
                verbose(f"Failed to send log line: {e}")
                break

            line_clean = line.strip()
            if "Fra:" in line_clean or "Rendering" in line_clean:
                current_line = line_clean
                sys.stdout.write(f"\r[SERVER] {current_line[:80]:<80}")
                sys.stdout.flush()
            elif "Saved:" in line_clean:
                sys.stdout.write(f"\r[SERVER] {line_clean[:80]:<80}\n")
                sys.stdout.flush()

        proc.wait()

        if proc.returncode == 0:
            sys.stdout.write("\n")
            verbose("Render completed successfully.")
            conn.send(f"\nDONE: OK\nJOB_ID:{job_id}\n".encode())
        else:
            sys.stdout.write("\n")
            verbose("Render failed.")
            conn.send(f"\nDONE: ERROR\nJOB_ID:{job_id}\n".encode())

    except Exception as e:
        verbose(f"Exception: {e}")
        try:
            conn.send(f"ERR: {e}\n".encode())
        except:
            pass
    finally:
        if conn in active_connections:
            active_connections.remove(conn)
        conn.close()


def render_worker():
    while not shutdown_requested:
        try:
            job_data = job_queue.get(timeout=1)
        except queue.Empty:
            continue

        conn = job_data["conn"]
        addr = job_data["addr"]
        process_render_job(conn, addr)
        job_queue.task_done()

for _ in range(MAX_CONCURRENT_JOBS):
    threading.Thread(target=render_worker, daemon=True).start()

if __name__ == "__main__":
    start_server()