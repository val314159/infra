
infra::	
	uv run --env-file $@/.env --project $@ $@

clean::
	find . -name \*~ -o -name .\*~ | xargs rm -fr
	@make -C infra $@

realclean:: clean
	@make -C infra $@
reset:
	rm -fr ~/.lab infra/convos/[0-9a-z]* ideas/cli/convos