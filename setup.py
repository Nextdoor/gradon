import sys

from setuptools import setup, find_packages

install_requires = ()

if sys.version_info < (3, 2):
    install_requires += ('contextlib2',)

setup(
    name='gradon',
    description='Nextdoor Gradon (Git + Radon == Gradon)',
    author='Andrew S. Brown',
    author_email='eng@nextdoor.com',
    packages=find_packages(exclude=['ez_setup']),
    scripts=['bin/gradon'],
    install_requires=install_requires + (
        'future>=0.15.2',
        'gitpython',
        'click>=6.7',
        'pandas',
        'pyyaml',
        'radon',
        'scandir',
        'tqdm',
    ),
    tests_require=[
    ],
    url='https://github.com/Nextdoor/gradon'
)
