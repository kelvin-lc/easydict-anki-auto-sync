#!/usr/bin/env python3
"""Stop automatic sync while preserving cards and optional local queue."""
import argparse
import os
import pathlib
import subprocess

LABEL = 'local.easydict.anki-sync'
AGENT = pathlib.Path.home() / 'Library/LaunchAgents' / (LABEL + '.plist')
DATA = pathlib.Path.home() / 'Library/Application Support/EasydictAnkiSync'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--remove-local-data', action='store_true',
                        help='also remove the local queue, cached MP3, and logs')
    args = parser.parse_args()
    if AGENT.exists():
        subprocess.run(['launchctl', 'bootout', f'gui/{os.getuid()}', str(AGENT)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        AGENT.unlink()
    if args.remove_local_data and DATA.exists():
        # Deliberately leave data removal as a separate, explicit step.
        import shutil
        shutil.rmtree(DATA)
    print('Automatic sync stopped. Anki cards are unchanged.')
    if not args.remove_local_data:
        print(f'Local queue and cache preserved at {DATA}')


if __name__ == '__main__':
    main()
