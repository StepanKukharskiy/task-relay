# Proposal reviewer experiment

Experimental review code, separate from production routing. `reviewer.py` constructs
amended-guide context and validates structured reviews. Citation checks do not prove
semantic support. A ready result is eligible for human review and carries
`approval: false`; it does not authorize a production change.

Run the synthetic boundary tests when changing this reviewer:

```sh
python3 -m unittest experiments.proposal_review.test_reviewer -v
```

Personal replay datasets, model responses and one-off run programs are not part of
this public example. Model evaluation requires explicitly supplied evidence and
separate authorization for provider calls.
