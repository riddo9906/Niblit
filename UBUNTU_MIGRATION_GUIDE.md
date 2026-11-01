# Niblit Ubuntu workstation migration

Prepared 2026-10-26 from the local Windows source repositories. Commands below
run in **Ubuntu Bash**, after Ubuntu is installed. They have not been executed
or verified on Ubuntu. Hardware queries on Windows were unavailable, so GPU
driver selection must follow detection below. Keep Windows for Warzone.

## 1. Preserve the Windows installation and your work

Reserve about 256 GB for Ubuntu; keep the rest available for Windows games.
Use the Ubuntu installer in UEFI mode. Do not format Windows partitions or the
existing Windows EFI partition. Back up important files and retain your
BitLocker recovery key before installation or firmware changes.

If Windows starts instead of Ubuntu after installation, inspect firmware boot
order and select the `ubuntu` entry before `Windows Boot Manager`. Keep both
entries. From Ubuntu, `sudo efibootmgr -v` displays the actual entries; do not
copy somebody else's boot entry numbers. Confirm UEFI with:

```bash
test -d /sys/firmware/efi && echo 'UEFI boot confirmed'
lsblk -o NAME,SIZE,MODEL,FSTYPE,MOUNTPOINTS
```

Before copying data, stop Niblit and its related services cleanly on Windows.
Copy source repositories including uncommitted changes, private configuration,
SQLite databases (including WAL/SHM files if present), runtime/memory folders,
and models. A Git clone alone will omit ignored files and local work. Back up
Qdrant separately using its snapshot/export procedure; a new Linux container
does not include Windows Docker volumes. Keep the original backup unchanged.
Do not copy running SQLite databases as a consistent backup.

Observed sibling repositories:

- `Niblit`
- `Niblit-cloud-server`
- `niblit-ui`
- `niblit-lean-algos`
- `github-copilot-llm-gateway`
- `freqtrade` (optional separate trading environment)

Observed model files in `C:\Users\Riyaad\llama_migration\models`:

| Model | Bytes |
| --- | ---: |
| Llama-3.2-1B-Instruct-Q4_K_M.gguf | 807694464 |
| qwen2.5-0.5b-instruct-q4_k_m.gguf | 491400032 |
| qwen2.5-coder-3b-instruct-q4_k_m.gguf | 2104932800 |

The Windows CMake cache has `GGML_VULKAN=ON`. Its llama.cpp Git HEAD is
`dd7cad7197f991b18ded6aca46ff095972b95318`. Uncommitted upstream changes were
not audited. GGML is included in llama.cpp; do not install a separate unrelated
`ggml` Python package. Windows EXE/DLL files cannot replace Linux builds.

## 2. Ubuntu packages and folder layout

These package names target Ubuntu Desktop 24.04/26.04. Stop if apt reports
missing packages and check the installed Ubuntu version instead of mixing
repositories from another release.

```bash
cat /etc/os-release
sudo apt update
sudo apt upgrade
sudo apt install build-essential git cmake ninja-build pkg-config curl wget \
  ca-certificates unzip rsync python3 python3-dev python3-venv python3-pip \
  libssl-dev libffi-dev libcurl4-openssl-dev libopenblas-dev \
  libvulkan-dev vulkan-tools glslc spirv-headers \
  libsndfile1 ffmpeg portaudio19-dev sqlite3 smartmontools
mkdir -p "$HOME/Projects" "$HOME/llama_migration/models" "$HOME/.config/niblit"
```

Copy each repository to `~/Projects/<repository-name>`, and the GGUF files to
`~/llama_migration/models`. Use Ubuntu's Files application and your backup
drive. Keep working copies on Ubuntu's ext4 filesystem. Recreate `.venv`,
`niblit-env`, `node_modules`, native build folders and Rust target folders;
do not reuse Windows versions. Keep private `.env` files outside Git and
review their paths before using them. Never paste secrets into migration logs.

## 3. GPU driver and Vulkan checks

```bash
lspci -nnk | grep -A3 -E 'VGA|3D|Display'
vulkaninfo --summary
```

AMD/Intel commonly use Mesa:

```bash
sudo apt install mesa-vulkan-drivers
```

For NVIDIA, use Ubuntu **Software & Updates > Additional Drivers** to install
the recommended proprietary driver, then reboot. Complete MOK enrollment if
requested with Secure Boot enabled. Do not disable Secure Boot as a default
workaround. Re-run `vulkaninfo --summary`: it must show the intended physical
GPU. A software renderer such as llvmpipe/lavapipe is not GPU acceleration.

## 4. Build llama.cpp with the GGML Vulkan backend

Copy the Windows llama.cpp source checkout, including its `.git` directory,
to `~/llama_migration/llama.cpp` to retain the existing revision and local
source changes. Use a NEW Linux build directory below. If you choose a fresh
clone instead, run these first (only when the destination does not exist):

```bash
git clone https://github.com/ggml-org/llama.cpp "$HOME/llama_migration/llama.cpp"
git -C "$HOME/llama_migration/llama.cpp" checkout dd7cad7197f991b18ded6aca46ff095972b95318
```

Build without sudo; keep the binaries and their shared libraries together:

```bash
cd "$HOME/llama_migration/llama.cpp"
git rev-parse HEAD
cmake -S . -B build-linux-vulkan -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DGGML_VULKAN=ON
cmake --build build-linux-vulkan --config Release --parallel 2
./build-linux-vulkan/bin/llama-server --version
./build-linux-vulkan/bin/llama-server --list-devices
```

Two build jobs limit peak RAM; increase only if memory permits. Do not use the
existing generic `tools/install_llama_server.sh` as proof of Vulkan support:
it downloads a generic binary and copies only the server executable.

Run a standalone server in terminal A:

```bash
"$HOME/llama_migration/llama.cpp/build-linux-vulkan/bin/llama-server" \
  -m "$HOME/llama_migration/models/qwen2.5-coder-3b-instruct-q4_k_m.gguf" \
  --alias qwen2.5-coder-3b --host 127.0.0.1 --port 8080 -c 4096 -ngl 99
```

Check startup logs for Vulkan device selection AND layers actually offloaded.
On allocation failures reduce context or GPU layers (for example `-ngl 10`);
`-ngl 0` is a CPU diagnostic fallback. Begin with 4096 context, then measure
memory before restoring the Windows profiles' larger context settings.

In terminal B:

```bash
curl --fail http://127.0.0.1:8080/health
curl --fail http://127.0.0.1:8080/v1/models
curl --fail http://127.0.0.1:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen2.5-coder-3b","messages":[{"role":"user","content":"Write a Python hello world."}],"max_tokens":100}'
```

## 5. Core Python and server dependencies

Use one Linux environment for Core and its autostarted cloud process: the
current UI launcher starts the cloud process using Core's `sys.executable`.

```bash
cd "$HOME/Projects/Niblit"
python3 -m venv niblit-env
source niblit-env/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements.txt
python -m pip install -r ../niblit-lean-algos/requirements.txt
CMAKE_ARGS='-DGGML_VULKAN=ON' python -m pip install --no-cache-dir \
  --no-binary=llama-cpp-python -r ../Niblit-cloud-server/requirements.txt
python -m pip check
```

The server requirements currently pin `llama-cpp-python==0.3.16`, FastAPI,
uvicorn, pytest and httpx. Installing it last applies those pins; stop on
resolver errors. This binding bundles a separate llama.cpp revision from the
standalone server. Its Vulkan support needs separate verification. The
standalone HTTP route above avoids relying on it for the primary GPU server.
CPU torch still supports embeddings; Vulkan llama.cpp does not make torch
training GPU accelerated. Do not assume bitsandbytes/CUDA applies to AMD/Intel.

## 6. UI and development tools

```bash
sudo apt install nodejs npm
node --version
npm --version
```

Core requires Node >=18. If the distribution package is older, install a
supported Node LTS from the official Node instructions before continuing.

```bash
cd "$HOME/Projects/niblit-ui"
npm ci
npm run build
sudo apt install libwebkit2gtk-4.1-dev libxdo-dev libayatana-appindicator3-dev \
  librsvg2-dev patchelf
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs -o /tmp/niblit-rustup.sh
less /tmp/niblit-rustup.sh
sh /tmp/niblit-rustup.sh
source "$HOME/.cargo/env"
rustc --version
```

Install VS Code from its official Linux download. To reuse the local gateway:

```bash
code --install-extension "$HOME/Projects/github-copilot-llm-gateway/gateway-niblit-local.vsix"
```

The gateway currently requires VS Code ^1.120.0. Verify editor compatibility.
Cloud Copilot features require network access; local inference does not make
all editor features offline. Export your existing extension list and settings
on Windows, copy them privately, and replace Windows executable/workspace paths.

## 7. Linux path profile and first boot

Create `~/.config/niblit/ubuntu.sh` with the following Bash content. This
separate profile avoids overwriting Core's private `.env`. Source it in each
terminal before starting a component. Keep terminal A's server running.

```bash
export NIBLIT_PROFILE=full
export NIBLIT_UI_PATH="$HOME/Projects/niblit-ui"
export NIBLIT_CLOUD_SERVER_PATH="$HOME/Projects/Niblit-cloud-server"
export NIBLIT_LLAMA_CPP_ROOT="$HOME/llama_migration/llama.cpp"
export NIBLIT_LLAMA_BINARY_PATH="$NIBLIT_LLAMA_CPP_ROOT/build-linux-vulkan/bin/llama-server"
export NIBLIT_LLAMA_SERVER_BIN="$NIBLIT_LLAMA_BINARY_PATH"
export NIBLIT_LLAMA_BINARY="$NIBLIT_LLAMA_BINARY_PATH"
export NIBLIT_LLAMA_MODEL_DIRS="$HOME/llama_migration/models"
export NIBLIT_GGUF_MODEL_DIR="$NIBLIT_LLAMA_MODEL_DIRS"
export NIBLIT_GGUF_MODEL_PATH="$NIBLIT_LLAMA_MODEL_DIRS/qwen2.5-coder-3b-instruct-q4_k_m.gguf"
export NIBLIT_MODEL_PATH="$NIBLIT_GGUF_MODEL_PATH"
export NIBLIT_GGUF_BACKEND=http
export NIBLIT_LLAMA_SERVER_URL=http://127.0.0.1:8080
export LLAMA_CPP_SERVER_URL=http://127.0.0.1:8080
export NIBLIT_LLAMA_AUTOSTART=0
export NIBLIT_LLAMA_N_CTX=4096
export NIBLIT_GGUF_N_CTX=4096
export NIBLIT_QWEN_PORT=8081
export NIBLIT_N_CTX=4096
export NIBLIT_N_GPU_LAYERS=20
export NIBLIT_HOST=127.0.0.1
export NIBLIT_CLOUD_BIND_HOST=127.0.0.1
export NIBLIT_PORT=8000
export NIBLIT_CLOUD_SERVER_PRIMARY_PORT=8000
export NIBLIT_CLOUD_SERVER_URL=http://127.0.0.1:8000
export NIBLIT_CLOUD_BASE_URL=http://127.0.0.1:8000
export PYTHON="$HOME/Projects/Niblit/niblit-env/bin/python"
```

Core and server have different variable names, so both are provided. The
standalone server occupies 8080. If the cloud qwen provider starts its own
server, it uses 8081 and may load another model into memory. Inspect actual
processes/logs before enabling additional providers. Model routing and aliases
must be verified using the cloud API; a configured URL alone proves nothing.

```bash
source "$HOME/.config/niblit/ubuntu.sh"
cd "$HOME/Projects/Niblit"
source niblit-env/bin/activate
npm run dev
# After browser mode works, stop it and optionally use:
# npm run tauri:dev
```

Check in another terminal:

```bash
curl --fail http://127.0.0.1:8000/healthz
curl --fail http://127.0.0.1:8000/v1/models
ss -ltnp | grep -E ':5000|:8000|:8080|:8081|:6333'
```

Test a real completion through the cloud route with an ID returned by its
`/v1/models`, then test UI chat. Source boot is the first target; packaged
desktop build scripts and sidecars require their own Linux audit.

## 8. Docker and the memory laboratory

Install Docker Engine and the Compose plugin using the official Ubuntu guide
linked below. Do not mix Docker CE and Ubuntu docker.io installations. Verify:

```bash
sudo systemctl enable --now docker
sudo docker version
sudo docker compose version
```

Privately copy the Windows `%LOCALAPPDATA%/Niblit/memory-laboratory/.env` to
`~/.config/niblit/memory-laboratory.env`. Preserve its key when restoring the
existing service. For a fresh lab, create a private key and use the settings
in `scripts/Start-Memory-Laboratory.ps1`; do not source that Windows script.
Reinstalling the container creates an EMPTY volume unless you restore data.

```bash
chmod 600 "$HOME/.config/niblit/memory-laboratory.env"
cd "$HOME/Projects/Niblit"
sudo docker compose --project-name niblit-memory-lab \
  --env-file "$HOME/.config/niblit/memory-laboratory.env" \
  -f deploy/memory-laboratory.compose.yml up -d
source niblit-env/bin/activate
python -m modules.memory_laboratory \
  --env-file "$HOME/.config/niblit/memory-laboratory.env" --embedding-only
python -m modules.memory_laboratory \
  --env-file "$HOME/.config/niblit/memory-laboratory.env" --apply
```

Download the pinned embedding before going offline (section 9). For runtime
integration add to the Bash profile:

```bash
export NIBLIT_MEMORY_LAB_ENABLED=1
export NIBLIT_MEMORY_LAB_ENV_FILE="$HOME/.config/niblit/memory-laboratory.env"
export NIBLIT_MEMORY_LAB_NAMESPACE=desktop
export NIBLIT_MEMORY_LAB_PRINCIPAL=desktop_operator
export NIBLIT_MEMORY_LAB_LEDGER="$HOME/.local/share/niblit/memory-laboratory/ledger.sqlite3"
mkdir -p "$(dirname "$NIBLIT_MEMORY_LAB_LEDGER")"
```

Keep existing ledger and access settings in the backup. On a fresh ledger,
explicitly grant the intended local access using the existing operator tool:

```bash
python -m modules.memory_laboratory.operator \
  --env-file "$NIBLIT_MEMORY_LAB_ENV_FILE" --ledger "$NIBLIT_MEMORY_LAB_LEDGER" \
  grant read ingest consolidate --confirm
```

## 9. Prepare and test offline operation

```bash
source "$HOME/Projects/Niblit/niblit-env/bin/activate"
python - <<'PY'
from huggingface_hub import snapshot_download
snapshot_download('intfloat/multilingual-e5-small',
                  revision='614241f622f53c4eeff9890bdc4f31cfecc418b3')
PY
mkdir -p "$HOME/niblit-offline/wheels"
python -m pip freeze > "$HOME/niblit-offline/ubuntu-python-lock.txt"
python -m pip wheel -r "$HOME/niblit-offline/ubuntu-python-lock.txt" \
  --wheel-dir "$HOME/niblit-offline/wheels"
sudo docker save qdrant/qdrant:v1.18.0 -o "$HOME/niblit-offline/qdrant-image.tar"
```

Build/cache Linux wheels on Ubuntu, not Windows. For a cold llama-cpp-python
wheel build, use `CMAKE_ARGS='-DGGML_VULKAN=ON'` and verify that wheel separately.
Download any additional transformer models/tokenizers actually used by your
selected providers, coding documentation, npm packages and Cargo dependencies.
GGUF files do not include embedding models or every tokenizer used elsewhere.
Once downloaded, set `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` for an
offline test. Disconnect networking and verify model inference, UI, memory
ingest/retrieval and project compilation. Web research, exchanges, cloud
services and package downloads inherently need connectivity.

Keep Freqtrade in a separate environment to avoid dependency conflicts; migrate
its data/configuration separately and verify it in paper mode before any live
use. LEAN, Docker images, datasets, fine-tuning tools and large models can push
the workstation well beyond 256 GB. Measure `df -h` and `du -sh` regularly.

## 10. Path audit after migration

Run from each active repository (install `ripgrep` with apt first):

```bash
sudo apt install ripgrep
cd "$HOME/Projects/Niblit"
rg -l --hidden -g '!.git/**' -g '!node_modules/**' -g '!niblit-env/**' \
  -g '!*.log' -g '!*.sqlite*' -g '!*.db' \
  'C:\\Users\\|C:/Users/|/mnt/c/|Scripts/python|python.exe|llama-server.exe|build/bin/Release'
```

This prints filenames rather than secret configuration values. Review active
launchers, dotenv files, editor settings, workspace files, subprocess commands,
model registries and service definitions. Do not mass-replace historical logs,
dataset text, database payloads or documentation examples. Replace PATH lists
using Linux `:` separators; use `/` for Linux paths. Check case sensitivity,
executable permissions, external-drive mounts, and imports with a different
working directory. Recreate environments after moving them; venv scripts and
compiled artifacts can contain absolute paths. Record old-to-new mappings and
test Core, UI, cloud, model inference and memory independently before removing
any backup. This audit is still pending on the actual Ubuntu installation.

## Sources and verification limits

- llama.cpp build/Vulkan: https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md
- Tauri Linux prerequisites: https://v2.tauri.app/start/prerequisites/
- Docker Ubuntu install: https://docs.docker.com/engine/install/ubuntu/
- Ubuntu UEFI: https://help.ubuntu.com/community/UEFI

Reviewed local requirements, launchers, cloud config/provider, model files,
Windows CMake cache and memory lab compose/setup. This is a migration runbook,
not a claim of full Windows-to-Linux feature parity. Native Ubuntu runtime,
GPU acceleration, packaged desktop, restored state and offline acceptance
checks remain to be performed after installation.
