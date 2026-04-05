.PHONY: cli clean realclean

UV=UV_ENV_FILE=.env uv

cli:
	${UV} run -m chat

clean:
	find . -name \*~ -o -name .\*~ | xargs rm -fr

realclean: clean
	find . -name \#\*\# -o -name .\#\* | xargs rm -fr
	find . -name __pycache__ | xargs rm -fr
	rm -fr uv.lock .venv
	tree -a -I .git
