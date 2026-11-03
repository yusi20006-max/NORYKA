"""Shared YAML 1.1 policy for config, manifests, and frontmatter.

Uses ruamel.yaml when installed, with automatic fallback to PyYAML (yaml)
so lean Termux/Linux environments work without mandatory ruamel installation.
"""

from io import StringIO
from typing import Any, IO, overload

ROUNDTRIP_YAML_WIDTH = 2**31 - 1

try:
    from ruamel.yaml import YAML
    from ruamel.yaml.error import YAMLError
    from ruamel.yaml.resolver import VersionedResolver

    class _Yaml11Resolver(VersionedResolver):
        @property
        def processing_version(self) -> tuple[int, int]:
            return (1, 1)

    def _load(document: str | bytes, *, pure: bool) -> Any:
        yaml = YAML(typ="safe", pure=pure)
        yaml.version = (1, 1)
        return yaml.load(document)

    def safe_load(stream: str | bytes | IO[str] | IO[bytes]) -> Any:
        document = stream if isinstance(stream, (str, bytes)) else stream.read()
        try:
            return _load(document, pure=False)
        except YAMLError:
            return _load(document, pure=True)

    def safe_dump(
        data: Any,
        stream: IO[str] | None = None,
        *,
        default_flow_style: bool = False,
        sort_keys: bool = True,
        allow_unicode: bool = True,
        width: int = 80,
    ) -> str | None:
        yaml = YAML(typ="safe", pure=True)
        yaml.Resolver = _Yaml11Resolver
        yaml.default_flow_style = default_flow_style
        yaml.allow_unicode = allow_unicode
        yaml.width = width
        yaml.sort_base_mapping_type_on_output = sort_keys
        yaml.indent(mapping=2, sequence=4, offset=2)
        if stream is not None:
            yaml.dump(data, stream)
            return None
        output = StringIO()
        yaml.dump(data, output)
        return output.getvalue()

    def roundtrip_yaml() -> YAML:
        yaml = YAML(typ="rt")
        yaml.width = ROUNDTRIP_YAML_WIDTH
        yaml.Resolver = _Yaml11Resolver
        yaml.preserve_quotes = True
        yaml.allow_unicode = True
        yaml.default_flow_style = False
        yaml.indent(mapping=2, sequence=4, offset=2)
        return yaml

except ImportError:
    import yaml as _pyyaml

    YAMLError = _pyyaml.YAMLError

    class YAML:  # type: ignore[no-redef]
        def __init__(self, typ: str = "safe", pure: bool = True):
            self.typ = typ
            self.pure = pure
            self.width = 80
            self.preserve_quotes = True
            self.allow_unicode = True
            self.default_flow_style = False

        def indent(self, mapping: int = 2, sequence: int = 4, offset: int = 2) -> None:
            pass

        def load(self, stream: Any) -> Any:
            return _pyyaml.safe_load(stream)

        def dump(self, data: Any, stream: Any) -> None:
            _pyyaml.safe_dump(data, stream, allow_unicode=self.allow_unicode, default_flow_style=self.default_flow_style)

    def safe_load(stream: str | bytes | IO[str] | IO[bytes]) -> Any:
        return _pyyaml.safe_load(stream)

    def safe_dump(
        data: Any,
        stream: IO[str] | None = None,
        *,
        default_flow_style: bool = False,
        sort_keys: bool = True,
        allow_unicode: bool = True,
        width: int = 80,
    ) -> str | None:
        return _pyyaml.safe_dump(
            data,
            stream=stream,
            default_flow_style=default_flow_style,
            sort_keys=sort_keys,
            allow_unicode=allow_unicode,
            width=width,
        )

    def roundtrip_yaml() -> YAML:
        return YAML(typ="rt")
