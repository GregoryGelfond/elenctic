%% tweety.lp -- Chapter 5, Section 5.4.3
%% Last Modified: 2/6/14
%% Inheritance using the specificity principle -- more-specific 
%%   information overrides less specific information.
%% This program creates a hierarchical structure based on one implied by
%% the following statements. 
%%   Eagles and penguins are types of birds.
%%   Birds are a type of animal.
%%   Sam is an eagle, and Tweety is a penguin.
%%   Tabby is a cat.

class(animal).
class(bird).
class(eagle).
class(penguin).
class(cat).

object(sam).
object(tweety).
object(tabby).

is_subclass(eagle,bird).
is_subclass(penguin,bird).
is_subclass(bird,animal).
is_subclass(cat,animal).

%% Class C1 is a subclass of class C2 if C1 is a subclass of C2 or
%% if C1 is a subclass of C3 which is a subclass of C2.
subclass(C1,C2) :- is_subclass(C1,C2).
subclass(C1,C2) :- is_subclass(C1,C3),
                   subclass(C3,C2).

is_a(sam,eagle).
is_a(tweety,penguin).
is_a(tabby,cat).

%% Object X is a member of class C if X is a C or if X is a C0
%% and C0 is a subclass of C.
member(X,C) :- is_a(X,C).
member(X,C) :- is_a(X,C0),
               subclass(C0,C).
 
%% Sibling classes are disjoint unless we are specifically told otherwise.
siblings(C1,C2) :- is_subclass(C1,C),
                   is_subclass(C2,C),
                   C1 != C2.
-member(X,C2) :- member(X,C1),
                 siblings(C1,C2),
                 C1 != C2,
                 not member(X,C2). 
                 
%% default d1: Animals normally do not fly.
-fly(X) :- member(X,animal),
           not ab(d1(X)),
           not fly(X).
           
%% default d2: Birds normally fly.
fly(X) :- member(X,bird),
          not ab(d2(X)),
          not -fly(X).
          
%% default d3: Penguins normally do not fly.
-fly(X) :- member(X,penguin),
           not ab(d3(X)),
           not fly(X).

%% X is abnormal with respect to d2 if X might be a penguin.
ab(d2(X)) :- object(X), not -member(X,penguin).      

%% X is abnormal with respect to d1 if X might be a bird.
ab(d1(X)) :- object(X), not -member(X,bird).            
%% --- elenctic @-contract (Gelfond-Kahl Sec 5.4.3; the program above is verbatim) ---
%% sam the eagle flies (default d2); tweety the penguin does not (specificity: d3 over d2);
%% tabby the cat does not (default d1). The conjunctive @query is false in the model (both -fly).
#show fly/1.
#show -fly/1.
% @expect sat
% @query yes { fly(sam) }
% @query no { fly(tweety) }
% @query no { fly(tabby) }
% @query no { fly(tweety), fly(tabby) }
% @note Inheritance with the specificity principle.
