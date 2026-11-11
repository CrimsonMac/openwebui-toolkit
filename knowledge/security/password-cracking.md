# Password hash cracking reference (hashcat and John the Ripper)

For recovering passwords from hashes obtained in an authorized test, a CTF, or from your own systems.

## Identify the hash first

By prefix:

| Looks like | Type | hashcat mode |
|---|---|---|
| `$1$...` | md5crypt | 500 |
| `$2a$`, `$2b$`, `$2y$` | bcrypt | 3200 |
| `$5$...` | sha256crypt | 7400 |
| `$6$...` | sha512crypt (Linux `/etc/shadow`) | 1800 |
| `$y$...` | yescrypt (newer Linux) | use John the Ripper |
| `$apr1$...` | Apache MD5 | 1600 |
| `$P$...`, `$H$...` | phpass (WordPress, phpBB) | 400 |
| `$krb5tgs$23$...` | Kerberoast (TGS-REP, RC4) | 13100 |
| `$krb5asrep$23$...` | AS-REP roast | 18200 |
| `user::domain:challenge:...` | NetNTLMv2 | 5600 |
| `$office$...` | MS Office document | 9400 to 9600 by version |
| `$pdf$...` | PDF | 10400 to 10700 by version |
| `$keepass$...` | KeePass database | 13400 |
| `$7z$...` | 7-Zip archive | 11600 |
| `$rar5$...` | RAR5 archive | 13000 |
| three Base64url parts with dots, starting `eyJ` | JWT (HMAC) | 16500 |

By length, hex only:

| Length | Type | hashcat mode |
|---|---|---|
| 32 | MD5 | 0 |
| 32 | NTLM (from Windows) | 1000 |
| 40 | SHA-1 | 100 |
| 64 | SHA-256 | 1400 |
| 128 | SHA-512 | 1700 |

Other common modes: 3000 LM, 5500 NetNTLMv1, 1100 domain cached credentials (DCC), 2100 DCC2, 22000 WPA/WPA2, 300 MySQL 4.1+, 1500 DES crypt, 10 `md5($pass.$salt)`, 20 `md5($salt.$pass)`.

`hashcat --help | grep -i NAME` and `hashcat --example-hashes` show every mode with a sample.

## hashcat

```
hashcat -m MODE -a 0 hashes.txt rockyou.txt                 # wordlist
hashcat -m MODE -a 0 hashes.txt rockyou.txt -r rules/best64.rule   # wordlist + rules
hashcat -m MODE -a 3 hashes.txt '?u?l?l?l?l?d?d?d'          # mask (brute force by pattern)
hashcat -m MODE -a 6 hashes.txt words.txt '?d?d?d?d'        # word + mask
hashcat -m MODE -a 7 hashes.txt '?d?d' words.txt            # mask + word
hashcat -m MODE -a 1 hashes.txt left.txt right.txt          # combine two lists
hashcat -m MODE hashes.txt --show                           # print cracked ones
```

Mask characters: `?l` a-z, `?u` A-Z, `?d` 0-9, `?s` symbols, `?a` all of these, `?b` any byte. Custom set: `-1 ?l?d` then use `?1`. Add `--increment` to try shorter lengths first.

Useful options: `-O` optimised kernels (faster, shorter maximum length), `-w 3` higher workload, `--username` when lines look like `user:hash`, `--session NAME` and `--restore` to resume, `--status`.

## John the Ripper

```
john --wordlist=rockyou.txt hashes.txt
john --wordlist=rockyou.txt --rules=Jumbo hashes.txt
john --format=nt hashes.txt
john --show hashes.txt
john --list=formats | tr ',' '\n' | grep -i NAME
```

Conversion helpers turn files into crackable hashes: `zip2john`, `rar2john`, `7z2john`, `pdf2john`, `office2john`, `keepass2john`, `ssh2john` (private key passphrase), `gpg2john`. Combine Linux files with `unshadow passwd shadow > hashes.txt`.

## Strategy

1. Quick wins: a common wordlist such as rockyou, no rules.
2. Same list with rules (`best64`, then `OneRuleToRuleThemAll` or `dive`).
3. Targeted words: company name, product names, seasons and years, usernames, words from the website (`cewl URL -w words.txt`), with rules.
4. Masks for known policies, for example capital first, digits and a symbol at the end: `?u?l?l?l?l?l?d?d?s`.
5. Stop and consider whether the hash is worth it: bcrypt, sha512crypt, yescrypt, Argon2 and KeePass are slow by design; long random passwords will not fall.

Speed for orientation, single modern GPU: MD5 and NTLM tens of billions per second, SHA-256 several billions, NetNTLMv2 around a billion or more, sha512crypt hundreds of thousands, bcrypt (cost 5) tens of thousands and far fewer at realistic costs.

## Online brute force is different

Guessing against a live login (hydra, medusa, netexec) is slow, noisy and can lock accounts. Check the lockout policy and the scope first, and prefer a short list of likely passwords over a large wordlist.
