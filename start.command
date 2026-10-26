#!/bin/sh
# Start the app. Double-click on macOS (.command) or run ./start.sh in a terminal.
cd "$(dirname "$0")" || exit 1
PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
export PATH

pause_on_error() {
    if [ -t 0 ]; then
        printf 'Press Enter to close this window. '
        read -r _ignored
    fi
}

if ! command -v uv >/dev/null 2>&1; then
    echo "Installing uv (the tool that manages Python for this app)..."
    if ! curl -LsSf https://astral.sh/uv/install.sh | sh; then
        echo "Could not install uv. Check your internet connection and try again."
        pause_on_error
        exit 1
    fi
    PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    export PATH
fi

uv run python -m medimg serve "$@"
status=$?
if [ "$status" -ne 0 ]; then
    echo "Stopped with an error (code $status). Read the message above."
    pause_on_error
fi
exit "$status"
