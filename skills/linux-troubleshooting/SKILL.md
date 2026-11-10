---
name: linux-troubleshooting
description: Diagnose problems on a Linux machine - slowness, full disks, memory pressure, services that will not start, network and port issues. Use when the user says their Linux system, server or service is slow, hanging, out of space, crashing, unreachable or failing to start.
---

# Linux troubleshooting

Measure before changing anything. Most wrong fixes come from skipping the first step.

## First, get a snapshot

If you can run commands:

```
bash scripts/sysinfo.sh
```

It is read-only and needs no root. It shows: distro and kernel, load, memory and memory pressure, disk and inode usage (flagging anything over 80%), top processes by memory and CPU, GPU memory, failed systemd units, listening ports, recent error-level journal entries, and containers.

Otherwise ask the user to run it, or the specific command for the symptom below, and paste the output.

## By symptom

**Slow or hanging**
- Load average above the core count means a queue. `top` or `htop`: is it CPU (`us`/`sy`), disk wait (`wa`), or swapping?
- High `wa`: `iostat -x 2` or `iotop` to find the process hitting the disk.
- Low available memory with swap in use: the top memory process is the suspect. `journalctl -k | grep -i oom` shows whether the kernel killed something.

**Disk full**
- `df -h` for space, `df -i` for inodes. Either one at 100% gives "No space left on device".
- Find it: `sudo du -xh / --max-depth=2 2>/dev/null | sort -h | tail -20`.
- Usual culprits: logs (`journalctl --disk-usage`), package caches, container images and volumes, core dumps, a deleted file still held open (`sudo lsof +L1`).

**Service will not start**
- `systemctl status NAME` then `journalctl -u NAME -n 80 --no-pager`. The real error is usually a few lines above the "Failed" line.
- Check, in this order: wrong path or permission in the unit, port already in use (`ss -tlnp | grep PORT`), missing config or environment file, a dependency not running.

**Network or port**
- Is it listening? `ss -tlnp`. On `127.0.0.1` means local only; `0.0.0.0` means all interfaces.
- Reachable locally (`curl -v localhost:PORT`) but not remotely means a firewall or a bind address.
- DNS: `resolvectl status`, `dig name`. Route: `ip route`, `ping -c 3 gateway`.

**After an update or reboot**
- `journalctl -b -p err` for this boot, `journalctl -b -1 -p err` for the previous one.
- Kernel and driver mismatch (GPU modules especially) is common. Compare `uname -r` with the installed module versions.

## Rules

- **Read-only first.** Give diagnostic commands before any that change the system.
- **One change at a time**, with how to check that it worked and how to undo it.
- Before any `rm`, `kill -9`, `systemctl disable`, package removal or config edit: say exactly what it affects, and back up the config (`sudo cp file file.bak`).
- Do not suggest `chmod -R 777`, disabling the firewall or SELinux/AppArmor, or piping a download into a root shell as a fix.
- Commands differ between distros (apt, dnf, pacman, zypper). Check which one it is before giving package commands.
- If the evidence does not point to a cause, say what to measure next rather than guessing.

## Answer format

**What the numbers show**, **most likely cause** with the line that supports it, **next command to run** and what result would confirm it, then **the fix** once confirmed.
