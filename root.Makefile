
infra::	
	uv run --env-file $@/.env --project $@ $@

clean::
	find . -name \*~ -o -name .\*~ | xargs rm -fr
	@make -C infra $@

realclean:: clean
	@make -C infra $@

reset::
	rm -fr infra/convos/[0-9a0z]*
	rm -fr */*/convo
	rm -fr ~/.lab
	@make -C infra realclean

