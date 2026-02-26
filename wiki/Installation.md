# Installation

Flexiconv is a regular Python package with a CLI entry point named `flexiconv`.

## Editable install (development)

From the repository root:

```bash
python -m pip install -e .
```

This installs the package and the `flexiconv` wrapper script, so you can run:

```bash
flexiconv input.ext output.ext
```

instead of:

```bash
python -m flexiconv input.ext output.ext
```

## Optional extras

The `flexiconv install` command provides convenience helpers for some extras:

```bash
flexiconv install rtf        # install RTF reader dependencies
flexiconv install tei-corpo  # (placeholder) TEI-CORPO integration
flexiconv install annatto    # integration with the Annatto annotation tool
```

These subcommands either print the `pip` command to run, or run it directly (see the CLI help or source for details).

## Wrapper and PATH

After installation, make sure your Python environment’s `bin` directory is on `PATH` so that the `flexiconv` command is visible. On Unix-like systems this is typically:

```bash
~/.local/bin   # user installs
```

or the `bin/` directory of your virtual environment.

