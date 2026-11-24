"""Double-click to launch the floating JARVIS desktop assistant."""
import os
from pathlib import Path
import socket
import subprocess
import sys

from jarvis.agent.desktop import main


def start_console_if_needed():
    try:
        with socket.create_connection(('127.0.0.1', 8767), timeout=.5):
            return
    except OSError:
        pass
    project = Path(__file__).resolve().parent
    configured = (project / 'jarvis' / '.secrets' / 'google-oauth.json').is_file()
    environment = os.environ.copy()
    environment.setdefault('JARVIS_DEMO', '0' if configured else '1')
    subprocess.Popen(
        [sys.executable, '-B', '-m', 'jarvis.agent.main'], cwd=project, env=environment,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


if __name__ == '__main__':
    if os.name == 'nt':
        start_console_if_needed()
    main()
