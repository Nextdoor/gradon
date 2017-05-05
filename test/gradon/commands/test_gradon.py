from click.testing import CliRunner

from gradon.commands import gradon

import pytest  # noqa


def test_gradon_help():
    runner = CliRunner()
    result = runner.invoke(gradon.gradon, ['--help'])
    assert result.exit_code == 0
