#!/bin/sh
# Run the self-test. Double-click on macOS (.command) or run ./selftest.sh in a terminal.
# This does not install anything and does not use the network.
cd "$(dirname "$0")" || exit 1
PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
export PATH

wait_for_enter() {
    if [ -t 0 ]; then
        printf 'Press Enter to close this window. '
        read -r _ignored
    fi
}

if ! command -v uv >/dev/null 2>&1 || [ ! -d .venv ]; then
    echo "Setup has not been run on this computer yet. Run setup first (double-click setup.command on a Mac, or run ./setup.sh), then run this again."
    wait_for_enter
    exit 1
fi

uv run --no-sync python -m medimg selftest "$@"
status=$?
if [ "$status" -eq 0 ]; then
    echo "Self-test passed."
else
    echo "The self-test found a problem (code $status)."
fi
echo "Send both report files named above to the project owner."
wait_for_enter
exit "$status"
