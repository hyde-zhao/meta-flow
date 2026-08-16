# Meta Flow 0.5.3 回滚方案

1. 停止新的 0.5.3 mutation，保留所有 receipt、event、failure ID、observation segment 和 transaction manifest。
2. 运行只读 inspect，确认没有非终态 Work-init、scope-amend 或 correction transaction；存在 `PARTIAL`/`RECOVERED` 时先按 0.5.3 native recovery 收敛并停止。
3. 重新安装 GitHub Release 的 exact 0.5.2 wheel/receipt；不得从 dirty checkout 或 editable source 回滚正式 provider。
4. 重跑 route/project/state/CR/Work 检查以及 targeted/compatibility validation。
5. 不删除 0.5.3 创建的 terminal successor revision、receipt、observation 或 audit event；0.5.2 不理解的新状态必须保持只读并升级回 0.5.3 处理。

回滚不授权 real correction/cutover、raw history rewrite、waiver、consumer 数据迁移、force push 或历史 receipt 修改。
