#!/bin/sh
# 开一个带 failure 标签的 Issue。同标题的失败 Issue 还开着时，按第 3 个参数分两种做法：
# - 默认：把这次的正文（带 cc）追加成那个 Issue 的评论，不另开。失败 Issue 没有程序去关，
#   只「不重复开」的话，一个没人关的旧失败 Issue 会让之后同标题的失败全部悄无声息，
#   包括 spec 2026-10-17 第 15 节靠失败 Issue 送达的「改写失败、别撤销勾」提醒。评论会通知人。
# - skip-if-open：什么都不做。只给「Issue 无法解析」提醒用：那种提醒内容不变，而任何 Issue 被编辑都会跑一轮同步，
#   每轮都评论会刷屏。
# 用 REST 列表比对标题，不用搜索接口：搜索索引有延迟，连续两次失败仍会重复开（spec 2026-10-17 第 11 节）。
# 列不出来、或评论不上时照样开新的：宁可重复，也不能漏报。
# 用法：sh scripts/open_issue_once.sh 标题 正文文件 [skip-if-open]。需要 GH_TOKEN、GITHUB_REPOSITORY、GITHUB_REPOSITORY_OWNER。
set -eu
title=$1
body=$2
mode=${3:-comment}
# 标题经环境变量传给 awk（ENVIRON），不用 -v：-v 会把标题里的反斜杠当转义处理
number=$(gh api --paginate "repos/$GITHUB_REPOSITORY/issues?labels=failure&state=open&per_page=100" \
  --jq '.[] | "\(.number)\t\(.title)"' | t=$title awk -F '\t' '$2 == ENVIRON["t"] {print $1; exit}')
if [ -n "$number" ] && [ "$mode" = skip-if-open ]; then
  echo "同标题的失败 Issue #$number 还开着，不重复开：$title"
  exit 0
fi
printf '\ncc @%s\n' "$GITHUB_REPOSITORY_OWNER" >> "$body"
if [ -n "$number" ]; then
  echo "同标题的失败 Issue #$number 还开着，把这次的情况追加为评论。"
  gh issue comment "$number" --repo "$GITHUB_REPOSITORY" --body-file "$body" && exit 0
  echo "评论没加上，改开一个新的失败 Issue。" >&2
fi
gh issue create --repo "$GITHUB_REPOSITORY" --title "$title" --body-file "$body" --label failure
