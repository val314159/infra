
infra::	
	uv run --env-file $@/.env --project $@ $@

clean::
	find . -name \*~ -o -name .\*~ | xargs rm -fr
	@make -C infra $@

realclean:: clean
	@make -C infra $@
