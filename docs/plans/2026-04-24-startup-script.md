# TV News Analyzer 启动脚本 Implementation Plan

> **For agentic workers:** REQUIRED: Use `subagent-driven-development` (if subagents available) or `executing-plans` to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a single Bash script that can start, stop, inspect, and restart the news downloader and the web server.

**Architecture:** Keep the script at the repo root so it can resolve the project directory reliably from `BASH_SOURCE[0]`. The script manages two services independently, writing PID files and logs to `logs/`, while leaving all Python code unchanged.

**Tech Stack:** Bash, Python 3, current repo entrypoints.

---

### Task 1: Add the service manager script

**Files:**
- Create: `tvnews.sh`

- [ ] **Step 1: Write the script**

Implement `start`, `stop`, `status`, and `restart` for:
- `python3 -u run.py`
- `python3 -u web/server.py`

- [ ] **Step 2: Verify shell syntax**

Run: `bash -n tvnews.sh`
Expected: no output, exit code `0`

- [ ] **Step 3: Verify status path**

Run: `./tvnews.sh status`
Expected: reports both services as running or stopped without crashing

### Task 2: Update runtime docs

**Files:**
- Modify: `README.md`
- Modify: `.gitignore`

- [ ] **Step 1: Replace direct startup commands in README**

Document the new `./tvnews.sh` workflow and keep manual commands as fallback only if needed.

- [ ] **Step 2: Ignore PID files**

Add `logs/*.pid` so runtime metadata stays out of version control.

### Task 3: Validate end-to-end behavior

**Files:**
- No code changes expected

- [ ] **Step 1: Start services**

Run: `./tvnews.sh start`
Expected: both services start or are detected as already running

- [ ] **Step 2: Confirm status**

Run: `./tvnews.sh status`
Expected: both services are reported correctly with PIDs

- [ ] **Step 3: Stop services**

Run: `./tvnews.sh stop`
Expected: both services exit cleanly and PID files are removed

