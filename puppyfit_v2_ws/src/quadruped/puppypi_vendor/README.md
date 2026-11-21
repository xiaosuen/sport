# puppypi_vendor

将 **PuppyPi 官方 `puppypi_control` 运行时**（Python 模块、`puppy_kinematics.so`、`ActionGroups/` 等）安装到

`share/puppypi_vendor/puppypi_control/`，供 `puppy_control` 通过 `ament_index` 定位。

## 覆盖路径

若需使用系统其它目录下的副本：

```bash
export PUPPYPI_CONTROL_PATH=/home/ubuntu/software/puppypi_control
```

## 更新 vendor 内容

在 Ubuntu 上从官方目录同步（示例）：

```bash
cp -a /home/ubuntu/software/puppypi_control/. \
  ~/puppyfit_ws_repo/puppyfit_v2_ws/src/quadruped/puppypi_vendor/puppypi_control/
# 勿提交 gdb 产生的 core 文件
rm -f ~/puppyfit_ws_repo/puppyfit_v2_ws/src/quadruped/puppypi_vendor/puppypi_control/core
```
