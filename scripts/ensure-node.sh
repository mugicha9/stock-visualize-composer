#!/usr/bin/env bash
set -euo pipefail

NODE_VERSION="${NODE_VERSION:-20.19.0}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NODE_DIR="${ROOT_DIR}/.node"
NODE_BIN="${NODE_DIR}/bin/node"

if [ -x "${NODE_BIN}" ]; then
  if "${NODE_BIN}" -e "const [major, minor] = process.versions.node.split('.').map(Number); process.exit(major > 20 || (major === 20 && minor >= 19) ? 0 : 1)"; then
    exit 0
  fi
fi

arch="$(uname -m)"
case "${arch}" in
  x86_64)
    node_arch="x64"
    ;;
  aarch64|arm64)
    node_arch="arm64"
    ;;
  *)
    echo "Unsupported CPU architecture for local Node.js: ${arch}" >&2
    exit 1
    ;;
esac

archive="node-v${NODE_VERSION}-linux-${node_arch}.tar.xz"
url="https://nodejs.org/dist/v${NODE_VERSION}/${archive}"
tmp_dir="${ROOT_DIR}/.node-tmp"
tmp_file="${tmp_dir}/${archive}"

mkdir -p "${tmp_dir}"
echo "Installing local Node.js v${NODE_VERSION} for linux-${node_arch}..."
curl -fsSL "${url}" -o "${tmp_file}"
rm -rf "${NODE_DIR}"
mkdir -p "${NODE_DIR}"
tar -xJf "${tmp_file}" -C "${NODE_DIR}" --strip-components=1
rm -rf "${tmp_dir}"

"${NODE_BIN}" -v
