#!/bin/sh

# clean up older versions
rm -rf dist
rm -rf build
rm -rf *.egg-info
#
# Generate pypi wheels universal package and upload
# in case anything goes wrong use:
# $twine check dist/*
python setup.py sdist bdist_wheel
twine upload --verbose dist/*
