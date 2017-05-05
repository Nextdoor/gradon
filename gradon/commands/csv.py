from __future__ import print_function

import logging

import click
import tqdm

from .. import core
from .. import fs_to_csv
from .. import tools

from . import shared

log = logging.getLogger(__name__)


@shared.git_log_args
@click.option('--output', '-o', type=click.File(mode='w'), default='-',
              help="Output destination (default is stdout)")
@click.option('--force', '-f', is_flag=True, help="Force refresh of cache")
@click.option('--filter', '-F', 'filters', multiple=True,
              help=('Report only for changes to files matching this artifact. '
                    'Default is to show just stats changes for entire tree'))
@click.pass_context
def command(ctx, rev_range=None, path=None, **options):
    stats_fs = ctx.obj['fs_class'](ctx.obj['cache_dir'], init=options['force'])

    total, source_commits = tools.tee_count(
        core.generate_shas_for_source_range(ctx.obj['repo'], rev_range))

    fs_commits = tqdm.tqdm(
        core.generate_stats_fs_commits_for_source_commits(
            stats_fs, ctx.obj['repo'], source_commits,
            paths=[path] if path else None, **ctx.obj['cache_kwargs']),
        unit='commit', total=total, unit_scale=True)

    filters = options['filters'] or ['^SUBTREE_TOTAL']
    log.info("Generating csv for range '{}'.".format(rev_range) or 'all')

    fs_to_csv.fs_commits_to_csv(
        stats_fs, fs_commits, options['output'],
        test_patterns=ctx.obj['test_patterns'], filters=filters)
