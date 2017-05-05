""" Process all files in a tree with radon """

import os

from .. import stats
from .. import file_system

import click


@click.argument('paths', type=click.Path(exists=True, readable=True, resolve_path=True), nargs=-1,
                required=True)
@click.pass_context
def command(ctx, paths):
    for path in paths:
        if os.path.isdir(path):
            dest = path
            files = None
        else:
            dest = os.path.dirname(path)
            files = [os.path.basename(path)]
        dest_fs = file_system.StatsFileSystem(dest)
        updater = stats.StatsUpdater(path, dest_fs,
                                     debug=ctx.obj['debug'],
                                     test_patterns=ctx.obj['test_patterns'],
                                     parallel=ctx.obj['parallel'])
        updater.update(changed_files=files,
                       ignore_patterns=ctx.obj['exclude_pattern'])
