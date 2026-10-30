% Theory atoms need a theory solver; clingo would ground them and ignore their constraints.
#theory t { c { }; &k/0 : c, any }.
{ p }. &k { 1 }.
% @expect sat
