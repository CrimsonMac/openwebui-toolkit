---
name: ollama-tuning
description: Configure and troubleshoot local models in Ollama - context size, memory use, speed, Modelfiles and sampling parameters. Use when the user asks about num_ctx, VRAM, slow generation, a model spilling to CPU, context being cut off, Modelfile syntax, or how to set up a model in Ollama or Open WebUI.
---

# Tuning Ollama models

## The facts that explain most problems

- **`num_ctx` is the context window in tokens**, prompt plus reply. Ollama's default is small. When a prompt is longer, the oldest part is dropped silently, and the model "forgets" its instructions. Set it deliberately.
- **Memory = model weights + context cache.** The cache grows linearly with `num_ctx`. A large context can cost more memory than the model itself.
- **If the total does not fit in VRAM, layers move to the CPU** and speed drops several-fold. `ollama ps` shows the split, e.g. `100% GPU` or `35%/65% CPU/GPU`.
- **Changing `num_ctx` reloads the model.** Two clients asking for different sizes cause a reload on every switch.

## Diagnose

Ask for, or run:

```
ollama ps                     # loaded models, size, CPU/GPU split, context
ollama show MODEL             # parameters, template, context length, quantization
ollama show MODEL --verbose   # layer count, embedding length, head counts
nvidia-smi                    # VRAM in use
```

## Estimate memory before changing context

If you can run code:

```
python scripts/vram_estimate.py --file-gb 21 --layers 64 --embed 5120 --heads 40 --kv-heads 8 \
    --ctx 8192 32768 65536 --vram-gb 24
```

Take `--layers` (block_count), `--embed` (embedding_length), `--heads` and `--kv-heads` from `ollama show MODEL --verbose`, and `--file-gb` from `ollama list`. Add `--kv-type q8_0` to see the effect of a quantized cache. The result is an estimate; confirm with `ollama ps`.

## Measure instead of guessing

```
python scripts/ollama_bench.py MODEL --ctx 32768 131072 --batch 512 2048 --repeat 2
python scripts/ollama_bench.py MODEL --ctx 131072 --option use_mmap=false
python scripts/ollama_prewarm.py MODEL --load --keep-alive 2h
```

`ollama_bench.py` loads the model fresh for each setting and reports load time, prompt processing speed, generation speed and the wait on a follow-up turn. Run it on the Ollama host while nobody is using the server. `ollama_prewarm.py` reads the model files into the file cache and can load the model ahead of the first message.

What such measurements commonly show on a card that cannot hold the whole model:

- `num_batch 2048` instead of 512 roughly doubles prompt processing speed, as long as the context is not so large that the bigger buffers push weights off the GPU.
- A context far larger than needed costs speed even when it is empty, because its cache takes VRAM away from the weights.
- When speeds swing wildly between runs, the part of the model on the CPU is being paged in and out of the file cache. `PARAMETER use_mmap false` loads it into memory properly: slower to load, then fast and steady. It needs enough free RAM for everything that is not on the GPU.
- Re-reading a long conversation takes minutes. Keep the history small enough to re-read in the time you are willing to wait, and avoid anything that changes early messages.

## When the whole machine freezes

A model that fits at load time can still eat all RAM later. Three things grow after loading:

1. **Saved prompt states.** The llama.cpp server behind Ollama keeps copies of earlier prompts in RAM so it can switch back to them, up to 8192 MiB by default. A copy of a 100,000-token chat is 1 to 2 GB, and a new one is stored whenever a request starts very differently from the last one: another chat, a title or summary request, or a chat whose beginning was trimmed. The log shows it: `journalctl -u ollama | grep "cache state"`.
2. **Context checkpoints**, up to 32 per chat at about 60 MB each.
3. **Swap on zram.** Model weights do not compress, so swapping them into compressed RAM frees nothing and the machine stalls.

The fix is a wall, not a watchdog: give Ollama a fixed share of RAM that the kernel enforces, and size Ollama's own appetite to stay below it. Then nothing is ever unloaded or killed, and the rest of the RAM always stays with the rest of the PC.

1. Measure what the model holds after loading, and look at the wall:

   ```
   python scripts/ollama_ram_wall.py --measure MODEL      # prints "--model-mb N"
   python scripts/ollama_ram_wall.py --model-mb N         # shows the wall and whether it holds
   ```

2. Get the settings for a wall that leaves a chosen amount to the PC. This prints them and changes nothing:

   ```
   python scripts/ollama_ram_wall.py --plan --keep-free-mb 9000 --model-mb N
   ```

3. Apply them (needs root): put the printed block in `/etc/systemd/system/ollama.service.d/zz-memory-wall.conf`, then `sudo systemctl daemon-reload && sudo systemctl restart ollama`. It looks like this:

   ```
   [Service]
   MemoryMax=21504M
   MemorySwapMax=0
   Environment="LLAMA_ARG_CACHE_RAM=1536"
   Environment="LLAMA_ARG_CTX_CHECKPOINTS=8"
   ```

What each line does: `MemoryMax` is the wall. `MemorySwapMax=0` keeps model weights out of swap. The two variables cap the only parts that grow after loading, so the most Ollama can ever ask for is model + prompt cache + checkpoints, and `--plan` keeps that sum below the wall. If the model alone does not fit behind the wall you ask for, `--plan` says so instead of printing settings that would get it killed.

Check afterwards with `python scripts/ollama_ram_wall.py --model-mb N`: it must say "the wall holds", with the wall reached 0 times. Also check that the log line `cache state` shows the new prompt cache limit (`journalctl -u ollama | grep "cache state"`); if it still says 8192, this Ollama version does not pass the variable on.

Do not run a script that unloads the model when memory gets low. It stops answers in the middle, and with the wall in place it is not needed.

## Levers, in order of effect

1. **Lower `num_ctx`** to what the task needs.
2. **Quantize the context cache**: server environment `OLLAMA_KV_CACHE_TYPE=q8_0` (about half the cache memory, little quality loss) together with `OLLAMA_FLASH_ATTENTION=1`.
3. **Use a smaller quantization** of the model (q4_K_M instead of q8) or a smaller model.
4. **`OLLAMA_NUM_PARALLEL=1`**: each parallel slot gets its own full context.
5. **`OLLAMA_MAX_LOADED_MODELS=1`** if two models fight over VRAM. `keep_alive` controls how long a model stays loaded.

Environment variables are set on the Ollama server (for systemd: `systemctl edit ollama`, add `Environment="NAME=value"`, then restart), not in the client.

## Modelfile

```
FROM qwen3:32b
PARAMETER num_ctx 32768
PARAMETER temperature 0.7
PARAMETER top_p 0.9
PARAMETER repeat_penalty 1.05
SYSTEM """You are a concise technical assistant."""
```

Build with `ollama create my-model -f Modelfile`. In Open WebUI the same parameters can be set per model under Workspace → Models → Advanced Params, which avoids a Modelfile.

## Sampling, briefly

- `temperature`: 0–0.3 for code and extraction, 0.6–0.8 for general chat, higher for brainstorming.
- `top_p` 0.9 and `top_k` 40 are fine defaults; change one thing at a time.
- `repeat_penalty` above 1.15 damages code and structured output.
- `num_predict` caps the reply length; `-1` is unlimited.
- Prefer the values the model's publisher recommends over generic ones.

## Rules

- Do not state a model's exact layer count, context limit or memory use from memory. Read it from `ollama show` or say it is an estimate.
- Give one change at a time and say how to verify it (`ollama ps`, tokens per second in the reply stats).
