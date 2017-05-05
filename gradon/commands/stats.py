from __future__ import print_function

import click
import tqdm

from .. import core
from . import shared
from .. import tools


@shared.git_log_args
@click.option('--all', is_flag=True, help="Show all stats")
@click.option('--force', '-f', is_flag=True, help="Force refresh of cache")
@click.option('--filter', '-F', 'filters', multiple=True,
              default=['^SUBTREE_TOTAL'],
              help=('Report only for changes to files matching this artifact. '
                    'Default is to show just stats changes for entire tree'))
@click.pass_context
def command(ctx, rev_range=None, **options):
    source_repo = ctx.obj['repo']
    stats_fs = ctx.obj['fs_class'](ctx.obj['default_cache_path'], init=options['force'])

    total, source_shas = tools.tee_count(
        core.generate_shas_for_source_range(source_repo, rev_range))

    fs_commits = core.generate_stats_fs_commits_for_source_commits(
        stats_fs, source_repo, source_shas)

    stats_iter = core.generate_stats_for_stats_fs_commits(
        stats_fs, fs_commits, test_patterns=ctx.obj['test_patterns'], filters=options['filters'])

    print('Stats after first commit:')
    stats = next(stats_iter)
    print(stats.after)

    old_commit = stats.commit
    progress = tqdm.tqdm(unit='commit', unit_scale=True, total=total, leave=False)
    for stats in stats_iter:
        if stats.commit != old_commit:
            progress.update()
            old_commit = stats.commit

    print('Stats after last commit:')
    print(stats.after)
