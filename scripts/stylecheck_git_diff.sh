#!/usr/bin/env bash
###############################################################################
# git diff style checker
# ----------------------
# This script runs a style check within our Drone setup, or within the
# `drone exec` runner.
#
# Since the codebase has a substantial body of non-conformant code, style
# checks are only ran on the diffs (compared to master). As a consequence of
# this, style checks also only run on non-master branches.
###############################################################################

# Don't let the pipe to pep8 eat exit(1) thrown by git diff.
set -o pipefail

if [[ ${CI_BRANCH} = "master" ]]; then
    echo "Skipping style checks on commit(s) to the master branch."
    exit 0
fi

if [[ ${CI_REPO:=} = "" ]]; then
    # This assumed to be `drone exec`.
    echo "Running style checks on staged local changes..."
    git diff --unified=0 --cached | pep8 --diff
else
    echo "Running style checks within Drone..."
    # Get repo name without org and slash so we place nicely with forks.
    repo_name=${CI_REPO#*/}
    git remote add upstream "https://github.com/reddit/${repo_name}.git"
    git fetch --no-tags --depth=10 upstream master
    # Find the point at which the branch and the canonical repo diverged.
    # Catches cases where the submitter hasn't rebased recently.
    git diff --unified=0 --cached $(git merge-base HEAD upstream/master) | pep8 --diff
fi
error_encountered=$?

if [[ ${error_encountered} = 1 ]]; then
    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    echo "pep8 issues found. reddit follows pep8: https://github.com/reddit/styleguide"
    echo "              Please commit a fix or ignore inline with: noqa"
    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    exit 1
fi

echo "Style checks passed. Good jerb!"
