#!/bin/bash
# Diagnostic wrapper — logs everything about how the process is spawned
LOG="/home/jbeck/.local/share/continuity/mcp-wrapper.log"
echo "=== $(date -Iseconds) ===" >> "$LOG"
echo "PID: $$" >> "$LOG"
echo "PPID: $PPID" >> "$LOG"
echo "PWD: $(pwd)" >> "$LOG"
echo "argv: $@" >> "$LOG"
echo "stdin isatty: $([ -t 0 ] && echo yes || echo no)" >> "$LOG"
echo "stdout isatty: $([ -t 1 ] && echo yes || echo no)" >> "$LOG"
echo "stderr isatty: $([ -t 2 ] && echo yes || echo no)" >> "$LOG"
ls -la /proc/$$/fd/ >> "$LOG" 2>&1
echo "--- env ---" >> "$LOG"
env | sort >> "$LOG"
echo "--- launching server ---" >> "$LOG"
exec /home/jbeck/git/continuity/.venv/bin/continuity-mcp "$@"
