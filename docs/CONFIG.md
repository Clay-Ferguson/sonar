# SonarEx Configuration

SonarEx uses a YAML configuration file located at `~/.config/sonarex/sonarex-config.yaml`.

## Configuration Options

### Search Inclusions

You can limit searches to specific file types using glob patterns. If the `included` list is empty or omitted, all files are searched (subject to exclusions).

```yaml
search:
  included:
    - "*.md"      # Only search Markdown files
    - "*.txt"     # And text files
```

**Note:** When include patterns are specified, only files matching these patterns will be searched.

#### Common Include Patterns

**Documentation:**
- `*.md` - Markdown files
- `*.txt` - Plain text files
- `*.rst` - ReStructuredText files

**Code:**
- `*.py` - Python files
- `*.js` - JavaScript files
- `*.ts` - TypeScript files
- `*.java` - Java files
- `*.cpp` - C++ files
- `*.h` - Header files

**Leave empty to search all files:**
```yaml
search:
  included: []   # Search all file types
```

### Search Exclusions

You can exclude specific directories and files from search results using glob patterns.

```yaml
search:
  excluded:
    - "*/node_modules/*"    # Exclude all node_modules directories
    - "*/.git/*"            # Exclude .git directories
    - "*/.venv/*"           # Exclude Python virtual environments
    - "*/__pycache__/*"     # Exclude Python cache directories
```

#### How Exclusions Work

- Exclusions use **glob patterns**, which SonarEx converts into `ugrep -g` exclusion globs
- The `*` wildcard matches any characters
- Patterns are matched against the full path
- Excluded directories are pruned from the search (not descended into)
- Press `Alt-g` inside the search TUI to view or edit the active globs for that session

#### Common Patterns to Exclude

**JavaScript/Node.js:**
- `*/node_modules/*` - npm packages
- "*/.next/*" - Next.js build output
- `*/.nuxt/*` - Nuxt.js build output
- `*/dist/*` - Distribution/build output
- `*/build/*` - Build artifacts

**Python:**
- `*/.venv/*` - Virtual environments
- `*/venv/*` - Alternative venv naming
- `*/__pycache__/*` - Compiled bytecode
- `*/.pytest_cache/*` - Pytest cache
- `*.egg-info/*` - Package metadata

**Version Control:**
- `*/.git/*` - Git repository data
- `*/.svn/*` - Subversion data
- `*/.hg/*` - Mercurial data

**IDEs:**
- `*/.vscode/*` - VS Code settings
- `*/.idea/*` - JetBrains IDE settings
- `*/.eclipse/*` - Eclipse settings

**Other:**
- `*/target/*` - Java/Maven build output
- `*/bin/*` - Compiled binaries
- `*/obj/*` - Object files (.NET, C++)
- `*/.cache/*` - Cache directories

#### Adding Your Own Exclusions

Edit `~/.config/sonarex/sonarex-config.yaml` and add patterns to the `excluded` list:

```yaml
search:
  included:
    - "*.md"
    - "*.txt"
  
  excluded:
    - "*/node_modules/*"
    - "*/.git/*"
    - "*/my_custom_dir/*"      # Add your custom exclusion here
    - "*/temp/*"               # Exclude temporary directories
    - "*/.backup/*"            # Exclude backup directories
```

Changes take effect immediately on the next search - no need to restart Nautilus.

### Using Include and Exclude Patterns Together

Include and exclude patterns work together to give you fine-grained control over what gets searched:

1. **Exclusions are applied first** - Directories matching exclude patterns are skipped entirely
2. **Inclusions filter the remaining files** - Only files matching include patterns are searched

**Example: Search only Python files, excluding virtual environments:**
```yaml
search:
  included:
    - "*.py"           # Only search Python files
  
  excluded:
    - "*/.venv/*"      # Skip virtual environment directories
    - "*/__pycache__/*"  # Skip cache directories
```

**Example: Search documentation only:**
```yaml
search:
  included:
    - "*.md"
    - "*.txt"
    - "*.rst"
  
  excluded:
    - "*/node_modules/*"
    - "*/.git/*"
```

**Example: Search everything (default behavior):**
```yaml
search:
  included: []         # Empty or omit to search all file types
  
  excluded:
    - "*/node_modules/*"
    - "*/.git/*"
```

## Default Configuration

When you first run `./setup.sh`, a default configuration file is created with sensible exclusions for common development directories. You can customize it to match your workflow.

## Troubleshooting

**Config file not found:**
- Run `./setup.sh` to create the default config
- Or manually create `~/.config/sonarex/sonarex-config.yaml`

**Exclusions not working:**
- Check the config file syntax (YAML is indentation-sensitive)
- Verify glob patterns match your directory structure
- Check terminal output during search for any error messages

**Python YAML library not available:**
- Install it: `sudo apt install python3-yaml`
- Or run `./setup.sh` which installs it automatically
