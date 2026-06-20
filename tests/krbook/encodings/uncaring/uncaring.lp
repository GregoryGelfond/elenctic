%% uncaring.lp -- Chapter 5, Section 5.1
%% Last Modified: 12/12/14
%% Example of a default and its exceptions.

person(john).  
person(sam).  
person(alice).

father(john,sam). 
mother(alice,sam). 

parent(X,Y) :- father(X,Y). 
parent(X,Y) :- mother(X,Y). 

child(X,Y) :-  parent(Y,X). 

% John doesn't care about his children:
-cares(john,X) :- child(X,john). 

% default rule -- Normally parents care about their children:
cares(X,Y) :- parent(X,Y),
              not ab(d_cares(X,Y)),
              not -cares(X,Y).
              
% Parents who are never seen at school cannot be assumed to
% care about their children; i.e., we cannot assume that 
% default d_cares(P,C) holds if P may have been always absent.
% (Note that does not mean that the parents don't care.
% It just means that we cannot assume that they do.)
ab(d_cares(P,C)) :- person(P), person(C),
                    not -absent(P).
                    
% Parents who are born in country u do not care about their kids.
-cares(P,X) :- parent(P,X),
               born_in(P,u).
               
% We cannot assume that P cares about C if he may have been
% born in country u.
ab(d_cares(P,X)) :- person(P), person(X),    
                    not -born_in(P,u). 
                  
person(pit).
person(kathy).
person(jim).
father(pit,jim).
mother(kathy,jim).
country(moldova).
country(u).
born_in(kathy,moldova).
%% A person can only be born in one country
-born_in(P,X) :- country(X),
                 born_in(P,Y),
                 X != Y.      
                 
-absent(pit).
-absent(kathy). 

%% --- elenctic @-contract (Gelfond-Kahl Sec 5.1; the program above is verbatim) ---
%% kathy (born moldova, known present) cares by the default; john explicitly does not; pit's birth
%% country is unknown, so we cannot assume he cares -- UNKNOWN, not a denial that he cares.
#show cares/2.
#show -cares/2.
% @expect sat
% @query yes { cares(kathy,jim) }
% @query no { cares(john,sam) }
% @query unknown { cares(pit,jim) }
% @note A default and its exceptions; pit is undetermined.
