from __future__ import print_function

import logging
import shutil
import tempfile

import click

from .. import core
from . import shared

log = logging.getLogger(__name__)


@click.argument('first', nargs=1, required=False, metavar='commit')
@click.argument('last', nargs=1, required=False, metavar='commit')
@click.option('--all', is_flag=True, help="Show all stats")
@click.option('--all-grades', is_flag=True, help="Only show grades affecting the score")
@click.option('--filter', '-F', 'filters', multiple=True,
              help=('Report only for changes to files matching this artifact. '
                    'Default is to show just stats changes for entire tree'))
@click.pass_context
@shared.page_output
def command(ctx, first=None, last=None, paths=None, **options):
    cache_path = tempfile.mkdtemp(prefix='gradon-tmp')
    source_repo = ctx.obj['repo']

    try:
        stats_fs = ctx.obj['fs_class'](cache_path)
        filters = {'^SUBTREE_TOTAL_TEST': 'TEST CODE', '^SUBTREE_TOTAL_NON_TEST': 'NON-TEST CODE'}

        fs_commit = core.generate_stats_fs_commit_for_diff(
            stats_fs, source_repo, first, last, paths=paths, **ctx.obj['cache_kwargs'])

        stats_iter = core.generate_stats_for_stats_fs_commits(
            stats_fs, [fs_commit], test_patterns=ctx.obj['test_patterns'],
            filters=options['filters'] or filters)

        shared.print_stats(stats_iter, source_repo, stats_fs, ctx.obj['cruft_scores'],
                           all=options['all'], name_map=filters, all_grades=options['all_grades'])
    finally:
        shutil.rmtree(cache_path)
