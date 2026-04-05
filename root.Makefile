
cli::	
	@make -C infra $@

clean::
	find . -name \*~ -o -name .\*~ | xargs rm -fr
	@make -C infra $@

realclean:: clean
	@make -C infra $@
