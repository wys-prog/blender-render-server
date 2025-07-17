# blender-render-server

# Blender Render Server (Client/Server Setup)

This project provides a socket-based render server for Blender that accepts `.blend` files from remote clients, processes them using a local Blender installation, and returns the rendered outputs. It includes:

- A **Python server** to manage rendering requests.
- A **client script** to send `.blend` files and receive the render output.
- Support for **concurrent jobs**, **queueing**, and **auto-downloads** via `rsync`.

---

## Features

- Headless rendering of `.blend` files via Blender's CLI.
- Queue system with configurable concurrency (default: 2 parallel jobs).
- Blender auto-installation on the server if not available.
- Client config persistence across runs.
- Add-on directory syncing (useful for remote scripts or custom tools).
- Output download using `rsync`.

---

## Requirements

### Server:
- Python 3.7+
- Linux
- `curl`, `tar`, `rsync` must be available
- Internet connection (to install Blender automatically)

### Client:
- Python 3.7+
- Unix-based (macOS or Linux) or Windows with Python and `rsync` in PATH
- Blender file to render (`.blend`)

---

## Setup

### 1. Clone or copy the repository

```bash
git clone https://github.com/wys-prog/blender-render-server
cd blender-render-server
````

### 2. Server Setup

Run the server on your Linux machine:

```bash
python3 server.py
```

The server will:

* Install Blender into a local folder (`./BlenderServerInstance`)
* Create a job queue system
* Start listening on the configured `HOST:PORT`

You can adjust `MAX_CONCURRENT_JOBS`, `PORT`, or other constants inside `server.py`.

### 3. Client Setup

On any machine with Python and network access to the server:

```bash
python3 send_render_job.py <path_to_file.blend> [--animation] [--format PNG|FFMPEG|JPEG]
```

The script will:

* Ask for initial server configuration and cache it into `~/.render_client_config.json`
* Sync Blender add-ons to the server (optional)
* Send the `.blend` file to the server
* Stream logs and progress live
* Automatically download the rendered output once complete (via `rsync`)

---

## Example Usage

### Send a still image:

```bash
python3 send_render_job.py /path/to/my_scene.blend
```

### Send an animation render in JPEG format:

```bash
python3 send_render_job.py /path/to/scene.blend --animation --format JPEG
```

---

## Output

Rendered frames will be downloaded into:

```
~/Rendered/<JOB_ID>/
```

---

## Notes

* `rsync` is required for auto-download. If not available, the script will print the manual command to use.
* Job IDs are timestamped UUIDs (e.g., `20250717_150301_023894_a9b3e7f2`).
* Blender is downloaded from the official release site and extracted locally on the server.
* Server supports graceful shutdown via `CTRL+C`.
