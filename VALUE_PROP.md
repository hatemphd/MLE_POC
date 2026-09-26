# TrustGate value proposition, for the general reader

A plain-language explanation of what this project does, how it uses the
data, and why it complements the AI systems that write code fixes. Written to
be read aloud or turned into a five-minute talk.

## The 60-second version

AI coding agents can now read a bug report and write a fix. Lots of them.
Someone still has to decide which fixes to trust, and running every test
suite or asking a human every time is slow and expensive.

TrustGate is the quick first look. It reads a proposed fix and says "this one
probably works", "this one probably does not", or "a person should look at
this". To learn how, we borrowed thousands of fixes that ten different AI
agents wrote for the same 500 real bugs, along with the official grade each
fix received when its tests were run. We taught a small model to predict the
grade from the fix alone. The single best clue turned out to be whether a fix
agrees with what the other agents did. The model is good enough to sort a
review queue today and not yet good enough to merge code on its own.

## The classroom analogy

Picture a class of ten students who all sit the same exam of 500 questions.
Each question is a real bug from a real open-source project, and each answer
is a code change meant to fix it. The teacher has the answer key: for every
question there is a set of tests, and an answer is correct if the tests pass.
The teacher has already marked every paper.

Now imagine a teaching assistant who is handed a fresh answer sheet with no
marks on it and asked: without running the tests, how likely is this answer
to be correct?

That teaching assistant is TrustGate.

The assistant cannot check the answer directly, so they look at how it is
written. Is it a reasonable length, or suspiciously huge? Is the code well
formed, or does it have obvious mistakes a linter would flag? And, most
usefully: do the other nine students' answers to this question look the same?
If seven of ten students changed the same lines in the same file, that answer
is probably right. If one student's answer looks like nobody else's, be
careful.

## How we use the data, step by step

1. **We did not write any fixes and we did not grade any.** The SWE-bench
   project publishes the exam (the 500 bugs and their tests) and the
   leaderboard publishes the marked papers: every fix each AI agent
   submitted, plus the pass or fail result from the official grader. We
   downloaded ten agents' papers. That gave us about 4,900 fixes, each with a
   known grade.

2. **We turned each fix into a row of numbers.** How many lines it adds and
   removes, how many files it touches, whether it parses and compiles, how
   many warnings a linter raises, how similar it is to the other fixes for the
   same bug, and how much its words overlap with the bug report. Sixteen
   numbers per fix. Never the tests, never the real answer, never which agent
   wrote it.

3. **We hid some bugs from the model.** The model learns from fixes to 300
   bugs, tunes its settings on 100 more, and is tested on a final 100 it has
   never seen. All ten fixes for a bug stay together on one side of the line,
   so the model can never peek at a sibling answer during training and meet
   its twin in the exam.

4. **We trained two kinds of model.** A straight-line model, which is easy to
   explain, and a tree model that learns rules like "if agreement is high and
   the fix touches one file, it probably works". The tree model wins.

5. **We turned the score into a decision.** The model outputs a probability.
   Above a high cut-off we approve automatically; below a low cut-off we
   reject automatically; in between a human reviews. The cut-offs are chosen
   on the tuning bugs and frozen before we look at the final test bugs.

6. **We measured honestly.** On the 100 unseen bugs, the model ranks a good
   fix above a bad one 73 times in 100. Of the fixes it approved on its own,
   76 in 100 really worked. Of those it rejected, 93 in 100 really were
   broken. It sent 80 in 100 to a human.

## Why TrustGate complements the patch writers

The agents on the SWE-bench leaderboard are authors. TrustGate is an editor.
An author's job is to produce something; an editor's job is to decide what
gets published. Neither replaces the other.

- **Writers produce, TrustGate filters.** As agents get cheaper it becomes
  easy to generate five or ten candidate fixes for one bug. Somebody has to
  pick. TrustGate can rank them in milliseconds without running a single
  test.
- **TrustGate learns from the writers' collective behaviour.** Its best clue,
  agreement between independent attempts, only exists because several
  writers tackled the same bug. More writers make the judge better.
- **The writers' results are TrustGate's training data.** Every fix a
  leaderboard system submits, with its official grade, is another labelled
  example for us. Their progress feeds our model for free.
- **The leaderboard already shows the payoff.** Two teams appear twice on the
  Verified leaderboard, once submitting their agent's first answer and once
  letting a judge pick the best of several. One rises from 38 to 47 percent,
  the other from 42 to 59 percent. That gap is the value of a good editor. Our
  editor is cheap and explainable; theirs are expensive language models. The
  two can be stacked: ours first, theirs only on the uncertain middle.

## The airport-security analogy for the three-way gate

Most travellers walk through the scanner and go straight to the gate: that is
auto-approve. A few set off every alarm and are turned back: auto-reject. The
rest get a bag search by a person: human review. The security system is not
trying to make the final call on everyone. It is trying to be very sure about
the people it waves through, very sure about the people it turns back, and
honest about the rest.

TrustGate today is good at turning back: 93 of 100 rejections are right. It
is not yet sure enough to wave people through: 24 of 100 approvals would let
a broken fix into the codebase. So we use it to decide who gets searched
first, and we keep a person at the gate.

## Three things a reader should take away

1. **Where labels come from matters more than the model.** Our labels are the
   result of actually running the tests, produced by the benchmark's own
   grader, not by us. That is why the numbers can be trusted.
2. **Never let the model see the answer, or anything that leaks it.** No
   tests, no reference fix, no author identity. And split by bug, not by row.
3. **Measure the decision you will actually make.** Accuracy is a poor guide
   here. What matters is: of the fixes we approve unattended, how many really
   work, and how many fixes we can decide at all.

## One-paragraph pitch for a slide

AI agents now write code fixes faster than humans can review them. TrustGate
is a small, fast model that reads a proposed fix and estimates the chance it
works, before any tests run, so a team can approve the obvious, reject the
hopeless, and spend human attention on the rest. We trained it on thousands
of real fixes from ten different AI agents, graded by the official SWE-bench
tests, and found that the strongest signal is whether independent agents
agree. It already sorts a review queue well; making it safe to merge code on
its own is the next problem.

## Where to go next

- [GETTING_STARTED.md](GETTING_STARTED.md) to run it yourself
- [METRICS.md](METRICS.md) for every number above, with formulas and figures
- [SWEBench_TrustGate.md](SWEBench_TrustGate.md) for how our work relates to the leaderboard systems
