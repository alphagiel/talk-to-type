#!/usr/bin/env node
// The actual `talk-to-type` command. All the real logic is Python --
// this just finds the private virtualenv postinstall.js built and runs
// the app inside it, passing through stdio so you see the same console
// output you'd get running Python directly.
"use strict";

const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

const PACKAGE_ROOT = path.join(__dirname, "..");
const VENV_PYTHON = path.join(PACKAGE_ROOT, "venv", "bin", "python");

if (!fs.existsSync(VENV_PYTHON)) {
  console.error(
    "Python environment not found. Try reinstalling with `npm install`\n" +
      "(this runs the postinstall step that sets up Python and its dependencies)."
  );
  process.exit(1);
}

const child = spawn(VENV_PYTHON, ["-m", "ptt_dictation.main"], {
  cwd: PACKAGE_ROOT,
  stdio: "inherit",
});

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
  } else {
    process.exit(code === null ? 1 : code);
  }
});

for (const sig of ["SIGINT", "SIGTERM"]) {
  process.on(sig, () => child.kill(sig));
}
