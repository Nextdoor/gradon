import pandas as pd
from pandas.util import testing as pdt

import pytest  # noqa


from gradon import file_system
from gradon import stats_fs_adapter


@pytest.fixture
def dest_fs(tmpdir):
    return file_system.GitCachedIndexStatsFileSystem(str(tmpdir.mkdtemp()))


@pytest.fixture
def adapter(dest_fs):
    return stats_fs_adapter.GitCachedStatsFSAdapter(dest_fs)


def test_get_and_set(adapter):
    series = pd.Series({('a', 'x'): 1,
                        ('a', 'y'): 2,
                        ('b', 'z'): 3})
    adapter.set('my-dir/my-series', series)
    pdt.assert_series_equal(adapter.get('my-dir/my-series'), series)
