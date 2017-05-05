import logging

import click
import git
import os
import sys

from . import blast
from . import csv
from . import diff
from . import log
from . import stats

from .. import file_system

COMMANDS = dict(
    blast=blast.command,
    csv=csv.command,
    diff=diff.command,
    log=log.command,
    stats=stats.command,
)


def find_repo(ctx, param, path):
    if path is None:
        try:
            path = git.Repo('.', search_parent_directories=True)
        except git.CommandError:
            raise click.BadParameter('Could not find repo')
    return path


def create_cruft_score_map(ctx, param, value):
    return {grade: float(score) for grade, score in zip('ABCDEF', value.split(','))}


@click.group()
@click.option('-C', 'repo', help="Git repo location", metavar='<path-to-repo>',
              type=click.Path(file_okay=False, resolve_path=True), callback=find_repo)
@click.option('--debug', '-d', help="Print debug output", count=True)
@click.option('--parallel', '-j', is_flag=True, help="Run radon in parallel")
@click.option('--index', '-i', 'index_only', is_flag=True, help="Use git-index file system",
              default=True)
@click.option('--cache', '-c', 'cache_dir', type=click.Path(),
              help="gradon git cache repo (default is <repo>/.gradon)")
@click.option('--cruft-scores', default='0,1,2,4,8,16', metavar='A,B,C,D,E,F',
              callback=create_cruft_score_map,
              help="Comma-separated score values for each grade")
@click.option('--test-pattern', '-t', 'test_patterns', metavar='REGEX', multiple=True,
              help="Regex to identify tests",
              default=[r'^tests?_.*.\py$', r'_tests?\.py$'])
@click.option('--exclude-pattern', '-x', 'exclude_patterns', metavar='REGEX', multiple=True,
              help="Ignore files whose full path matches these regexps")
@click.pass_context
def gradon(ctx, **options):
    if options.pop('index_only'):
        fs_class = file_system.GitCachedIndexStatsFileSystem
    else:
        fs_class = file_system.GitCachedStatsFileSystem

    options['fs_class'] = fs_class
    options['default_cache_path'] = os.path.join(options['repo'].working_tree_dir, '.gradon')
    options['cache_dir'] = options['cache_dir'] or options['default_cache_path']
    options['cache_kwargs'] = dict(test_patterns=options['test_patterns'],
                                   exclude_patterns=options['exclude_patterns'],
                                   parallel=options['parallel'],
                                   debug=options['debug'])

    ctx.obj.update(options)
    logging.basicConfig(stream=sys.stderr,
                        level=(logging.DEBUG if options['debug'] > 1 else
                               logging.INFO if options['debug'] == 1 else
                               logging.WARNING))

for name, cmd in COMMANDS.items():
    gradon.command(name=name)(cmd)
