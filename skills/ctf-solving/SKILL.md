---
name: ctf-solving
description: Solve capture-the-flag challenges methodically - web, crypto, reversing, binary exploitation (pwn), forensics, steganography, OSINT. Use when the user shares a CTF task, a challenge file, a ciphertext, a binary or a pcap and wants help finding the flag.
---

# CTF solving

A CTF task is built to be solved, so there is an intended path. Find what kind of task it is, collect facts cheaply, then form one hypothesis at a time.

## First minutes

1. Read the title, description, points and flag format; hints hide there.
2. Identify every file: `file X`, `strings -n 6 X | head -50`, `xxd X | head`, `binwalk X`, `exiftool X`.
3. Say which category it is and what the likely intended technique is.

## By category

- **Crypto**: identify the scheme from the shape of the data. Encoded, not encrypted? Use the `decode_text` tool if available. Classical cipher: frequency analysis, known flag prefix as crib. XOR: known-plaintext with the flag prefix, repeating-key length by Hamming distance. RSA: small `e`, shared or small factors, `n` on factordb, Wiener for large `e`. Hash: `identify_hash`, then a wordlist. Write a short Python script; do not do big-number math in your head.
- **Web**: view source, cookies, `robots.txt`, hidden parameters; then the `web-app-testing` skill.
- **Reversing**: `file`, `strings`, run it in a sandbox, then decompile (Ghidra). Find the check on the input, and invert it or solve it with z3. For scripts and bytecode, deobfuscate step by step.
- **Pwn**: `checksec`, find the bug (overflow, format string, use-after-free), find the offset with a cyclic pattern, decide the technique from the protections (ret2win, ret2libc, ROP), write it with pwntools, test locally before remote.
- **Forensics**: pcap: protocol statistics, follow streams, export objects. Disk or memory image: file listing, deleted files, process list, command history. Always check timestamps and metadata.
- **Stego**: metadata, appended data after the file end, LSB planes (`zsteg`, `stegsolve`), `steghide` with an empty or hinted password, spectrogram for audio.
- **OSINT**: usernames across sites, image metadata and reverse search, archived pages, map and street views.

## Rules

- Run things and read the output; ask the user for the output if you cannot run code.
- Do every calculation and decoding with a tool or script.
- Never invent a flag. A flag counts only when it came out of the challenge data.
- When stuck for more than a few steps: list what is known, what has not been looked at, and what the challenge title could be hinting at.
