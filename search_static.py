#!/usr/bin/env python3
"""
Static search functionality for the SonarEx Nautilus extension.

Where the interactive search (search_ugrep.py) hands the user over to ugrep's
live TUI, this module runs a one-shot search: a terminal opens and prompts for
a search string, ugrep collects the full paths of the matching files, and the
results are presented in a scrollable zenity list the user can click through to
open files.

All of the terminal-side work happens in the companion `search_static.sh`
script that lives next to this module, so more prompts/options can be added
there without touching the extension. That script in turn hands the results to
`search_results_dialog.sh`, which owns the zenity dialog.
"""

import os
import shutil
import urllib.parse
import subprocess

from search_ugrep import SearchHandler


class StaticSearchHandler(SearchHandler):
    """Runs a one-shot ugrep search and shows the hits in a zenity list."""

    SCRIPT_NAME = 'search_static.sh'

    def __init__(self, config_file, vscode_path):
        """
        Initialize the static search handler.

        Args:
            config_file (str): Path to the SonarEx config file
            vscode_path (str): Path to the VS Code executable
        """
        super().__init__(config_file)
        self.vscode_path = vscode_path

    def _get_script_path(self):
        """Return the path of the shell script installed alongside this module."""
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), self.SCRIPT_NAME)

    def search_folder_static(self, menu, folder):
        """
        Prompt for a search string in a terminal and list the hits in zenity.

        Opens a gnome-terminal running `search_static.sh`, which asks the user
        for a search string and then runs `ugrep -r -i -l -% --files` over the
        selected folder. As with the interactive search, -% enables Boolean
        query mode ("quoted phrases" are literal, space/AND requires all terms,
        OR matches any, NOT/- excludes) and --files applies the query at
        whole-file scope. The script then sorts the hits by modification time,
        newest first. The matching paths are then displayed by
        `search_results_dialog.sh` in a scrollable zenity list that stays open
        while the user opens files from it; the terminal closes itself once the
        search finishes.

        Args:
            menu (Nautilus.MenuItem): The menu item that triggered this action (unused).
            folder (Nautilus.FileInfo): The folder to search within.

        Requirements:
            - ugrep: For the search itself (sudo apt install ugrep)
            - gnome-terminal: To host the prompt
            - zenity: For the results list
            - pdftotext (optional, from poppler-utils): For PDF content search
        """
        if not folder.get_uri().startswith('file://'):
            return

        folder_path = urllib.parse.unquote(folder.get_uri()[7:])

        # If it's a file selection, use the parent directory
        if not folder.is_directory():
            folder_path = os.path.dirname(folder_path)

        script_path = self._get_script_path()
        if not os.path.exists(script_path):
            print(f'Static search script not found: {script_path}')
            return

        # Extra ugrep arguments are passed through as separate argv entries,
        # so no shell quoting is involved anywhere in the chain.
        ugrep_args = []
        if shutil.which('pdftotext'):
            ugrep_args.append('--filter=pdf:pdftotext -q % -')
        ugrep_args.extend(self.build_ugrep_glob_list(
            self._get_search_patterns('excluded'),
            self._get_search_patterns('included'),
        ))

        try:
            subprocess.Popen([
                'gnome-terminal',
                f'--working-directory={folder_path}',
                '--',
                'bash', script_path, folder_path, self.vscode_path, *ugrep_args,
            ])
        except Exception as e:
            print(f'Error launching static search: {e}')
