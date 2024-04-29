#!/usr/bin/env python

from setuptools import find_packages, setup


def descriptions():
    with open("README.md") as fh:
        ret = fh.read()
        first = ret.split("\n", 1)[0].replace("#", "")
        return first, ret


def version():
    with open("octodns_infomaniak/__init__.py") as fh:
        for line in fh:
            if line.startswith("__version__"):
                return line.split('"')[1]
    return "unknown"


description, long_description = descriptions()

setup(
    author="Raphaël Hien",
    author_email="raphael.hien@infomaniak.com",
    description=description,
    install_requires=("octodns>=0.9.16", "requests>=2.27.0"),
    license="MIT",
    long_description=long_description,
    long_description_content_type="text/markdown",
    name="octodns-infomaniak",
    packages=find_packages(),
    python_requires=">=3.6",
    version=version(),
)
