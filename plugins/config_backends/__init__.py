"""Config backends (``NORYKA_CONFIG_BACKEND``). Selected by ``noryka_cli.config_backend``
directly from the environment, never discovered through the general plugin loader: that loader
reads config.yaml, and the backend is what serves config.yaml (D11). User plugins cannot supply a
config backend."""
