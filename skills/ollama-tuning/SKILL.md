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
