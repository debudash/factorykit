Review pull request #$pr_number "$pr_title" as FactoryKit's independent reviewer. This is round $round.

- Reviewed commit (your working directory): $head_sha
- Merge-base with $base_branch: $merge_base. Review the changes since this commit.
- Ticket: $ticket. Spec: $spec. Docs PR: $docs_pr. LLD: $lld
  Read issues with the information below; you have no network access to GitHub.

$round_note

## Ticket and spec text
$issue_text

## Changed files
$diff_stat

## Diff
```diff
$diff
```
$previous
