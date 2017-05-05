import pytest  # noqa


from gradon import file_system


GIT_FS_CLASSES = (file_system.GitCachedIndexStatsFileSystem,
                  file_system.GitCachedStatsFileSystem,
                  file_system.GitStatsFileSystem,
                  file_system.GitIndexStatsFileSystem)

FS_CLASSES = GIT_FS_CLASSES + (file_system.FileSystem,)


@pytest.fixture
def fs_path(tmpdir):
    return str(tmpdir.mkdir('my-fs-path'))


class TestBasic(object):
    @pytest.fixture(params=FS_CLASSES)
    def fs(self, request, fs_path):
        return request.param(fs_path)

    def test_path(self, fs_path, fs):
        """ Path returned is the path passed to the constructor """
        assert fs.path == fs_path

    def test_add_and_read_file(self, tmpdir, fs):
        """ Reads return the file data passed during add_file """
        with fs.add_file('my-dir', 'my-file') as f:
            f.write('hello')
        assert fs.read('my-dir', 'my-file') == 'hello'


class TestGit(object):
    @pytest.fixture(params=GIT_FS_CLASSES)
    def fs(self, request, fs_path):
        return request.param(fs_path)

    def test_commit_and_head_message(self, fs):
        fs.commit('my commit message')
        assert fs.head_message.startswith('my commit message')
