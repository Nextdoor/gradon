import os
import shutil
import tempfile

import git
import pytest  # noqa

from gradon import core
from gradon import file_system


def empty_tree_sha(git_repo):
    """ Magic SHA for an empty source repo, useful for initial diffs """
    # http://stackoverflow.com/questions/9765453/is-gits-semi-secret-empty-tree-object-reliable-and-why-is-there-not-a-symbolic  # noqa
    return git_repo.git.hash_object('/dev/null', t='tree')


@pytest.fixture
def _source_dir(tmpdir):
    return str(tmpdir.mkdir('my-source'))


@pytest.fixture
def source_repo(_source_dir):
    source_repo = git.Repo.init(_source_dir)
    source_repo.git.update_environment(
        GIT_AUTHOR_EMAIL='author@example.com',
        GIT_AUTHOR_NAME='Ms. Author',
        GIT_AUTHOR_DATE='2017-02-18 22:00:05-08:00',
        GIT_COMMITTER_EMAIL='committer@example.com',
        GIT_COMMITTER_NAME='Mr. Committer',
        GIT_COMMITTER_DATE='2017-02-19 22:00:05-08:00',
    )
    return source_repo


@pytest.fixture
def source_path(source_repo):
    return source_repo.working_tree_dir


@pytest.fixture
def write_source_file(source_path):
    def writer(file_path):
        return open(os.path.join(source_path, file_path), 'w')
    return writer


FS_CLASSES = (file_system.GitCachedIndexStatsFileSystem,
              file_system.GitCachedStatsFileSystem,
              file_system.GitStatsFileSystem,
              file_system.GitIndexStatsFileSystem)


@pytest.fixture(params=FS_CLASSES)
def dest_fs(request, _source_dir):
    dest_path = os.path.join(_source_dir, '.gradon')
    return request.param(dest_path)


def test_update_cache(source_repo, dest_fs, write_source_file):
    """ Creates a copy of the repo with all of the metadata """
    source_repo.git.commit(message='Initial commit', allow_empty=True)
    with write_source_file('file.py') as file:
        file.write('def foo(): pass\n')
    with write_source_file('test_file.py') as file:
        file.write('def foo(): pass\n')
    source_repo.git.add(all=True)
    source_repo.git.commit(message='My message')
    core.update_stats_fs_from_repo(dest_fs, source_repo)
    dest_repo = dest_fs.repo

    # Commit message was copied verbatim from source
    assert dest_repo.head.commit.message == (
        '{}\nMy message\n'.format(source_repo.head.commit.hexsha))
    assert dest_repo.head.commit.author == source_repo.head.commit.author
    # assert dest_repo.head.commit.authored_datetime == source_repo.head.commit.authored_datetime
    assert dest_repo.head.commit.committer == source_repo.head.commit.committer
    # assert dest_repo.head.commit.committed_datetime == source_repo.head.commit.committed_datetime

    # Stats were generated
    assert 'TOTAL.stats.yaml' in [
        d.b_path for d in dest_repo.head.commit.diff(empty_tree_sha(source_repo))]


def test_update_cache_with_ignored_files(source_repo, dest_fs, write_source_file):
    """ Ignores files matching provided patterns """
    source_repo.git.commit(message='Initial commit', allow_empty=True)
    with write_source_file('file.py') as file:
        file.write('def foo(): pass\n')
    with write_source_file('ignored-file.py') as file:
        file.write('def foo(): pass\n')
    source_repo.git.add(all=True)
    source_repo.git.commit(message='My message')

    core.update_stats_fs_from_repo(dest_fs, source_repo, exclude_patterns=('ignored-file',))

    new_files = [d.b_path for d in dest_fs.repo.head.commit.diff(empty_tree_sha(source_repo))]

    # Stats were generated
    assert 'file.py.stats.yaml' in new_files
    assert 'ignored-file.py.stats.yaml' not in new_files


def test_update_cache_with_existing_repo(source_repo, write_source_file):
    """ It starts again where we left off """
    try:
        dest_dir = tempfile.mkdtemp()
        git_env = dict(GIT_COMMITTER_EMAIL='noone@example.com', GIT_COMMITTER_NAME='No One',
                       GIT_AUTHOR_EMAIL='noone@example.com', GIT_AUTHOR_NAME='No One')
        dest_repo = git.Repo.init(dest_dir)
        dest_repo.git.update_environment(**git_env)

        # Synchronize source and destination repos
        source_repo.git.commit(message='Initial commit', allow_empty=True)
        dest_repo.git.commit(message='{}\nSome message'.format(source_repo.head.commit.hexsha),
                             allow_empty=True)

        # Now add a file to the destination
        with write_source_file('file.py') as file:
            file.write('def foo(): pass\n')
        source_repo.git.add(all=True)
        source_repo.git.commit(message='My message')

        dest_fs = file_system.GitCachedIndexStatsFileSystem(dest_dir)
        core.update_stats_fs_from_repo(dest_fs, source_repo, 'HEAD~1..HEAD')

        # Prior commit was not clobbered
        assert 'Some message' in dest_fs.repo.commit('HEAD~1').message

        # Stats were generated
        assert 'TOTAL.stats.yaml' in [d.b_path for d in dest_repo.head.commit.diff('HEAD~1')]
    finally:
        shutil.rmtree(dest_dir)


class TestGenerateStatsFSCommits(object):
    def test_incremental_from_initial(self, source_repo, dest_fs, write_source_file):
        """ In incremental mode, we create extra commits to catch-up on missing files  """
        with write_source_file('file.py') as file:
            file.write('def foo(): pass\n')
        source_repo.git.add(all=True)
        source_repo.git.commit(message='Initial commit', allow_empty=True, all=True)
        with write_source_file('test_file.py') as file:
            file.write('def foo(): pass\n')
        source_repo.git.add(all=True)
        source_repo.git.commit(message='My message', all=True)

        list(core.generate_stats_fs_commits_for_source_commits(
            dest_fs, source_repo, (c.hexsha for c in source_repo.iter_commits(reverse=True)),
            incremental=True))
        log = dest_fs.repo.git.log(format='%s', name_only=True)
        assert log == """\
b1a75c274d6458a54fb39b2071c4a6bc1c0f0b18 My message

LATEST_CHANGES.yaml
SUBTREE_TOTAL.stats.yaml
SUBTREE_TOTAL_NON_TEST.stats.yaml
TOTAL.stats.yaml
TOTAL_NON_TEST.stats.yaml
test_file.py.methods.yaml
test_file.py.stats.yaml
[ignore] b1a75c274d6458a54fb39b2071c4a6bc1c0f0b18
edbdba25b0177558f52891a8d95df75988e309ae Initial commit

LATEST_CHANGES.yaml
LATEST_CHANGES_TOTAL.yaml
SUBTREE_TOTAL.stats.yaml
SUBTREE_TOTAL_NON_TEST.stats.yaml
SUBTREE_TOTAL_TEST.stats.yaml
TOTAL.stats.yaml
TOTAL_NON_TEST.stats.yaml
TOTAL_TEST.stats.yaml
file.py.methods.yaml
file.py.stats.yaml
[ignore] edbdba25b0177558f52891a8d95df75988e309ae"""

    def test_incremental_partial(self, source_repo, dest_fs, write_source_file):
        """ It creates an intermediate commit with any files that will change """

        with write_source_file('test_file.py') as file:
            file.write('def foo(): pass\n')
        source_repo.git.add(all=True)
        source_repo.git.commit(message='Initial commit')
        source_repo.git.commit(message='Blank commit', allow_empty=True)
        with write_source_file('test_file.py') as file:
            file.write('def foo2(): pass\n')
        source_repo.git.commit(message='My message', all=True)

        list(core.generate_stats_fs_commits_for_source_commits(
            dest_fs, source_repo, (c.hexsha for c in source_repo.iter_commits('HEAD~1..HEAD',
                                                                              reverse=True)),
            incremental=True))
        log = dest_fs.repo.git.log(format='%s', name_only=True)
        assert log == """\
2d0f67270020d5bb55ead2237182f8f64943ad66 My message

LATEST_CHANGES.yaml
LATEST_CHANGES_TOTAL.yaml
test_file.py.methods.yaml
[ignore] 2d0f67270020d5bb55ead2237182f8f64943ad66

SUBTREE_TOTAL.stats.yaml
SUBTREE_TOTAL_NON_TEST.stats.yaml
SUBTREE_TOTAL_TEST.stats.yaml
TOTAL.stats.yaml
TOTAL_NON_TEST.stats.yaml
TOTAL_TEST.stats.yaml
test_file.py.methods.yaml
test_file.py.stats.yaml"""


def test_generate_stats_fs_commit_for_diff(source_repo, dest_fs, write_source_file):
    """ Generate fs commits for diff """
    source_repo.git.commit(message='Initial commit', allow_empty=True, all=True)
    with write_source_file('file.py') as file:
        file.write('def foo(): pass\n')
    source_repo.git.add(all=True)
    source_repo.git.commit(message='My message', all=True)
    with write_source_file('test_file.py') as file:
        file.write('def foo(): pass\n')
    source_repo.git.add(all=True)
    source_repo.git.commit(message='My last message', all=True)

    core.generate_stats_fs_commit_for_diff(dest_fs, source_repo, 'HEAD~2', 'HEAD')
    log = dest_fs.repo.git.log(format='%s', name_only=True)
    assert log == """\
HEAD~2..HEAD

LATEST_CHANGES.yaml
LATEST_CHANGES_TOTAL.yaml
SUBTREE_TOTAL.stats.yaml
SUBTREE_TOTAL_NON_TEST.stats.yaml
SUBTREE_TOTAL_TEST.stats.yaml
TOTAL.stats.yaml
TOTAL_NON_TEST.stats.yaml
TOTAL_TEST.stats.yaml
file.py.methods.yaml
file.py.stats.yaml
test_file.py.methods.yaml
test_file.py.stats.yaml
[ignore] 0e3b2ccbb150254c5b3a4319c1bafd280f6b27a4"""


def test_generate_stats_fs_commit_for_working_tree_plus_commit(source_repo, dest_fs,
                                                               write_source_file):
    """ Generate fs commits for working tree changes plus extra commit """
    source_repo.git.commit(message='Initial commit', allow_empty=True, all=True)
    with write_source_file('file.py') as file:
        file.write('def foo(): pass\n')
    source_repo.git.add(all=True)
    source_repo.git.commit(message='My message', all=True)
    with write_source_file('test_file.py') as file:
        file.write('def foo(): pass\n')
    source_repo.git.add(all=True)

    core.generate_stats_fs_commit_for_diff(dest_fs, source_repo, None, None)
    log = dest_fs.repo.git.log(format='%s', name_only=True)
    assert log == """\
HEAD..<working tree>

LATEST_CHANGES.yaml
LATEST_CHANGES_TOTAL.yaml
SUBTREE_TOTAL.stats.yaml
SUBTREE_TOTAL_NON_TEST.stats.yaml
SUBTREE_TOTAL_TEST.stats.yaml
TOTAL.stats.yaml
TOTAL_NON_TEST.stats.yaml
TOTAL_TEST.stats.yaml
test_file.py.methods.yaml
test_file.py.stats.yaml
[ignore] 0bb85185a126821a2bcb9e172b69f21fcbdedce1"""


def test_generate_stats_fs_commit_for_working_tree_diff(source_repo, dest_fs, write_source_file):
    """ Generate fs commits for working tree changes """
    source_repo.git.commit(message='Initial commit', allow_empty=True, all=True)
    with write_source_file('file.py') as file:
        file.write('def foo(): pass\n')
    source_repo.git.add(all=True)
    source_repo.git.commit(message='My message', all=True)
    with write_source_file('test_file.py') as file:
        file.write('def foo(): pass\n')
    source_repo.git.add(all=True)

    core.generate_stats_fs_commit_for_diff(dest_fs, source_repo, 'HEAD~1', None)
    log = dest_fs.repo.git.log(format='%s', name_only=True)
    assert log == """\
HEAD~1..<working tree>

LATEST_CHANGES.yaml
LATEST_CHANGES_TOTAL.yaml
SUBTREE_TOTAL.stats.yaml
SUBTREE_TOTAL_NON_TEST.stats.yaml
SUBTREE_TOTAL_TEST.stats.yaml
TOTAL.stats.yaml
TOTAL_NON_TEST.stats.yaml
TOTAL_TEST.stats.yaml
file.py.methods.yaml
file.py.stats.yaml
test_file.py.methods.yaml
test_file.py.stats.yaml
[ignore] 0e3b2ccbb150254c5b3a4319c1bafd280f6b27a4"""
