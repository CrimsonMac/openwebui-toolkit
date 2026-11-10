#!/usr/bin/env bash
# Read-only snapshot of a Linux system for troubleshooting. Changes nothing, needs no root.
# Usage: sysinfo.sh
set -u
section() { printf '\n== %s ==\n' "$1"; }
have() { command -v "$1" >/dev/null 2>&1; }

section "system"
. /etc/os-release 2>/dev/null && echo "${PRETTY_NAME:-unknown distro}"
echo "kernel $(uname -r), $(uname -m)"
uptime 2>/dev/null

section "cpu and load"
grep -m1 'model name' /proc/cpuinfo 2>/dev/null | cut -d: -f2- | sed 's/^ //'
echo "cores: $(nproc 2>/dev/null)   load (1/5/15 min): $(cut -d' ' -f1-3 /proc/loadavg 2>/dev/null)"

section "memory"
free -h 2>/dev/null
if [ -r /proc/pressure/memory ]; then echo "memory pressure: $(head -1 /proc/pressure/memory)"; fi

section "disks (over 80% is flagged)"
df -h -x tmpfs -x devtmpfs -x squashfs -x overlay 2>/dev/null | awk 'NR==1 {print; next} {u=$5; sub("%","",u); print $0 (u+0>=80 ? "   <-- nearly full" : "")}'
df -i -x tmpfs -x devtmpfs -x squashfs 2>/dev/null | awk 'NR>1 {u=$5; sub("%","",u); if (u+0>=80) print "inodes nearly exhausted on " $6 " (" $5 ")"}'

section "top processes by memory"
ps -eo pid,user,%mem,%cpu,rss,comm --sort=-%mem 2>/dev/null | head -8

section "top processes by cpu"
ps -eo pid,user,%cpu,%mem,comm --sort=-%cpu 2>/dev/null | head -6

if have nvidia-smi; then
  section "gpu (nvidia)"
  nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu --format=csv,noheader 2>/dev/null
elif have rocm-smi; then
  section "gpu (amd)"
  rocm-smi --showmeminfo vram --showuse 2>/dev/null | grep -v '^=' | head -12
fi

if have systemctl; then
  section "failed systemd units"
  failed=$(systemctl --failed --no-legend --plain 2>/dev/null)
  [ -n "$failed" ] && echo "$failed" || echo "none"
fi

section "listening ports"
if have ss; then ss -tlnH 2>/dev/null | awk '{print $4}' | sort -u | head -25; else echo "ss not available"; fi

section "recent kernel and service errors"
if have journalctl; then
  journalctl -p err -b --no-pager -n 15 -o short 2>/dev/null | cut -c1-200 | head -20 || echo "journal not readable without more permissions"
else
  dmesg 2>/dev/null | tail -15 || echo "dmesg not readable without root"
fi

if have docker; then
  section "docker containers"
  docker ps -a --format '{{.Names}}\t{{.Status}}\t{{.Image}}' 2>/dev/null | head -20 || echo "docker not accessible for this user"
fi
