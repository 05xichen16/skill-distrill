# Journal - xichen (Part 1)

> AI development session journal
> Started: 2026-06-10

---



## Session 1: 阶段B：评测工具固化 + 2_2 确定性 skill

**Date**: 2026-06-11
**Task**: 阶段B：评测工具固化 + 2_2 确定性 skill
**Branch**: `develop`

### Summary

固化判分逻辑为评测工具/回归台(source/eval；baseline 重现 12.386/32，白送分锚点 1_1=2/1_3=2/3_2=5 全中)；新增 2_2 敏感信息扫描确定性 skill(递归解 zip+tar+边界正则，文本计数 2782/3479/2299/3562；图 OCR 逐字转写+优雅降级)；补 mcp_client skill_run 的 question_dir 注入。回归台确认 1_1/1_3/3_2 未破坏。还原了 trellis-check 越界改的图片上限默认值。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `de03770` | (see git log) |
| `a01523b` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete
