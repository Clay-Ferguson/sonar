#!/usr/bin/env python3

import os
import subprocess
from gi.repository import Nautilus, GObject

# Import our handlers
from search_ugrep import SearchHandler
from search_static import StaticSearchHandler

class SonarExMenuItems(GObject.GObject, Nautilus.MenuProvider):
    """
    A Nautilus file manager extension that adds recursive search actions to the
    right-click context menu.

    SonarEx contributes two search entries — an interactive ugrep TUI and a
    one-shot "static" search that presents its matches in a clickable dialog —
    plus a shortcut for opening its own YAML configuration file.

    Inherits from:
        GObject.GObject: Base class for GObject-based objects
        Nautilus.MenuProvider: Interface for providing custom menu items in Nautilus

    Class Constants:
        VSCODE_PATH (str): Path to the VSCode executable
        CONFIG_FILE (str): Path to the SonarEx YAML configuration file

    Menu Actions Provided:
        - Search (Interactive): Live ugrep TUI in a terminal, rooted at the folder
        - Search (Static): Search once, then browse the matching files in a dialog
        - Open SonarEx Configs: Opens the YAML config in VSCode
    """
    VSCODE_PATH = '/usr/bin/code'
    CONFIG_FILE = os.path.expanduser('~/.config/sonarex/sonarex-config.yaml')

    def __init__(self):
        """
        Initialize the Nautilus extension.

        Calls the parent class constructor to properly initialize the GObject
        and Nautilus MenuProvider interfaces. This method is called automatically
        when Nautilus loads the extension.
        """
        super().__init__()
        # Initialize the handlers
        self.search_handler = SearchHandler(self.CONFIG_FILE)
        self.static_search_handler = StaticSearchHandler(self.CONFIG_FILE, self.VSCODE_PATH)

    def get_file_items(self, files):
        """
        Add context menu items when files or folders are selected.

        This method is called by Nautilus when the user right-clicks on selected
        files or folders. It analyzes the selection and provides appropriate menu
        items based on the file type and context.

        Args:
            files (list): List of Nautilus.FileInfo objects representing selected files/folders.
                         Only processes single selections (len(files) == 1).

        Returns:
            list: List of Nautilus.MenuItem objects to display in the context menu.
                  Returns empty list if multiple files are selected.

        Menu Items Added:
            - Search (Interactive): Available for directories
            - Search (Static): Available for directories
            - Open SonarEx Configs: Always available for any single selection
        """
        if len(files) != 1:
            return []

        file = files[0]
        items = []

        # Add Search for directories (first items)
        if file.is_directory():
            search_item = Nautilus.MenuItem(
                name='SonarExMenuItems::search',
                label='🔍  Search (Interactive)',
                tip='Interactive search in a terminal'
            )
            search_item.connect('activate', self.search_folder, file)
            items.append(search_item)

            static_search_item = Nautilus.MenuItem(
                name='SonarExMenuItems::search_static',
                label='🔍  Search (Static)',
                tip='Search once and open the list of matching files in VSCode'
            )
            static_search_item.connect('activate', self.search_folder_static, file)
            items.append(static_search_item)

        # Add Open SonarEx Configs option
        config_item = Nautilus.MenuItem(
            name='SonarExMenuItems::open_sonarex_configs',
            label='⚙️  Open SonarEx Configs',
            tip='Open SonarEx configuration file in VSCode'
        )
        config_item.connect('activate', self.open_sonarex_configs)
        items.append(config_item)

        return items

    def get_background_items(self, current_folder):
        """
        Add context menu items when right-clicking on empty space in Nautilus.

        This method is called by Nautilus when the user right-clicks on empty space
        within a folder view, providing context menu options relevant to the current
        directory without any specific file selection.

        Args:
            current_folder (Nautilus.FileInfo): Object representing the current folder
                                               being viewed in Nautilus.

        Returns:
            list: List of Nautilus.MenuItem objects to display in the context menu.

        Menu Items Added:
            - Search (Interactive): Recursively search the current folder
            - Search (Static): Search the current folder once and browse the matches
            - Open SonarEx Configs: Opens the YAML config in VSCode
        """
        items = []

        # Search for current folder (first items)
        search_item = Nautilus.MenuItem(
            name='SonarExMenuItems::search_current',
            label='🔍  Search (Interactive)',
            tip='Interactive search in a terminal'
        )
        search_item.connect('activate', self.search_folder, current_folder)
        items.append(search_item)

        static_search_item = Nautilus.MenuItem(
            name='SonarExMenuItems::search_static_current',
            label='🔍  Search (Static)',
            tip='Search once and open the list of matching files in VSCode'
        )
        static_search_item.connect('activate', self.search_folder_static, current_folder)
        items.append(static_search_item)

        # Open SonarEx Configs option
        config_item = Nautilus.MenuItem(
            name='SonarExMenuItems::open_sonarex_configs_bg',
            label='⚙️  Open SonarEx Configs',
            tip='Open SonarEx configuration file in VSCode'
        )
        config_item.connect('activate', self.open_sonarex_configs)
        items.append(config_item)

        return items

    def search_folder(self, menu, folder):
        """
        Delegate to the search handler for interactive folder search.

        This is a wrapper method that maintains the existing menu interface
        while delegating the actual search functionality to the SearchHandler.
        """
        self.search_handler.search_folder(menu, folder)

    def search_folder_static(self, menu, folder):
        """
        Delegate to the static search handler for one-shot folder search.

        Prompts for a search string in a terminal, writes the matching file
        paths to a temp file, and opens them in a clickable results dialog.
        """
        self.static_search_handler.search_folder_static(menu, folder)

    def open_sonarex_configs(self, menu, file=None):
        """
        Open the SonarEx configuration file in Visual Studio Code.

        This method opens the YAML configuration file located at
        ~/.config/sonarex/sonarex-config.yaml directly in VSCode, allowing users
        to quickly edit their SonarEx search settings.

        Args:
            menu (Nautilus.MenuItem): The menu item that triggered this action (unused).
            file (Nautilus.FileInfo, optional): The file context (unused, since we always
                                               open the config file regardless of context).

        Behavior:
            - Opens the config file at ~/.config/sonarex/sonarex-config.yaml
            - Uses the VSCode path specified in VSCODE_PATH constant
            - Works from any context (file selection or background menu)
        """
        subprocess.Popen([self.VSCODE_PATH, self.CONFIG_FILE])
