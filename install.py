#!/usr/bin/env python3
"""Install or update the per-user macOS LaunchAgent."""
import argparse
import json
import os
import pathlib
import plistlib
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime

LABEL = 'local.easydict.anki-sync'
APP_DIR = pathlib.Path.home() / 'Library/Application Support/EasydictAnkiSync'
AGENT = pathlib.Path.home() / 'Library/LaunchAgents' / (LABEL + '.plist')


def active_profile():
    request = urllib.request.Request(
        'http://127.0.0.1:8765',
        data=json.dumps({'action': 'getActiveProfile', 'version': 6}).encode(),
        headers={'Content-Type': 'application/json'},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        result = json.load(opener.open(request, timeout=3))
    except (OSError, ValueError):
        return None
    return result.get('result') if not result.get('error') else None


def main():
    parser = argparse.ArgumentParser(description='Install Easydict → Anki automatic sync')
    parser.add_argument('--profile', help='Anki profile name; detected from running Anki when omitted')
    parser.add_argument('--deck', default='Easydict 生词', help='destination deck')
    parser.add_argument('--interval', type=int, default=300, help='scan interval in seconds (min 60)')
    parser.add_argument('--voice', default='Samantha', help='macOS say voice')
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.error('this integration currently requires macOS')
    if args.interval < 60:
        parser.error('--interval must be at least 60 seconds')
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        parser.error('ffmpeg is required; install it with: brew install ffmpeg')
    if not pathlib.Path('/Applications/Easydict.app').exists():
        parser.error('Easydict.app was not found in /Applications')
    profile = args.profile or active_profile()
    if not profile:
        parser.error('open Anki with AnkiConnect enabled, or pass --profile "your profile name"')
    APP_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    APP_DIR.chmod(0o700)
    AGENT.parent.mkdir(parents=True, exist_ok=True)

    # A second install updates the program without discarding the queue or audio.
    if AGENT.exists():
        subprocess.run(['launchctl', 'bootout', f'gui/{os.getuid()}', str(AGENT)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        backup = APP_DIR / ('install-backup-' + stamp)
        backup.mkdir()
        shutil.copy2(AGENT, backup / AGENT.name)
        if (APP_DIR / 'sync.py').exists():
            shutil.copy2(APP_DIR / 'sync.py', backup / 'sync.py')
        print(f'Previous program and agent saved to {backup}')

    shutil.copy2(pathlib.Path(__file__).with_name('sync.py'), APP_DIR / 'sync.py')
    environment = {
        'EASYDICT_ANKI_PROFILE': profile,
        'EASYDICT_ANKI_DECK': args.deck,
        'EASYDICT_ANKI_POLL_SECONDS': str(args.interval),
        'EASYDICT_ANKI_VOICE': args.voice,
        'EASYDICT_ANKI_FFMPEG': ffmpeg,
    }
    spec = {
        'Label': LABEL,
        'ProgramArguments': [sys.executable, str(APP_DIR / 'sync.py')],
        'EnvironmentVariables': environment,
        'RunAtLoad': True,
        'KeepAlive': True,
        'ProcessType': 'Background',
        'ThrottleInterval': 15,
        'StandardErrorPath': str(APP_DIR / 'service-error.log'),
        'StandardOutPath': str(APP_DIR / 'service-output.log'),
    }
    AGENT.write_bytes(plistlib.dumps(spec))
    subprocess.run(['launchctl', 'bootstrap', f'gui/{os.getuid()}', str(AGENT)], check=True)
    print(f'Installed for Anki profile {profile!r}, deck {args.deck!r}; scans every {args.interval}s.')
    print('Keep AnkiConnect installed. Open Anki to import queued cards; sync Anki to upload media.')


if __name__ == '__main__':
    main()
