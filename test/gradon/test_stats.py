import os

import pytest  # noqa


from gradon import stats
from gradon import file_system


TEST_PATTERNS = (r'^tests?_.*.\py$', r'_tests?\.py$')


@pytest.fixture
def source_dir(tmpdir):
    return str(tmpdir.mkdir('my-source'))


FS_CLASSES = (file_system.FileSystem,
              file_system.GitCachedIndexStatsFileSystem,
              file_system.GitCachedStatsFileSystem,
              file_system.GitStatsFileSystem,
              file_system.GitIndexStatsFileSystem)


@pytest.fixture(params=FS_CLASSES)
def dest_fs(request, source_dir):
    dest_path = os.path.join(source_dir, '.gradon')
    return request.param(dest_path)


def test_update_stats(source_dir, dest_fs, cmpfile):
    """ Updates all the stats in a path """
    with open(os.path.join(source_dir, 'file.py'), 'w') as file:
        file.write('def foo(): pass\n')
    with open(os.path.join(source_dir, 'test_file.py'), 'w') as file:
        file.write('def test_foo(): pass\n')
        file.write('def test_foo2(): pass\n')

    stats.StatsUpdater(source_dir, dest_fs, test_patterns=TEST_PATTERNS, debug=True).update()
    if hasattr(dest_fs, '_sync_working_tree'):
        dest_fs._sync_working_tree('.')  # We need to commit or the files are not written to disk
    orig_dir = os.getcwd()

    dest_path = os.path.join(source_dir, '.gradon')
    os.chdir(dest_path)
    try:
        files = os.listdir('.')
        assert 'file.py.stats.yaml' in files
        assert 'test_file.py.stats.yaml' in files
        assert cmpfile('file.py.stats.yaml') == cmpfile('TOTAL_NON_TEST.stats.yaml')
        assert cmpfile('test_file.py.stats.yaml') == cmpfile('TOTAL_TEST.stats.yaml')
        assert cmpfile('TOTAL_NON_TEST.stats.yaml') == cmpfile('SUBTREE_TOTAL_NON_TEST.stats.yaml')
        assert cmpfile('TOTAL_TEST.stats.yaml') == cmpfile('SUBTREE_TOTAL_TEST.stats.yaml')
        assert cmpfile('TOTAL.stats.yaml') == cmpfile('SUBTREE_TOTAL.stats.yaml')
    finally:
        os.chdir(orig_dir)


def test_ignore_patterns(source_dir, dest_fs):
    """ Files whose names are in the ignored pattern list are not processed """
    with open(os.path.join(source_dir, 'file.py'), 'w') as file:
        file.write('def foo(): pass\n')
    with open(os.path.join(source_dir, 'ignore-file.py'), 'w') as file:
        file.write('def foo(): pass\n')

    stats.StatsUpdater(source_dir, dest_fs).update(ignore_patterns=('ignore-file',))

    files = os.listdir(os.path.join(source_dir, '.gradon'))
    assert 'file.py.stats.yaml' in files
    assert 'ignore-file.py.stats.yaml' not in files


def test_ignore_patterns_in_dir(source_dir, dest_fs):
    """ Files whose parent directories match the ignored pattern list are not processed """
    os.mkdir(os.path.join(source_dir, 'ignore-dir'))
    with open(os.path.join(source_dir, 'file.py'), 'w') as file:
        file.write('def foo(): pass\n')
    with open(os.path.join(source_dir, 'ignore-dir', 'file.py'), 'w') as file:
        file.write('def foo(): pass\n')

    stats.StatsUpdater(source_dir, dest_fs).update(ignore_patterns=('ignore-file',))

    files = os.listdir(os.path.join(source_dir, '.gradon'))
    assert 'file.py.stats.yaml' in files
    subdir_files = os.listdir(os.path.join(source_dir, '.gradon', 'ignore-dir'))
    assert 'ignore-file.py.stats.yaml' not in subdir_files
