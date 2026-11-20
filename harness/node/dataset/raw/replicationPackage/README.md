# An Empirical Study of Flaky Tests in JavaScript

In this paper, we study the flaky tests in JavaScript projects. The full replication package is available  [online](10.5281/zenodo.6673741). The repository contains the data and results from the paper "An Empirical Study of Flaky Tests in JavaScript", accepted at the 2022 38th IEEE International Conference on Software Maintenance and Evolution (ICSME 2022).

The replication package contains the following directories:

**1) ./Data**
* *JavaScript-flakyTests-dataset* contains 735 JavaScript flaky tests related commits extracted from the top 40 starred GitHub JavaScript projects. Each item includes the name of the repository, commit URL, and keyword that commits were found by it.
* *JavaScript-flakyTests-classification* contains 481 commits extracted from 18 JavaScript GitHub projects, with the following information:
    - *Repository name*.
    - *Commit URL*.
    - *Keyword*: the keyword that the commit was extracted.
    - *Cause of flakiness*.
    - *Response*: the developers' response regarding the flaky test.
    - *type of change*: it shows that developers fix or decrease the flakiness.
    - *change code*: it contains where the change is done to deal with flakiness, test code, or the code under test.

**2) ./Script**

includes the script used to search for flaky tests and the list of flaky test keywords.
* *keyword.txt* contains the list of flaky-related keywords.
* *get_commits.html* is used for working with the GitHub API and extracting commits that contain at least one keyword. GitHub API has a limit of 30 commits per request. For such repositories, we used manual paginations to extract all commits. In addition, we manually saved the extracted commits into a CSV file.
