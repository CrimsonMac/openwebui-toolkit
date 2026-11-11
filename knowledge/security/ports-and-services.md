# Common ports and what to check on each

Reference for network enumeration in authorized security testing. For each port: the usual service and the first things to check.

## Remote access and file transfer

| Port | Service | First checks |
|---|---|---|
| 21/tcp | FTP | Anonymous login (`anonymous` / any password), writable folders, version banner, cleartext credentials |
| 22/tcp | SSH | Version banner, allowed auth methods (`ssh -v`), key reuse, weak or default passwords only if in scope |
| 23/tcp | Telnet | Cleartext login, default credentials on devices |
| 69/udp | TFTP | No authentication; try fetching config files by known names |
| 873/tcp | rsync | `rsync rsync://HOST/` lists modules; modules without password |
| 2049/tcp | NFS | `showmount -e HOST`; exports to everyone, `no_root_squash` |
| 3389/tcp | RDP | NLA enabled or not, valid users, known vulnerabilities by OS version |
| 5900/tcp | VNC | No password or weak password |
| 5985, 5986/tcp | WinRM | Remote shell with valid credentials (`evil-winrm`) |

## Mail

| Port | Service | First checks |
|---|---|---|
| 25, 465, 587/tcp | SMTP | Open relay, user enumeration with `VRFY`, `EXPN`, `RCPT TO` |
| 110, 995/tcp | POP3 | Cleartext login on 110, credential reuse |
| 143, 993/tcp | IMAP | Cleartext login on 143, credential reuse |

## Name, directory and time services

| Port | Service | First checks |
|---|---|---|
| 53/tcp+udp | DNS | Zone transfer `dig axfr @HOST domain`, subdomain brute force, version |
| 88/tcp | Kerberos | Marks a domain controller. User enumeration, AS-REP roasting, Kerberoasting |
| 111/tcp+udp | rpcbind | `rpcinfo -p HOST` lists RPC services such as NFS |
| 123/udp | NTP | Time offset matters for Kerberos (must be within 5 minutes) |
| 135/tcp | MS-RPC | Endpoint mapper; `rpcclient -U '' -N HOST` |
| 137-139/tcp+udp | NetBIOS | Names and shares; `nbtscan`, `enum4linux-ng` |
| 161/udp | SNMP | Community strings `public`, `private`; `snmpwalk -v2c -c public HOST` gives users, processes, interfaces |
| 389, 636/tcp | LDAP, LDAPS | Anonymous bind: `ldapsearch -x -H ldap://HOST -s base namingcontexts`; users and descriptions |
| 445/tcp | SMB | Null session, shares (`smbclient -L //HOST -N`), signing required or not, OS version |
| 3268, 3269/tcp | Global Catalog | LDAP across the forest on a domain controller |

## Web and proxies

| Port | Service | First checks |
|---|---|---|
| 80, 443, 8080, 8443, 8000, 8888/tcp | HTTP(S) | Technology, directories, virtual hosts, default pages, admin panels, certificate names |
| 3128/tcp | Squid proxy | Open proxy; reach internal hosts through it |
| 8009/tcp | AJP | Tomcat connector; Ghostcat on old versions |
| 9200/tcp | Elasticsearch | No authentication; `/_cat/indices` |
| 5601/tcp | Kibana | Version, unauthenticated access |
| 2375/tcp | Docker API | Unauthenticated API gives root on the host |
| 6443, 10250/tcp | Kubernetes API, kubelet | Anonymous access, exposed pods and exec |

## Databases and caches

| Port | Service | First checks |
|---|---|---|
| 1433/tcp | MS SQL Server | Default `sa` account, `xp_cmdshell`, linked servers |
| 1521/tcp | Oracle | SID enumeration, default accounts |
| 3306/tcp | MySQL, MariaDB | Root without password, remote root allowed, `FILE` privilege |
| 5432/tcp | PostgreSQL | Default `postgres` account, `COPY ... PROGRAM` for superusers |
| 6379/tcp | Redis | No authentication; `INFO`, config write to disk |
| 11211/tcp | Memcached | No authentication; `stats`, cached session data |
| 27017/tcp | MongoDB | No authentication; list databases |

## Other

| Port | Service | First checks |
|---|---|---|
| 500/udp | IKE (IPsec VPN) | Aggressive mode leaks a crackable hash |
| 623/udp | IPMI | Cipher 0, hash disclosure (RAKP) |
| 1883/tcp | MQTT | No authentication; subscribe to `#` |
| 5000/tcp | Many dev servers, Docker registry | `/v2/_catalog` on a registry |
| 9100/tcp | Printer (JetDirect) | Printer job language access |
