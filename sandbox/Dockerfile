FROM alpine:3.23
RUN apk add git
RUN apk add py3-pip
RUN pip install --break-system-packages \
    docopt-ng pyaml
RUN pip install --break-system-packages \
    prompt-toolkit openai
ENV PAGER=cat
