# Linux privilege escalation reference

For authorized tests and CTFs. Each section: how to spot the weakness and how it is used. GTFOBins (gtfobins.github.io) lists the abuse for individual binaries.

## sudo

`sudo -l` shows what the user may run.

- `(ALL) NOPASSWD: /usr/bin/vim` and similar: many programs can start a shell. Examples: `sudo vim -c ':!/bin/sh'`, `sudo find . -exec /bin/sh \; -quit`, `sudo awk 'BEGIN {system("/bin/sh")}'`, `sudo less /etc/hosts` then `!/bin/sh`, `sudo env /bin/sh`, `sudo python3 -c 'import os; os.system("/bin/sh")'`, `sudo tar -cf /dev/null /dev/null --checkpoint=1 --checkpoint-action=exec=/bin/sh`.
- `env_keep+=LD_PRELOAD`: compile a shared object whose init function calls `setuid(0)` and starts a shell, then `sudo LD_PRELOAD=/tmp/x.so ALLOWED_COMMAND`.
- A script you can edit, or a script in a folder you can write, allowed through sudo.
- A wildcard in the allowed command line, which lets you add arguments.
- `sudo -V`: old sudo versions have known flaws (for example CVE-2021-3156 before 1.9.5p2).

## SUID and SGID binaries

`find / -perm -4000 -type f 2>/dev/null` (SUID), `-perm -2000` (SGID).

- Compare with a clean install; anything unusual or custom deserves a look.
- Standard tools with SUID set by mistake: `find`, `vim`, `bash` (`bash -p`), `cp`, `nmap` (old), `python`.
- Custom SUID programs: run `strings` and `ltrace` on them; look for commands called without a full path (put your own program earlier in `PATH`), and for unsafe input handling.

## Capabilities

`getcap -r / 2>/dev/null`. `cap_setuid+ep` on an interpreter gives root: `python3 -c 'import os; os.setuid(0); os.system("/bin/sh")'`. `cap_dac_read_search` lets a program read any file.

## Cron jobs and timers

`cat /etc/crontab`, `ls -la /etc/cron.d /etc/cron.daily`, `systemctl list-timers`. Watch for processes that appear on a schedule with `pspy`.

- A root job runs a script you can write: add your command.
- A root job uses a relative command and `PATH` in the crontab includes a folder you can write.
- A root job uses a wildcard, for example `tar czf backup.tgz *` in a folder you can write: file names such as `--checkpoint=1` and `--checkpoint-action=exec=sh x.sh` are read as options.

## Writable sensitive files

- `/etc/passwd` writable: add a line with UID 0 and a hash from `openssl passwd -6 PASSWORD`.
- `/etc/shadow` readable: copy the hashes and crack them offline. Writable: replace root's hash.
- `/etc/sudoers` or a file in `/etc/sudoers.d` writable.
- A systemd unit file or the program it starts is writable: change `ExecStart`, then wait for a restart.

## Groups

- `docker`: `docker run -v /:/mnt --rm -it alpine chroot /mnt sh` gives root on the host.
- `lxd` / `lxc`: start a privileged container with the host disk mounted.
- `disk`: read raw devices with `debugfs /dev/sda1`.
- `adm`: read logs in `/var/log`, which may hold credentials.
- `shadow`: read `/etc/shadow`.

## Credentials lying around

Shell history, `.git` folders and old commits, configuration files of web apps (`wp-config.php`, `.env`, `settings.py`), database dumps, backup archives, SSH keys in home folders and `/root` backups, `/var/mail`, environment of running processes (`/proc/PID/environ`). Try every password found with `su` for each local user.

## Services on localhost

`ss -tlnp` shows listeners. A database, admin panel or debug port bound to 127.0.0.1 and running as root can be reached after a port forward: `ssh -L 8080:127.0.0.1:8080 user@host`.

## NFS

`cat /etc/exports`. An export with `no_root_squash` lets root on a client create a SUID root file on the share.

## Kernel

`uname -r` and the distribution release. Use a kernel exploit last: it can crash the machine. Well-known ones: Dirty COW (CVE-2016-5195, kernels before late 2016), Dirty Pipe (CVE-2022-0847, 5.8 up to 5.16.11 / 5.15.25 / 5.10.102), PwnKit in polkit's pkexec (CVE-2021-4034, a userland SUID bug present from 2009 to January 2022).

## Automated enumeration

`linpeas.sh` prints everything above with likely findings highlighted. `pspy` shows processes of other users without root. Read their output critically; highlighted does not mean exploitable.
