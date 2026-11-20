*get_commits* script can be used for extracting the repositories and commits from GitHub by using Github API.
* Repository: pressing the Repositorty button shows the JavaScript repositories in GitHub, ordered by the most starred. 
* Commits: By putting the name of the repository in the box and selecting one of the keywords, then pressing the Commits button, commits are shown. These commits are from the inserted repository and contain a selected keyword.

GitHub API has a limit of 30 commits per request. For such repositories, we used manual paginations to extract all commits and saved the extracted commits into a CSV file.