---
name: privilege-escalation
description: Find a way from a low-privileged shell to root or SYSTEM on a Linux or Windows host during an authorized test or CTF. Use when the user has a shell or command output (id, sudo -l, whoami /priv, linpeas, winpeas) and asks how to escalate.
---

# Privilege escalation

Enumerate first, then pick the simplest path. Ask for command output; do not guess what the system looks like.

## Linux: run these and read them

```
id; hostname; uname -a; cat /etc/os-release
sudo -l
find / -perm -4000 -type f 2>/dev/null
getcap -r / 2>/dev/null
cat /etc/crontab; ls -la /etc/cron.*; systemctl list-timers
ps aux | grep -v '\]$'
ss -tlnp
ls -la /home /root /opt /var/backups /srv 2>/dev/null
find / -writable -type f -not -path '/proc/*' -not -path '/sys/*' 2>/dev/null | head -50
env; cat ~/.bash_history
```

What to look for, most common first:

1. `sudo -l`: a command allowed without password. Check GTFOBins for it. `env_keep` with `LD_PRELOAD`, or a wildcard in the allowed command line.
2. SUID/SGID binary that is not standard for the distribution, or one listed on GTFOBins.
3. Cron job or systemd unit running as root that uses a file, folder or `PATH` entry you can write.
4. Credentials: config files, history, backups, `.git`, database dumps, environment variables. Try them with `su` and on other services.
5. Group membership: `docker`, `lxd`, `disk`, `adm`, `sudo`.
6. Capabilities such as `cap_setuid` on an interpreter.
7. Services listening on localhost only, running as root.
8. Writable `/etc/passwd`, `/etc/shadow`, or a writable script in a root-owned service.
9. Kernel exploit, last, and only if the kernel version is clearly affected. It can crash the host; say so.

## Windows: run these and read them

```
whoami /all
systeminfo
net user; net localgroup administrators
cmdkey /list
sc query state= all; wmic service get name,pathname,startmode
schtasks /query /fo LIST /v
reg query HKLM\SOFTWARE\Policies\Microsoft\Windows\Installer /v AlwaysInstallElevated
dir /a C:\Users\*\AppData\Roaming\Microsoft\Windows\PowerShell\PSReadLine\
```

What to look for:

1. Privileges: `SeImpersonatePrivilege` or `SeAssignPrimaryToken` (potato-family attacks), `SeBackupPrivilege`, `SeDebugPrivilege`.
2. Services: unquoted path with spaces, a binary or folder you can write, a service you can reconfigure.
3. Stored credentials: `cmdkey`, PowerShell history, unattend files, registry autologon, config files.
4. `AlwaysInstallElevated` set in both HKLM and HKCU.
5. Scheduled tasks running as SYSTEM from a writable path.
6. Missing patches, last.

## How to answer

Name the one or two most promising findings in the output, explain why each works, and give the exact commands. Mention what the step changes on the system so it can be reverted and reported.
