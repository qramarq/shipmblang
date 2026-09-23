# Contextual English vocabulary

The general parser now uses the built-in thesaurus's reviewed output verbs
(`show`, `print`, `display`, `present`) only in instruction position. It does
not normalize identifiers, quoted data, or the entire source through the IR
lexicon. In particular, arithmetic `add` never becomes `install`.

Supported examples, with model translation disabled:

* `Present the sum of 2 and 3.`
* `Could you add 2 and 3 together and tell me the result?`
* `Compute the aggregate of 2 and 3.`
* `I want you to calculate the total of 2 and 3.`
* `Pls show me the total of 2 and 3.`

Compute/calculate requests output the requested arithmetic expression. The
reviewed total/aggregate sense accepts two integers. Unsupported aggregation
senses require clarification. Existing implicit updates still require a unique
mutable integer target. Every clause and expression must be consumed, including
constraints; unsupported conditions or negation cannot produce a partial program.

The configured model receives a bounded selection of trusted contextual meanings
for words in the request, excluding quoted text. This is not arbitrary dictionary
retrieval: external thesauri and WordNet senses require review before executable
use. Model output still requires parsing and validation, which cannot prove
semantic fidelity. Broader prose and unresolved references may still require
model translation or clarification. No new runtime operations are introduced.

Grammar identity is `general-english-0.6`; vocabulary identity is
`contextual-general-2`, invalidating older interpretation/cache entries.
Regression tests cover conversational, abbreviated, formal, and technical forms,
ambiguity, constraints, quoted data, and relevant model vocabulary selection.
