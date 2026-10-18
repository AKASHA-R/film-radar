#!/bin/sh
# 开一个带 failure 标签的 Issue；同标题的失败 Issue 还开着就不重复开。
# 用 REST 列表比对标题，不用搜索接口：搜索索引有延迟，连续两次失败仍会重复开（spec 2026-10-17 第 11 节）。
# 列不出来时照样开：宁可重复，也不能漏报。
# 用法：sh scripts/open_issue_once.sh 标题 正文文件。需要 GH_TOKEN、GITHUB_REPOSITORY、GITHUB_REPOSITORY_OWNER。
set -eu
title=$1
body=$2
if gh api --paginate "repos/$GITHUB_REPOSITORY/issues?labels=failure&state=open&per_page=100" --jq '.[].title' | grep -Fxq -- "$title"; then
  echo "同标题的失败 Issue 还开着，不重复开：$title"
  exit 0
fi
printf '\ncc @%s\n' "$GITHUB_REPOSITORY_OWNER" >> "$body"
gh issue create --repo "$GITHUB_REPOSITORY" --title "$title" --body-file "$body" --label failure
