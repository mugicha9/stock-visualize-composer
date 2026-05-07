#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
SETTINGS_PATH = Path(os.getenv("APP_SETTINGS_PATH") or ROOT_DIR / "config" / "app_settings.json")

DEFAULTS = {
    "llama_cpp_container_name": "llama-qwen36-cuda",
    "llama_cpp_image": "ghcr.io/ggml-org/llama.cpp:server-cuda",
    "llama_cpp_docker_restart": "unless-stopped",
    "llama_cpp_docker_gpus": "all",
    "llama_cpp_host_models_dir": "data/llama-models",
    "llama_cpp_container_models_dir": "/models",
    "llama_cpp_model_file": "Qwen3.6-35B-A3B-UD-IQ4_NL_XL.gguf",
    "llama_cpp_alias": "qwen3.6-35b-a3b",
    "llama_cpp_host": "0.0.0.0",
    "llama_cpp_port": "10000",
    "llama_cpp_container_port": "8080",
    "llama_cpp_context_length": "65536",
    "llama_cpp_n_parallel": "1",
    "llama_cpp_ncmoe": "24",
    "llama_cpp_gpu_layers": "auto",
    "llama_cpp_no_mmap": "false",
    "llama_cpp_chat_template_kwargs": '{"preserve_thinking":false}',
    "llama_cpp_reasoning": "off",
    "llama_cpp_reasoning_budget": "0",
    "llama_cpp_temperature": "0.6",
    "llama_cpp_top_p": "0.95",
    "llama_cpp_top_k": "20",
    "llama_cpp_min_p": "0.0",
    "llama_cpp_presence_penalty": "0.0",
    "llama_cpp_repeat_penalty": "1.0",
    "llama_cpp_docker_env_json": (
        '{"NVIDIA_VISIBLE_DEVICES":"all","NVIDIA_DRIVER_CAPABILITIES":"compute,utility,graphics"}'
    ),
    "llama_cpp_extra_args": "",
}


def main() -> int:
    action = sys.argv[1] if len(sys.argv) > 1 else "serve"
    settings = load_settings()
    name = setting(settings, "llama_cpp_container_name")

    if action == "serve":
        if container_exists(name):
            run(["docker", "start", name])
        else:
            run(docker_run_args(settings))
        return 0
    if action == "recreate":
        remove_container(name)
        run(docker_run_args(settings))
        return 0
    if action == "stop":
        if container_exists(name):
            run(["docker", "stop", name])
        else:
            print(f"container not found: {name}")
        return 0
    if action == "rm":
        remove_container(name)
        return 0
    if action == "logs":
        run(["docker", "logs", "-f", name])
        return 0
    if action == "ps":
        run(["docker", "ps", "-a", "--filter", f"name=^{name}$"])
        return 0
    if action == "command":
        print(" ".join(shlex.quote(part) for part in docker_run_args(settings)))
        return 0

    print("usage: scripts/llama_cpp_docker.py [serve|recreate|stop|rm|logs|ps|command]", file=sys.stderr)
    return 2


def docker_run_args(settings: dict[str, str]) -> list[str]:
    name = setting(settings, "llama_cpp_container_name")
    image = setting(settings, "llama_cpp_image")
    host_models_dir = resolve_host_path(setting(settings, "llama_cpp_host_models_dir"))
    container_models_dir = setting(settings, "llama_cpp_container_models_dir")
    model_file = setting(settings, "llama_cpp_model_file")
    host_port = setting(settings, "llama_cpp_port")
    container_port = setting(settings, "llama_cpp_container_port")
    args = [
        "docker",
        "run",
        "-d",
        "--name",
        name,
        "--restart",
        setting(settings, "llama_cpp_docker_restart"),
    ]
    gpus = setting(settings, "llama_cpp_docker_gpus")
    if gpus:
        args.extend(["--gpus", gpus])
    for key, value in docker_env(settings).items():
        args.extend(["-e", f"{key}={value}"])
    args.extend(["-p", f"{host_port}:{container_port}", "-v", f"{host_models_dir}:{container_models_dir}:ro", image])
    args.extend(
        [
            "-m",
            f"{container_models_dir.rstrip('/')}/{model_file}",
            "--alias",
            setting(settings, "llama_cpp_alias"),
            "--host",
            setting(settings, "llama_cpp_host"),
            "--port",
            container_port,
        ]
    )
    if truthy(setting(settings, "llama_cpp_no_mmap")):
        args.append("--no-mmap")
    args.extend(
        [
            "-c",
            setting(settings, "llama_cpp_context_length"),
            "-np",
            setting(settings, "llama_cpp_n_parallel"),
            "-ncmoe",
            setting(settings, "llama_cpp_ncmoe"),
        ]
    )
    gpu_layers = setting(settings, "llama_cpp_gpu_layers")
    if gpu_layers:
        args.extend(["--gpu-layers", gpu_layers])
    chat_kwargs = setting(settings, "llama_cpp_chat_template_kwargs")
    if chat_kwargs:
        args.extend(["--chat-template-kwargs", chat_kwargs])
    reasoning = setting(settings, "llama_cpp_reasoning")
    if reasoning:
        args.extend(["--reasoning", reasoning])
    reasoning_budget = setting(settings, "llama_cpp_reasoning_budget")
    if reasoning_budget:
        args.extend(["--reasoning-budget", reasoning_budget])
    args.extend(
        [
            "--temp",
            setting(settings, "llama_cpp_temperature"),
            "--top-p",
            setting(settings, "llama_cpp_top_p"),
            "--top-k",
            setting(settings, "llama_cpp_top_k"),
            "--min-p",
            setting(settings, "llama_cpp_min_p"),
            "--presence-penalty",
            setting(settings, "llama_cpp_presence_penalty"),
            "--repeat-penalty",
            setting(settings, "llama_cpp_repeat_penalty"),
        ]
    )
    args.extend(shlex.split(setting(settings, "llama_cpp_extra_args")))
    return args


def load_settings() -> dict[str, str]:
    if not SETTINGS_PATH.exists():
        return dict(DEFAULTS)
    raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    payload = raw.get("settings") if isinstance(raw, dict) and "settings" in raw else raw
    if not isinstance(payload, dict):
        raise SystemExit(f"settings JSON must be an object: {SETTINGS_PATH}")
    return {**DEFAULTS, **{str(key): str(value) for key, value in payload.items()}}


def setting(settings: dict[str, str], key: str) -> str:
    return settings.get(key) or DEFAULTS.get(key, "")


def docker_env(settings: dict[str, str]) -> dict[str, str]:
    raw = setting(settings, "llama_cpp_docker_env_json")
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise SystemExit(f"llama_cpp_docker_env_json must be valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise SystemExit("llama_cpp_docker_env_json must be a JSON object")
    return {str(key): str(value) for key, value in parsed.items()}


def container_exists(name: str) -> bool:
    result = subprocess.run(["docker", "inspect", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return result.returncode == 0


def remove_container(name: str) -> None:
    if not container_exists(name):
        print(f"container not found: {name}")
        return
    subprocess.run(["docker", "stop", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    run(["docker", "rm", name])


def run(args: list[str]) -> None:
    subprocess.run(args, check=True)


def resolve_host_path(path: str) -> str:
    value = Path(path).expanduser()
    if not value.is_absolute():
        value = ROOT_DIR / value
    return str(value)


def truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    raise SystemExit(main())
