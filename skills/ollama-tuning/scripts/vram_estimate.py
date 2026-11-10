#!/usr/bin/env python3
"""Estimate the memory an Ollama / llama.cpp model needs at a given context size.

  total ≈ weights file + KV cache + overhead
  KV cache = 2 × layers × context × kv_dim × bytes_per_value
  kv_dim   = embedding_length × kv_heads / heads

Get the numbers from `ollama show MODEL --verbose` (block_count, embedding_length,
attention.head_count, attention.head_count_kv) and the file size from `ollama list`.

Usage:
  vram_estimate.py --file-gb 21 --layers 64 --embed 5120 --heads 40 --kv-heads 8 --ctx 32768
  vram_estimate.py ... --ctx 8192 16384 32768 65536 --vram-gb 24
"""
import argparse


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--file-gb", type=float, required=True, help="size of the model file in GB")
    p.add_argument("--layers", type=int, required=True, help="block_count")
    p.add_argument("--embed", type=int, required=True, help="embedding_length")
    p.add_argument("--heads", type=int, required=True, help="attention.head_count")
    p.add_argument("--kv-heads", type=int, help="attention.head_count_kv (default: same as --heads)")
    p.add_argument("--ctx", type=int, nargs="+", default=[4096, 8192, 16384, 32768, 65536, 131072])
    p.add_argument("--kv-type", choices=["f16", "q8_0", "q4_0"], default="f16", help="OLLAMA_KV_CACHE_TYPE")
    p.add_argument("--parallel", type=int, default=1, help="OLLAMA_NUM_PARALLEL; the context is allocated once per slot")
    p.add_argument("--vram-gb", type=float, help="your VRAM, to mark what fits")
    a = p.parse_args()

    kv_dim = a.embed * (a.kv_heads or a.heads) / a.heads
    bytes_per = {"f16": 2.0, "q8_0": 1.0, "q4_0": 0.5}[a.kv_type]
    overhead = 0.6 + 0.02 * a.file_gb  # compute buffers and runtime, rough

    print(f"weights {a.file_gb:g} GB, {a.layers} layers, kv_dim {kv_dim:g}, cache type {a.kv_type}, parallel {a.parallel}")
    print(f"{'context':>9}  {'KV cache':>9}  {'total':>8}")
    for ctx in a.ctx:
        kv = 2 * a.layers * ctx * a.parallel * kv_dim * bytes_per / 1024**3
        total = a.file_gb + kv + overhead
        fit = ""
        if a.vram_gb:
            fit = "  fits" if total <= a.vram_gb else f"  over by {total - a.vram_gb:.1f} GB (spills to CPU, much slower)"
        print(f"{ctx:>9}  {kv:>7.2f} GB  {total:>5.1f} GB{fit}")
    print("\nAn estimate, usually within 10-15%. Check the real figure with `ollama ps` after loading.")


if __name__ == "__main__":
    main()
