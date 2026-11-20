export const ROLES={admin:'管理员',operator:'操作员',viewer:'观察员'};
export const STATUSES={queued:'等待执行',running:'执行中',completed:'已完成',failed:'执行失败'};
export const OPERATORS=['scan','filter','hash_join','group'];
export const VERDICTS={identical:'逐算子一致',result_equal_steps_unproven:'结果一致 / 步骤不可证',diverged:'存在分歧'};
export const STEP_KINDS={identical:'相同',changed:'参数调整',unproven:'无法证明',added:'新增',removed:'删除',conflict:'摘要冲突',output:'输出不一致'};
