from __future__ import print_function

import csv
import logging
import sys

from . import core

log = logging.getLogger(__name__)


def fs_commits_to_csv(stats_fs, fs_commits, csv_file, test_patterns=(), filters=None):
    csv_writer = csv.writer(csv_file)

    header_written = False

    old_commit = None
    stats_iter = core.generate_stats_for_stats_fs_commits(
        stats_fs, fs_commits, test_patterns=test_patterns, filters=filters)
    for stats_data in stats_iter:
        if old_commit != stats_data.commit:
            old_commit = stats_data.commit
        artifact = stats_data.filename.replace('/', '.')  # Use module name instead of file
        commit = stats_data.commit

        if not header_written:
            headers = tuple('.'.join(t) for t in stats_data.delta.index)
            csv_writer.writerow(
                ('Commit Time', 'Author', 'SHA', 'Artifact') +
                ('Total Lines', 'Inserted Lines', 'Deleted Lines') +
                ('Test Total Lines', 'Test Inserted Lines', 'Test Deleted Lines') +
                ('Non-test Total Lines', 'Non-test Inserted Lines',
                 'Non-test Deleted Lines') +
                tuple(h + '(delta)' for h in headers) +
                headers)
            header_written = True

        try:
            commit_datetime = commit.committed_datetime
        except ValueError as e:
            print('Got strange datetime at {}: {}'.format(commit.committed_date, e),
                  file=sys.stderr)
            print(commit, file=sys.stderr)
            continue

        csv_writer.writerow((commit_datetime,
                             commit.author.email,
                             commit.hexsha,
                             artifact) +
                            stats_data.lines +
                            stats_data.lines_test +
                            stats_data.lines_non_test +
                            tuple(stats_data.delta) +
                            tuple(stats_data.after))
