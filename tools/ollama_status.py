"""
title: Ollama Status
author: Crimson
version: 1.0.0
description: Lets the model see the local Ollama server - installed models, what is loaded, memory use and the CPU/GPU split, and a model's parameters. Unloading is off by default.
"""

import asyncio
import json
import urllib.error
import urllib.request
from datetime import datetime

from pydantic import BaseModel, Field


def _gb(n) -> str:
    return f"{(n or 0) / 1024**3:.1f} GB"


def _request(base: str, path: str, payload, timeout: int):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(base.rstrip("/") + path, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


class Tools:
    class Valves(BaseModel):
        ollama_url: str = Field(
            "http://localhost:11434",
            description="Base URL of the Ollama server as seen from the Open WebUI server (in Docker often http://host.docker.internal:11434 or http://ollama:11434).",
        )
        timeout: int = Field(15, description="Seconds before giving up.")
        allow_unload: bool = Field(False, description="Allow the model to unload models from memory.")

    def __init__(self):
        self.valves = self.Valves()

    async def _call(self, path: str, payload=None):
        return await asyncio.to_thread(_request, self.valves.ollama_url, path, payload, self.valves.timeout)

    def _error(self, e: Exception) -> str:
        if isinstance(e, urllib.error.HTTPError):
            try:
                detail = json.load(e).get("error", "")
            except Exception:
                detail = ""
            return f"Error: Ollama answered HTTP {e.code}. {detail}".strip()
        if isinstance(e, urllib.error.URLError):
            return f"Error: cannot reach Ollama at {self.valves.ollama_url} ({e.reason}). Check the ollama_url valve."
        return f"Error: {e}"

    async def list_installed_models(self) -> str:
        """
        List the models installed in Ollama with size, parameter count and quantization.

        :return: One line per model, largest first.
        """
        try:
            models = (await self._call("/api/tags")).get("models", [])
            version = (await self._call("/api/version")).get("version", "?")
        except Exception as e:
            return self._error(e)
        if not models:
            return f"Ollama {version}: no models installed."
        lines = []
        for m in sorted(models, key=lambda m: m.get("size", 0), reverse=True):
            d = m.get("details", {})
            lines.append(f"- {m['name']}: {_gb(m.get('size'))}, {d.get('parameter_size', '?')} parameters, {d.get('quantization_level', '?')}, family {d.get('family', '?')}")
        total = sum(m.get("size", 0) for m in models)
        return f"Ollama {version}, {len(models)} model(s), {_gb(total)} on disk:\n" + "\n".join(lines)

    async def list_loaded_models(self) -> str:
        """
        Show which models are loaded in memory right now, how much memory each uses, how much of it is on the GPU,
        the context size, and when each will be unloaded. Use this for questions about VRAM, speed or "why is it slow".

        :return: One line per loaded model.
        """
        try:
            models = (await self._call("/api/ps")).get("models", [])
        except Exception as e:
            return self._error(e)
        if not models:
            return "No models are loaded in memory right now."
        lines = []
        for m in models:
            size, vram = m.get("size", 0), m.get("size_vram", 0)
            gpu = round(100 * vram / size) if size else 0
            split = "100% GPU" if gpu >= 100 else "100% CPU" if gpu <= 0 else f"{gpu}% GPU / {100 - gpu}% CPU (partly on CPU, expect it to be slow)"
            ctx = f", context {m['context_length']}" if m.get("context_length") else ""
            until = ""
            if m.get("expires_at"):
                try:
                    left = datetime.fromisoformat(m["expires_at"]) - datetime.now().astimezone()
                    until = f", unloads in {max(0, int(left.total_seconds() // 60))} min"
                except (ValueError, TypeError):
                    pass
            lines.append(f"- {m['name']}: {_gb(size)} total, {_gb(vram)} in VRAM, {split}{ctx}{until}")
        return "\n".join(lines)

    async def show_model_details(self, model: str) -> str:
        """
        Show one model's details: architecture, parameter count, maximum context length, quantization,
        configured parameters (such as num_ctx and temperature) and capabilities.

        :param model: The model name exactly as installed, for example "llama3.2:3b".
        :return: The details as text.
        """
        try:
            d = await self._call("/api/show", {"model": model})
        except Exception as e:
            return self._error(e)
        det, info = d.get("details", {}), d.get("model_info", {})

        def find(suffix):
            return next((v for k, v in info.items() if k.endswith(suffix)), None)

        out = [
            f"{model}: {det.get('parameter_size', '?')} parameters, {det.get('quantization_level', '?')}, format {det.get('format', '?')}, family {det.get('family', '?')}",
            f"architecture: {info.get('general.architecture', '?')}",
            f"maximum context length: {find('.context_length') or '?'}",
            f"layers: {find('.block_count') or '?'}, embedding length: {find('.embedding_length') or '?'}, heads: {find('.attention.head_count') or '?'}, kv heads: {find('.attention.head_count_kv') or '?'}",
        ]
        if d.get("capabilities"):
            out.append("capabilities: " + ", ".join(d["capabilities"]))
        if d.get("parameters"):
            out.append("configured parameters:\n" + "\n".join("  " + " ".join(line.split()) for line in d["parameters"].splitlines()))
        else:
            out.append("configured parameters: none (Ollama defaults apply, including its default context size)")
        if d.get("system"):
            out.append(f"system prompt: {d['system'][:300]}")
        return "\n".join(out)

    async def unload_model(self, model: str) -> str:
        """
        Unload a model from memory to free VRAM. Only use this when the user asks for it.

        :param model: The model name exactly as shown by list_loaded_models.
        :return: Confirmation, or a note that unloading is disabled.
        """
        if not self.valves.allow_unload:
            return "Unloading is disabled. The administrator can enable it with the allow_unload valve of this tool."
        try:
            await self._call("/api/generate", {"model": model, "keep_alive": 0})
        except Exception as e:
            return self._error(e)
        return f"Asked Ollama to unload '{model}'. Check with list_loaded_models."
