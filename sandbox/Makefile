.PHONY: all

all::
	docker build -t sandbox .
	docker run  -it --rm \
	       -v`pwd`:`pwd` -w`pwd` \
	       --name sandbox sandbox
