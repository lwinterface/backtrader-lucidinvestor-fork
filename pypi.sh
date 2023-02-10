#!/bin/bash

py_cmd="python"
if ! hash python; then
    py_cmd="python3"
fi

if ! hash twine; then
    echo "Twine is not present and must be installed. Installing Twine with sudo apt install"
    sudo apt install twine
fi

# clean up older versions
$py_cmd setup.py clean --all
rm -rf dist
rm -rf build
rm -rf *.egg-info
#
# Generate pypi wheels universal package and upload
# in case anything goes wrong use:
# $twine check dist/*
$py_cmd setup.py sdist bdist_wheel
twine upload --config-file ../env_var/secret.pypirc --verbose dist/*
