#!/usr/bin/env node
// Runs automatically after `npm install`. This package is a Node/npm
// wrapper around a Python app -- npm can't install Python dependencies
// itself, so this script finds a suitable Python, builds a private
// virtualenv inside this package, and installs the Python requirements
// into it. bin/talk-and-type.js then runs that venv's Python directly.
"use strict";

const { spawnSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const PACKAGE_ROOT = path.join(__dirname, "..");
const VENV_DIR = path.join(PACKAGE_ROOT, "venv");
const REQUIREMENTS = path.join(PACKAGE_ROOT, "requirements.txt");

const CANDIDATE_PYTHONS = [
  "python3.13",
  "python3.12",
  "python3.11",
  "/opt/homebrew/bin/python3.13",
  "/opt/homebrew/bin/python3.12",
  "/opt/homebrew/bin/python3.11",
  "/usr/local/bin/python3.13",
  "/usr/local/bin/python3.12",
  "/usr/local/bin/python3.11",
];

function fail(message) {
  console.error(`\ntalk-and-type install failed: ${message}\n`);
  process.exit(1);
}

function run(command, args, options = {}) {
  return spawnSync(command, args, { stdio: "inherit", ...options });
}

function getVersion(pythonPath) {
  const result = spawnSync(pythonPath, ["-c", "import sys; print('%d.%d' % sys.version_info[:2])"]);
  if (result.status !== 0 || !result.stdout) return null;
  return result.stdout.toString().trim();
}

function findPython311Plus() {
  for (const candidate of CANDIDATE_PYTHONS) {
    const version = getVersion(candidate);
    if (!version) continue;
    const [major, minor] = version.split(".").map(Number);
    if (major > 3 || (major === 3 && minor >= 11)) {
      return candidate;
    }
  }
  return null;
}

function main() {
  if (process.platform !== "darwin") {
    fail("this tool only works on macOS (it relies on macOS-specific APIs for hotkeys, audio, and text insertion).");
  }

  console.log("Looking for Python 3.11 or newer...");
  const python = findPython311Plus();
  if (!python) {
    fail(
      "couldn't find Python 3.11+ on this Mac.\n" +
        "  Install it with:  brew install python@3.11\n" +
        "  Then run:         npm install"
    );
  }
  console.log(`Using ${python}`);

  if (!fs.existsSync(VENV_DIR)) {
    console.log("Creating a private virtual environment for this package...");
    const venvResult = run(python, ["-m", "venv", VENV_DIR]);
    if (venvResult.status !== 0) {
      fail("failed to create the Python virtual environment.");
    }
  } else {
    console.log("Virtual environment already exists, reusing it.");
  }

  const venvPip = path.join(VENV_DIR, "bin", "pip");
  console.log("Installing Python dependencies (this can take a minute, especially faster-whisper)...");
  const upgradeResult = run(venvPip, ["install", "--upgrade", "pip", "-q"]);
  if (upgradeResult.status !== 0) {
    fail("failed to upgrade pip inside the virtual environment.");
  }
  const installResult = run(venvPip, ["install", "-r", REQUIREMENTS, "-q"]);
  if (installResult.status !== 0) {
    fail("failed to install Python dependencies from requirements.txt.");
  }

  console.log("\nInstalled successfully.\n");
  console.log("Before running it, this Mac needs to grant three permissions to");
  console.log("whatever app runs `talk-and-type` (Terminal, iTerm, etc.):");
  console.log("  - Microphone");
  console.log("  - Accessibility");
  console.log("  - Input Monitoring");
  console.log("\nRun `talk-and-type` and it'll tell you exactly what's missing.\n");
}

main();
