# Contributing to Noryka

Thank you for contributing to **Noryka** (`https://github.com/yusi20006-max/NORYKA`).

## Development Setup

1. Create a virtual environment and install in editable mode:
   ```bash
   bash install-noryka-termux.sh
   ```
2. Run the smoke & regression test suite before submitting changes:
   ```bash
   pytest tests/test_noryka_smoke.py
   ```
3. Verify Python AST syntax across modified modules using the built-in `ast_code_analyzer` tool.
