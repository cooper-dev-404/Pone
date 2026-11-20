"""Run the workbench’s pinned PhotoCraft CLI without a shell."""
import json
from pathlib import Path
import subprocess


VERSION = '0.23.1'


class Editor:
    def __init__(self, binary: Path):
        self.binary = binary
        self.version = self.call('--version').strip()
        if f' {VERSION} ' not in self.version:
            raise ValueError(f'Expected PhotoCraft {VERSION}, got {self.version}')

    def call(self, *arguments):
        proc = subprocess.run(
            [str(self.binary), *map(str, arguments)],
            capture_output=True, text=True,
        )
        if proc.returncode:
            message = proc.stderr.strip() or proc.stdout.strip()
            raise RuntimeError(message or f"PhotoCraft exited with status {proc.returncode}")
        return proc.stdout

    def info(self, document):
        return json.loads(self.call('info', document, '--detail'))

    def edit(self, document, commands, output=None, options=()):
        args = ['run', str(document)]
        for name, params in commands:
            args.extend(['--cmd', name, '--params', json.dumps(params, ensure_ascii=False)])
        if output:
            args.extend(['--out', str(output)])
        args.extend(options)
        results = [json.loads(line) for line in self.call(*args).splitlines() if line.strip()]
        for result in results:
            if 'error' in result:
                raise RuntimeError(result)
        return results

    def pixel(self, document, x, y):
        [result] = self.edit(document, [('document.pixel', {'x': x, 'y': y})])
        return result['result']

