# 采购 PO 合规审计规则

输出一个逗号分隔的 po_id 字符串，按 po_id 升序排列。

## 审计范围

先按状态筛选，再按金额筛选。只审计状态语义明确表示已结束、已完成、已支付、已验收、已关闭或已结案，且 amount_cny >= 50000 CNY 的 PO。

状态字段可能使用中英文表达；草稿、评审中、审批中、待补件、取消、已取消、作废等未结束或已取消/作废状态无效。状态无效或金额低于阈值的 PO 不进入深审，也不输出。

## 供应商服务范围

深审 PO 的 service_items 必须全部落在 vendors.csv 中该供应商的 service_scope 内。只要有关键采购内容不在服务范围内，该 PO 不合规。

## VP 审批

approval_evidence.csv 是附件索引，真实审批内容在 file_path 指向的附件文件中。

有效审批必须同时满足：审批证据明确覆盖当前 PO；明确批准当前 PO 的全部 service_items；发件人邮箱匹配 people_roles.csv；该人员在审批日期的 role 为 VP；审批日期处于该 VP 身份有效期内；审批日期不晚于 PO 的 po_date。

Director、Manager、VP Assistant 或过期 VP 都不算有效 VP 审批。“考虑一下”“先评估”“另行确认”等不是完整审批；审批其他 PO 的邮件不能覆盖当前 PO。
