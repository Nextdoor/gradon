from __future__ import print_function

import logging
import shutil
import tempfile

import click

from .. import core
from . import shared

log = logging.getLogger(__name__)


@shared.git_log_args
@click.option('--all', is_flag=True, help="Show all stats")
@click.option('--all-grades', is_flag=True, help="Only show grades affecting the score")
@click.option('--force', '-f', is_flag=True, help="Force refresh of cache")
@click.option('--reverse', '-r', is_flag=True, help="Reverse order (default is newest first)")
@click.option('--filter', '-F', 'filters', multiple=True,
              help=('Report only for changes to files matching this artifact. '
                    'Default is to show just stats changes for entire tree'))
@click.pass_context
@shared.page_output
def command(ctx, rev_range=None, paths=(), **options):
    cache_path = tempfile.mkdtemp(prefix='gradon-tmp')

    source_repo = ctx.obj['repo']
    try:
        stats_fs = ctx.obj['fs_class'](cache_path,
                                       init=options['force'] or not ctx.obj['cache_dir'])
        filters = {'^SUBTREE_TOTAL_TEST': 'TEST CODE', '^SUBTREE_TOTAL_NON_TEST': 'NON-TEST CODE'}

        reverse = (not options['reverse'])  # reversed by default

        source_commits = core.generate_shas_for_source_range(source_repo, rev_range,
                                                             reverse=reverse)

        fs_commits = core.generate_stats_fs_commits_for_source_commits(
            stats_fs, source_repo, source_commits, reversed=reverse,
            incremental=True, **ctx.obj['cache_kwargs'])

        stats_iter = core.generate_stats_for_stats_fs_commits(
            stats_fs, fs_commits, test_patterns=ctx.obj['test_patterns'],
            filters=options['filters'] or filters)

        shared.print_stats(stats_iter, source_repo, stats_fs, ctx.obj['cruft_scores'],
                           all=options['all'], name_map=filters, print_original_commit=True,
                           all_grades=options['all_grades'])
    finally:
        shutil.rmtree(cache_path)
