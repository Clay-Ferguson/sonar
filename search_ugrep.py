#!/usr/bin/env python3
"""
Search functionality for the SonarEx Nautilus extension.

This module launches ugrep's interactive query TUI (-Q) in a terminal,
letting the user type a search pattern and see live results as they type.
No zenity dialogs are needed—all interaction happens inside ugrep's own
terminal UI.

It honors the search.excluded and search.included glob patterns from the
SonarEx config file.
"""

import os
import shlex
import shutil
import urllib.parse
import subprocess

# Try to import yaml for config file support
try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False


class SearchHandler:
    """Handles interactive search operations using the ugrep TUI."""

    def __init__(self, config_file):
        """
        Initialize the search handler.

        Args:
            config_file (str): Path to the SonarEx config file
        """
        self.config_file = config_file

    def _load_config(self):
        """
        Load configuration from YAML file.

        Returns:
            dict: Configuration dictionary, or empty dict if config can't be loaded.
        """
        if not YAML_AVAILABLE:
            return {}

        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    return yaml.safe_load(f) or {}
            else:
                print(f"Config file not found: {self.config_file}")
                return {}
        except Exception as e:
            print(f"Error loading config file: {e}")
            return {}

    def _get_search_patterns(self, pattern_type):
        """
        Get search patterns from config file.

        Args:
            pattern_type (str): Either 'excluded' or 'included'

        Returns:
            list: List of glob patterns, or empty list.
        """
        config = self._load_config()

        try:
            patterns = config.get('search', {}).get(pattern_type, [])
            if isinstance(patterns, list):
                return patterns
            else:
                return []
        except Exception as e:
            print(f"Error reading {pattern_type} patterns from config: {e}")
            return []

    def _convert_excluded_pattern_to_ugrep_glob(self, pattern):
        """
        Convert a find-style exclusion pattern to a ugrep -g exclusion glob.

        The config's excluded patterns use find's -path syntax, typically
        '*/node_modules/*'. ugrep's -g globs use gitignore-style syntax where
        '!NAME/' excludes directories named NAME anywhere in the tree, and
        '**' matches across path separators for full-pathname globs.

        Args:
            pattern (str): A find-style exclusion pattern (e.g., '*/node_modules/*')

        Returns:
            str: A ugrep exclusion glob (e.g., '!node_modules/')
        """
        # The common '*/NAME/*' directory form maps to ugrep's '!NAME/'
        # (a trailing '/' matches directories by basename anywhere)
        if pattern.startswith('*/') and pattern.endswith('/*'):
            middle = pattern[2:-2]
            if '/' not in middle:
                return f'!{middle}/'
            # Nested directory path: use a full-pathname glob
            return f'!**/{middle}/**'

        # Anything else (e.g., '*.log') excludes by basename as-is
        return f'!{pattern}'

    def build_ugrep_glob_list(self, excluded_patterns, included_patterns):
        """
        Build repeated -g arguments for ugrep from config patterns.

        Args:
            excluded_patterns (list): List of find-style exclusion glob patterns
            included_patterns (list): List of inclusion glob patterns

        Returns:
            list: Flat argv list, e.g. ['-g', '!node_modules/', '-g', '*.md']
        """
        args = []

        for pattern in excluded_patterns:
            args.extend(['-g', self._convert_excluded_pattern_to_ugrep_glob(pattern)])

        for pattern in included_patterns:
            args.extend(['-g', pattern])

        return args

    def _build_ugrep_glob_args(self, excluded_patterns, included_patterns):
        """
        Build repeated -g arguments for ugrep as a shell-quoted string.

        Args:
            excluded_patterns (list): List of find-style exclusion glob patterns
            included_patterns (list): List of inclusion glob patterns

        Returns:
            str: Space-separated, shell-quoted -g arguments for the ugrep command
        """
        args = self.build_ugrep_glob_list(excluded_patterns, included_patterns)
        return ' '.join(shlex.quote(arg) for arg in args)

    def search_folder(self, menu, folder):
        """
        Launch the ugrep interactive TUI scoped to the selected folder.

        Opens a gnome-terminal with the folder as the working directory and
        runs `ugrep -Q -% --files -r -i .` with -g globs built from the config
        file's search.excluded and search.included patterns. The -% flag
        enables Boolean query mode: "quoted phrases" match exactly/literally,
        space or AND requires all terms, OR/| matches any term, NOT/-
        excludes; unquoted terms are regex patterns. --files applies the
        Boolean query at whole-file scope rather than per line. When pdftotext is
        installed, PDF content is searched too via ugrep's --filter option
        (note: ugrep runs the filter command directly, not through a shell,
        so pdftotext's -q flag is used to suppress warnings rather than
        shell redirection). The user types the search pattern directly in
        the TUI. Useful TUI keys: F1 for help, Alt-i toggles
        case-insensitivity, Alt-g edits the active globs, F2/Ctrl-Y views
        the selected file, q quits.

        Args:
            menu (Nautilus.MenuItem): The menu item that triggered this action (unused).
            folder (Nautilus.FileInfo): The folder to search within.

        Requirements:
            - ugrep: For the interactive search TUI (sudo apt install ugrep)
            - gnome-terminal: To host the TUI
            - pdftotext (optional, from poppler-utils): For PDF content search
        """
        if not folder.get_uri().startswith('file://'):
            return

        folder_path = urllib.parse.unquote(folder.get_uri()[7:])

        # If it's a file selection, use the parent directory
        if not folder.is_directory():
            folder_path = os.path.dirname(folder_path)

        # Build -g glob arguments from config include/exclude patterns
        excluded_patterns = self._get_search_patterns('excluded')
        included_patterns = self._get_search_patterns('included')
        glob_args = self._build_ugrep_glob_args(excluded_patterns, included_patterns)

        # -% enables Boolean query mode: quoted "exact phrases", AND/OR/NOT
        # operators, space = AND; unquoted terms are still regex patterns.
        # --files applies the Boolean query to whole files instead of lines
        # (e.g. "cat" AND "dog" matches a file with the terms on different lines)
        cmd_parts = ['ugrep', '-Q', '-%', '--files', '-r', '-i']
        if shutil.which('pdftotext'):
            cmd_parts.append(shlex.quote('--filter=pdf:pdftotext -q % -'))
        if glob_args:
            cmd_parts.append(glob_args)
        cmd_parts.append('.')
        ugrep_cmd = ' '.join(cmd_parts)

        # Check for ugrep inside the terminal so missing-dependency instructions
        # are shown to the user
        inner = (
            'if ! command -v ugrep >/dev/null 2>&1; then '
            'echo "ERROR: ugrep not found. Please install it:"; '
            'echo "  sudo apt install ugrep"; '
            'echo ""; '
            'echo "Press Enter to exit..."; '
            'read; '
            'exit 1; '
            'fi; '
            f'{ugrep_cmd}'
        )

        try:
            # Working directory set to the folder so the TUI shows short relative paths;
            # searching '.' with -r recurses from there. -i presets case-insensitive
            # matching; toggle in TUI via Alt-i.
            subprocess.Popen([
                'gnome-terminal',
                f'--working-directory={folder_path}',
                '--',
                'bash', '-c', inner,
            ])
        except Exception as e:
            print(f'Error launching ugrep search: {e}')
