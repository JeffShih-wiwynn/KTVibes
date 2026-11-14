#!/usr/bin/env bash
# Run the real installer against this checkout, with real CPU packages and systemd.
set -euo pipefail
task_dir="$(mktemp -d)"
trap 'systemctl --user stop ktvibes.service 2>/dev/null || true' EXIT
export XDG_DATA_HOME="$task_dir/data with spaces"
export XDG_CACHE_HOME="$task_dir/cache"
app_dir="$XDG_DATA_HOME/ktvibes"
git clone --bare "$PWD" "$task_dir/origin.git"
git --git-dir="$task_dir/origin.git" update-ref refs/heads/ci-smoke HEAD
# Keep the installer unchanged while ensuring PRs test the checked-out commit.
git config --global url."file://$task_dir/origin.git".insteadOf https://github.com/JeffShih-wiwynn/KTVibes.git
bash install.sh --branch ci-smoke
test -x "$HOME/.local/bin/ktvibes"
"$HOME/.local/bin/ktvibes" --install
systemd-analyze --user verify "$HOME/.config/systemd/user/ktvibes.service"
test "$(systemctl --user show ktvibes.service --property=WorkingDirectory --value)" = "$app_dir"
service_diagnostics() {
  systemctl --user status ktvibes.service --no-pager || true
  journalctl --user -u ktvibes.service --no-pager -n 80 || true
}
wait_for_server() {
  for attempt in {1..90}; do
    if ! systemctl --user is-active --quiet ktvibes.service; then
      service_diagnostics
      return 1
    fi
    if curl -fsS --max-time 2 http://127.0.0.1:8765/api/config > "$task_dir/config.json" 2>/dev/null; then
      curl -fsS --max-time 2 http://127.0.0.1:8765/remote > "$task_dir/remote.html"
      return
    fi
    sleep 1
  done
  service_diagnostics
  return 1
}
systemctl --user start ktvibes.service
wait_for_server
"$app_dir/.venv/bin/python" "$app_dir/tools/ci/linux-power-smoke.py"
first_head="$(git -C "$app_dir" rev-parse HEAD)"
mkdir -p "$app_dir/cache"
echo preserved > "$app_dir/cache/ci-sentinel"
git clone "$task_dir/origin.git" "$task_dir/update"
git -C "$task_dir/update" checkout ci-smoke
git -C "$task_dir/update" -c user.name=CI -c user.email=ci@example.invalid commit --allow-empty -m 'CI update fixture'
git -C "$task_dir/update" push origin ci-smoke
systemctl --user stop ktvibes.service
bash install.sh --branch ci-smoke
test "$(git -C "$app_dir" rev-parse HEAD)" != "$first_head"
test "$(cat "$app_dir/cache/ci-sentinel")" = preserved
systemctl --user start ktvibes.service
wait_for_server
systemctl --user is-active --quiet ktvibes.service
echo 'Linux install, launcher, service, HTTP readiness and update passed.'
