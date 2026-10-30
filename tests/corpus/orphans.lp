% orphans.lp -- Chapter 4, Section 4.1.2
% Last Modified: 1/29/14
% Defining Orphans

person(mary).
person(bob).
person(mike).
person(rich).
person(kathy).
person(patty).

child(mary).        
child(bob).   

father(mike,mary).   
father(rich,bob). 
mother(kathy,mary).  
mother(patty,bob). 

dead(rich).       
dead(patty). 

%% CWA's for child, father, mother, and dead:

-child(X) :- person(X),                       
             not child(X).
-father(F,C) :- person(F), 
                child(C), 
                not father(F,C).
-mother(M,C) :- person(M),
                child(C),
                not mother(M,C).
-dead(X) :- person(X),
            not dead(X).
            
%% P's parents are dead if both the father and the mother of P are dead:
parents_dead(P) :- father(F,P),
                   mother(M,P),
                   dead(F),
                   dead(M).

%% P is considered an orphan if P is considered a child and 
%% both parents are dead:
orphan(P) :- child(P),
             parents_dead(P).
             
%% CWA for orphan:
-orphan(X) :- person(X), 
              not orphan(X). 
                          
            

%% --- elenctic @-contract (Gelfond-Kahl Sec 4.1; the program above is verbatim) ---
%% bob's parents are both dead and bob is a child -> orphan; mary's father mike is alive -> not.
%% CWA on orphan gives a definite yes/no for every person.
#show orphan/1.
#show -orphan/1.
#show child/1.
#show -child/1.
% @expect sat
% @query yes { orphan(bob) }
% @query no { orphan(mary) }
% @query yes { child(bob), orphan(bob) }
% @note Defining Orphans -- conjunctive @query over two cautiously-entailed literals.
