---
name: incident-triage
description: Investigate a suspected compromise or suspicious activity on a host or account - what happened, how far it went, what to do first. Use when the user reports strange logins, unknown processes, alerts, malware, a hacked server or account, or pastes logs and asks "was I hacked".
---

# Incident triage

Preserve evidence, establish facts, then contain. Do not start by deleting things.

## 1. First questions

What was noticed, when, on which system, by whom? What has been done since? Is the system still running and still connected?

## 2. Preserve before changing

- Do not reboot or reinstall yet; memory and temporary files are lost.
- Save volatile data to another disk: process list, network connections, logged-in users, then logs.
- If the host is actively harming others or leaking data, isolate it from the network (pull the cable, security group) rather than power it off.

## 3. Look (Linux)

```
who; last -a | head -30; lastb | head
ps auxf; ss -tulpn; ss -tp
systemctl list-units --type=service --state=running; systemctl list-timers
crontab -l; ls -la /etc/cron.* /var/spool/cron
find / -xdev -mtime -7 -type f -not -path '/proc/*' 2>/dev/null | head -100
cat ~/.ssh/authorized_keys /root/.ssh/authorized_keys
journalctl --since "3 days ago" -u ssh | grep -E "Accepted|Failed"
ls -la /tmp /var/tmp /dev/shm
```

## 3. Look (Windows)

Event log ids: 4624 logon (type 3 network, type 10 remote desktop), 4625 failed logon, 4672 admin logon, 4688 process created, 4720 account created, 4732 added to group, 7045 service installed, 1102 log cleared. Check scheduled tasks, services, Run keys, startup folders, and local administrators.

## 4. Build a timeline

Order what you find by time: first sign, entry point, what ran, what was changed, what left the network. Mark each line as fact (with its source) or guess. The bundled `log-triage` skill helps with large logs.

## 5. Decide

- Scope: which hosts, accounts and data are affected.
- Contain: block the entry point, disable affected accounts, rotate every credential that was on the host.
- Recover: rebuild from a clean source when root or SYSTEM was reached; cleaning a rooted host cannot be trusted.
- Report: legal or contractual duties to notify, if personal data is involved.

## How to answer

Say what the evidence shows and how sure it is. Separate "confirmed", "likely" and "unknown". Give the next two or three commands and what to look for in their output. Many alarms are harmless; say so when the evidence points that way.
