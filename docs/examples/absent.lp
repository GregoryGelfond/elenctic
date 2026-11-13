% Ann is an admin, and admins may use the database; we expect her to have access.
role(ann,admin). role(bob,staff).
permits(admin,db). permits(staff,wiki).
flagged(ann).
suspended(U) :- flagged(U), not cleared(U).
access(U,R) :- role(U,X), permits(X,R), not suspended(U).
#show access/2.
% @expect sat
% @cautious { access(ann,db) }
