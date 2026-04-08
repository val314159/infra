#!/bin/bash
set -ex
#docker build -t sandbox sandbox
docker run  -it --rm \
       -v$PWD:$PWD -w$PWD \
       --name sandbox sandbox
