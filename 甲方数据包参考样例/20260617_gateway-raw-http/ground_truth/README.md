# Ground-Truth Answer

标准答案文件，按 `environment/workspace/` 内相对路径存放。

将本目录下文件覆盖到 `environment/workspace/` 对应位置后，eval 应通过（reward = 1）。

可选：`ground_truth.patch` 为相对 baseline_commit 的 unified diff。
