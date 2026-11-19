#!/bin/bash
# setup.sh <name> <url> <sha> : clone at sha
set -e
S=/tmp/claude-0/-home-user-fenvix-engine-cli/32af3bec-41bb-5cba-9492-aa37cddbeea0/scratchpad/xd
name=$1; url=$2; sha=$3
d=$S/repos/$name
if [ ! -d $d/.git ]; then
  git init -q $d && cd $d && git remote add origin $url
  git fetch -q --depth 1 origin $sha || { full=$(git ls-remote origin | awk '{print $1}' | grep "^$sha" | head -1); git fetch -q --depth 50 origin; }
  git checkout -q FETCH_HEAD
fi
cd $d; git log --oneline -1
