#!/usr/bin/env bash
# KTVibes Linux installer. macOS is distributed as a DMG.
[ -n "${BASH_VERSION:-}" ] || exec bash "$0" "$@"
set -euo pipefail

channel=stable
while (($#)); do
  case "$1" in
    --channel)
      if (($# < 2)); then
        echo "Usage: install.sh [--channel stable|dev]" >&2
        exit 2
      fi
      channel="$2"
      shift 2
      ;;
    --channel=*)
      channel="${1#*=}"
      shift
      ;;
    -h|--help)
      echo "Usage: install.sh [--channel stable|dev]"
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      echo "Usage: install.sh [--channel stable|dev]" >&2
      exit 2
      ;;
  esac
done

if [[ "$channel" != stable && "$channel" != dev ]]; then
  echo "Invalid channel '$channel'. Choose 'stable' or 'dev'." >&2
  exit 2
fi

if [[ "$(uname -s)" != Linux ]]; then
  echo "This installer is for Linux. On macOS, install KTVibes from the DMG release." >&2
  exit 1
fi

for tool in git curl ffmpeg node systemctl journalctl ip; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "Missing required command: $tool" >&2
    echo "Install it with your distribution's package manager, then run this installer again." >&2
    exit 1
  fi
done
if (( $(node -p 'process.versions.node.split(".")[0]') < 22 )); then
  echo "Node.js 22 or later is required (https://nodejs.org or nvm)." >&2
  exit 1
fi

if [[ "$channel" == dev ]]; then
  target_ref=refs/heads/dev
  echo "Installing the dev channel."
else
  release_api="https://api.github.com/repos/JeffShih-wiwynn/KTVibes/releases/latest"
  if ! release_tag="$(curl -fsSL -H 'Accept: application/vnd.github+json' "$release_api" | node -e '
    let body = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", chunk => body += chunk);
    process.stdin.on("end", () => {
      const release = JSON.parse(body);
      if (typeof release.tag_name !== "string") process.exitCode = 1;
      else process.stdout.write(release.tag_name);
    });
  ')"; then
    echo "Could not determine the latest stable GitHub Release." >&2
    exit 1
  fi
  if [[ ! "$release_tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "Unexpected stable release tag: $release_tag" >&2
    exit 1
  fi
  target_ref="refs/tags/$release_tag"
  echo "Installing stable release $release_tag."
fi

if ! systemctl --user show-environment >/dev/null 2>&1; then
  echo "A running systemd user session is required. Use uv run ktvibes for foreground operation." >&2
  exit 1
fi

data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
cache_home="${XDG_CACHE_HOME:-$HOME/.cache}"
app_dir="$data_home/ktvibes"
bin_dir="$HOME/.local/bin"
repo="https://github.com/JeffShih-wiwynn/KTVibes.git"

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="${UV_INSTALL_DIR:-$HOME/.local/bin}:$HOME/.local/bin:$PATH"
fi

mkdir -p "$data_home" "$cache_home/ktvibes" "$bin_dir"
if [[ -e "$app_dir" && ! -d "$app_dir/.git" ]]; then
  echo "Refusing to replace $app_dir because it is not a KTVibes Git installation." >&2
  exit 1
elif [[ -d "$app_dir/.git" ]]; then
  git -C "$app_dir" remote set-url origin "$repo"
  if [[ -n "$(git -C "$app_dir" status --porcelain)" ]]; then
    echo "Refusing to update $app_dir because it contains local changes." >&2
    echo "Back up or discard those changes, then run the installer again." >&2
    exit 1
  fi
else
  git clone "$repo" "$app_dir"
fi
git -C "$app_dir" fetch origin "$target_ref"
git -C "$app_dir" reset --hard FETCH_HEAD

(cd "$app_dir" && uv run --no-project --python 3.12 python -m ktvibes.acceleration install)
export KTVIBES_CACHE="$data_home/ktvibes/cache"
(cd "$app_dir" && .venv/bin/python -m ktvibes.linux --install)

cat > "$bin_dir/ktvibes" <<LAUNCHER
#!/usr/bin/env bash
set -euo pipefail
export KTVIBES_CACHE="\${XDG_DATA_HOME:-\$HOME/.local/share}/ktvibes/cache"
export XDG_CACHE_HOME="\${XDG_CACHE_HOME:-\$HOME/.cache}"
cd "$app_dir"
exec "$app_dir/.venv/bin/python" -m ktvibes.linux "\$@"
LAUNCHER
chmod 755 "$bin_dir/ktvibes"

installation_config="${XDG_CONFIG_HOME:-$HOME/.config}/ktvibes"
mkdir -p "$installation_config"
printf '{"channel":"%s"}\n' "$channel" > "$installation_config/installation.json.tmp"
mv "$installation_config/installation.json.tmp" "$installation_config/installation.json"

echo
echo "KTVibes installed. Run: $bin_dir/ktvibes"
echo "The TUI starts the service and opens Player when ready. Ctrl+C detaches; Quit stops the server."
case ":${PATH}:" in
  *":$bin_dir:"*) ;;
  *) echo "Add $bin_dir to PATH to run 'ktvibes' directly." ;;
esac
