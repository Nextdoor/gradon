# Gradon = Git + Radon

Gradon is a tool for analyzing changes to a python code base using
[radon](https://github.com/rubik/radon).  It is modeled on git, and it tells you information about
how each commit in a git repo has changed your source code statistics and Cyclomatic Complexity
grades.

The Gradon command-line is much like git, supporting the following commands:

* `gradon log [<rev>]`: Shows the history of changes to your repo. 
* `gradon diff [<rev1>] [<rev2>]`: Compares two git revisions ()or current HEAD).
* `gradon csv`: Spits out raw csv
* `gradon stats <rev range>`: Show the starting and ending stats of a range
* `gradon blast`: Runs radon on a source tree, creating .yml files in-place.

Gradon also introduces a metric called a *Cruft Score*, which is:
 
  <num lines of As> * <score for As> ... <num lines of Fs> * <score for Fs>
  
By default, the score associated with A is 0, B is 1, C is 2, D is 4, E is 8 and F is 16.  The
theory behind this is that commits with non-positive cruft scores are improving the quality of the
code base.

## Running gradon

Clone the repo and run `python setup.py install`.  The run `gradon log` and see how your repo has
evolved.

For deeper analysis, the `gradon csv` command can be used to generate raw output per changed file
that can be sent to analysis scripts.  For example,

`gradon csv | sample/sum_deltas.py - SUBTREE_TOTAL`

will print the total changes to the stats in the repo by user, using the sample `sum_deltas.py`
script provided.  See below for more details about how to use `gradon csv`.

## How it works

Gradon generates metadata "stats" files for individual python files and aggreagates for directories.
Specifically,

1. For each python file `<my_file_name>.py`, a file called `<my_file_name>.stats.yaml` is created.

2. In each directory that contains python files, a `TOTAL.stats.yaml` file is created. 

3. In each directory that contains python files, separate `TOTAL_TEST.stats.yaml` and
`TOTAL_NON_TEST.stats.yaml` files are created.  These contain aggregate stats for only those files 
deemed to be tests, based on whether their names begin or end with `test(s)`.

4. In each directory, aggregates are created for the current directory and all subdirectories. These
aggregates have the names `SUBTREE_TOTAL_TEST.stats.yaml`, `SUBTREE_TOTAL_NON_TEST.stats.yaml` and
`SUBTREE_TOTAL.stats.yaml`.

For every commit in the source repo, `gradon` generates a commit in the destination repo that 
contains updated versions of these files at each commit.  Each commit has the same author and
committer as well as matching dates to the corresponding commits in the new repo.

Finally, for convenience, `gradon` also creates two files at the top of the tree: 

1. `LATEST_CHANGES.yaml` - the names of all files that changed, with the count of lines changed 
per file (including separate insertion and deletion counts) according to git.
2.`LATEST_CHANGES_TOTAL.yaml` -- the totals of the stats in `LATEST_CHANGES.yaml`

This information could be gleaned from the original repo, but it makes accessing the original repo
unnecessary.

Using a git repo as the database for *gradon* allows us to trivially identify deltas between commits
in addition to trivially storing the metadata (author, commit time, etc) from the original repo with
each commit.  Gradon can restart where it left off for an existing repo, allowing it to integrate
new  commits into a gradon repo efficiently.

## Statistics

The statistics are, for the most part, the values and sums of values calculated by radon.  Below is a 
sample statistics file:

```
complexity:
  class: 0
  func: 111
  total: 118
grades:
  A: 35
  B: 103
  C: 133
  D: 0
  E: 0
  F: 0
halstead:
  N1: 44
  N2: 82
  bugs: 0.21508743550534284
  calculated_length: 405.5183230692545
  difficulty: 8.712509712509712
  effort: 2471.849420430037
  h1: 16
  h2: 75
  length: 126
  time: 137.32496780166872
  vocabulary: 91
  volume: 645.2623065160285
stats:
  blank: 103
  comments: 16
  lloc: 331
  loc: 393
  multi: 21
  single_comments: 17
  sloc: 431
```

The dictionaries `complexity`, `halstead` and `stats` are pulled straight from radon.  The `grades`
dictionary represents the number of logical lines of code inside methods and functions that have
been ranked by radon's [cyclomatic complexity scoring
system](http://radon.readthedocs.io/en/latest/commandline.html#the-cc-command).

## How to use these stats

The `gradon csv` command produces a csv file for use in
tools such as Tableau or a python pandas script.  It generates a row for each changed stats file and
aggregate stats file in the repo at each commit.  Each row contains the commit author, the commit
date, the commit SHA and the name of the changed file, as well as the current and delta values for
each stat. It also contains the total number of lines changed, inserted and deleted (according to
git), as well as separate values for these counts for files that represents tests and those that do
not.

The pandas script at `sample/dum_deltas.py` is an example of a script that can use this data to
generate a report per author of their net effect on each statistic over the entire codebase.
