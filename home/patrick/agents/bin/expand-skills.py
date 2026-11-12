#!/usr/bin/env python3
"""Expand shared Markdown includes into a deployable skill tree."""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path


INCLUDE_MARKER = re.compile(
    r'^[\t ]*<!-- @include (?P<path>[^<>]+) -->[\t ]*$'
)


def _relative_target(root: Path, raw_target: str, source: Path) -> Path:
    target_text = raw_target.strip()
    target_path = Path(target_text)
    if target_path.is_absolute():
        raise ValueError(f'{source}: include target must be relative: {target_text}')

    target = (root / target_path).resolve()
    try:
        target.relative_to(root)
    except ValueError as error:
        raise ValueError(
            f'{source}: include target escapes the skills root: {target_text}'
        ) from error

    if not target.is_file():
        raise ValueError(f'{source}: include target does not exist: {target_text}')
    return target


def _frontmatter_end(lines: list[str], source: Path) -> int | None:
    if not lines or lines[0].rstrip('\r\n') != '---':
        return None

    for index, line in enumerate(lines[1:], start=1):
        if line.rstrip('\r\n') == '---':
            return index
    raise ValueError(f'{source}: unterminated YAML frontmatter')


def expand_markdown(
    source: Path,
    root: Path,
    stack: tuple[Path, ...] = (),
) -> str:
    resolved_source = source.resolve()
    if resolved_source in stack:
        cycle = ' -> '.join(
            str(path.relative_to(root)) for path in (*stack, resolved_source)
        )
        raise ValueError(f'include cycle: {cycle}')

    text = resolved_source.read_text(encoding='utf-8')
    lines = text.splitlines(keepends=True)
    frontmatter_end = _frontmatter_end(lines, resolved_source)
    expanded: list[str] = []

    for index, line in enumerate(lines):
        marker = INCLUDE_MARKER.fullmatch(line.rstrip('\r\n'))
        if marker is None:
            expanded.append(line)
            continue

        if frontmatter_end is not None and index <= frontmatter_end:
            raise ValueError(
                f'{resolved_source}: include marker inside YAML frontmatter'
            )

        target = _relative_target(root, marker.group('path'), resolved_source)
        included = expand_markdown(target, root, (*stack, resolved_source))
        if line.endswith(('\n', '\r')) and included and not included.endswith('\n'):
            included += '\n'
        expanded.append(included)

    result = ''.join(expanded)
    if '<!-- @include ' in result:
        raise ValueError(f'{resolved_source}: unresolved or malformed include marker')
    return result


def expand_tree(source: Path, output: Path) -> None:
    source_root = source.resolve()
    output_root = output.resolve()
    try:
        output_root.relative_to(source_root)
    except ValueError:
        pass
    else:
        raise ValueError('output directory must not be inside the source tree')

    output_root.mkdir(parents=True, exist_ok=True)
    for path in sorted(source_root.rglob('*')):
        relative = path.relative_to(source_root)
        target = output_root / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix == '.md':
            target.write_text(
                expand_markdown(path, source_root),
                encoding='utf-8',
            )
            shutil.copymode(path, target)
        else:
            shutil.copy2(path, target)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    expand_tree(args.source, args.output)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
