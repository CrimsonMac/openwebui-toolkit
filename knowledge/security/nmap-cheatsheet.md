# Nmap cheat sheet

Reference for port scanning in authorized tests. Scanning hosts without permission is illegal in many places.

## Scan types

| Option | Meaning |
|---|---|
| `-sS` | TCP SYN scan (default as root). Fast, does not complete the handshake |
| `-sT` | TCP connect scan (default without root) |
| `-sU` | UDP scan. Slow; limit it with `--top-ports` |
| `-sV` | Detect service and version on open ports |
| `-sC` | Run the default scripts (same as `--script=default`) |
| `-O` | Guess the operating system (needs root) |
| `-A` | `-O -sV -sC --traceroute` together |
| `-sn` | Host discovery only, no port scan ("ping sweep") |
| `-Pn` | Skip host discovery and treat every host as up. Needed when ping is blocked |

## Choosing ports

| Option | Meaning |
|---|---|
| (none) | The 1000 most common TCP ports |
| `-p-` | All 65535 TCP ports |
| `-p 22,80,443` or `-p 1-1024` | Listed ports or a range |
| `--top-ports 100` | The N most common ports |
| `-F` | Fast: the 100 most common ports |

## Speed

| Option | Meaning |
|---|---|
| `-T0` to `-T5` | Timing template. `-T3` is the default, `-T4` suits fast reliable networks |
| `--min-rate 1000` | Send at least this many packets per second |
| `--max-retries 1` | Fewer retries; faster but may miss ports on lossy links |

## Output

| Option | Meaning |
|---|---|
| `-oN file` | Normal text |
| `-oG file` | Greppable |
| `-oX file` | XML |
| `-oA name` | All three, as `name.nmap`, `name.gnmap`, `name.xml` |
| `-v`, `-vv` | Show open ports as they are found |
| `--open` | List only open ports |
| `--reason` | Say why a port has its state |

## Port states

- `open`: a service accepted the connection.
- `closed`: reachable, nothing listening.
- `filtered`: no answer; a firewall drops the probes.
- `open|filtered`: common for UDP; no answer can mean either.

## Scripts (NSE)

```
nmap --script vuln -p 80,443 HOST          # known-vulnerability checks
nmap --script "smb-enum-*" -p 445 HOST     # SMB shares, users
nmap --script http-enum -p 80 HOST         # common web paths
nmap --script ssl-enum-ciphers -p 443 HOST # TLS versions and ciphers
nmap --script-help "smb-*"                 # what a script does
```

Categories: `default`, `safe`, `discovery`, `version`, `vuln`, `auth`, `brute`, `intrusive`, `exploit`, `dos`. Avoid `dos`, and use `brute` and `intrusive` only when the scope allows.

## Usual sequence

```
nmap -sn 10.10.10.0/24 -oA hosts                       # which hosts are up
nmap -p- --min-rate 2000 -Pn -oA allports HOST         # every TCP port
nmap -sC -sV -p 22,80,445 -oA detail HOST              # detail on the open ones
nmap -sU --top-ports 25 -oA udp HOST                   # common UDP
```

Get the open ports out of a greppable file for the next scan:

```
grep -oP '\d+/open' allports.gnmap | cut -d/ -f1 | sort -un | paste -sd,
```
