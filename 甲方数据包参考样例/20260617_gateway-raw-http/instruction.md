对当前项目代码新增一个 trace 采集和整理的过程，首先检查当前是否已经完整记录了上游服务器完整的 request/response 日志，包括 http header 日志。如果不完整需要记录，url 中应该有一个 query 参数标记 agent 的请求 sessionid（以防止部分 agent 没有传递 sessionid 信息），把同一个 sessionid query param 的 raw http 日志记录到 sessionid 命名的文件夹中。另外提供一个脚本，将同 sessionid 下的 raw log 转为 sharegpt 格式的 trace 文件。正常的请求日志会逐步追加 assist，但是也可能因为 subagent 或者是上下文压缩的问题导致并非完全是这样。通过 log 的 request 中的 assist 列表和请求时间戳顺序来整理 sharegpt 的 trace，遇到 subagent 可以使用 sessionid-subid_x 的文件命名方式针对每个 subagent 再有一个独立的 trace 文件。

测试结果需要通过 Test Acceptance 里面的 case 全部通过。
