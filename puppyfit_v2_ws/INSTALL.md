# 安装ros2相关依赖
```
rosdep update # 更新 rosdep 数据库
rosdep install --from-paths src --ignore-src -r -y #自动安装所有依赖
```
# 遍历setup.py中的python依赖
```
python3 sripts merge_setup_requires.py
```
# 换源
```
sudo sed -i 's|https://mirrors.tuna.tsinghua.edu.cn/ubuntu-ports|https://mirrors.aliyun.com/ubuntu-ports|g' /etc/apt/sources.list
sudo sed -i 's|mirrors.tuna.tsinghua.edu.cn/ros2/ubuntu|mirrors.aliyun.com/ros2/ubuntu|g' /etc/apt/sources.list.d/ros2-latest.list

```
# 安装python依赖
```
/usr/bin/python3 -m pip install --user -r /home/ubuntu/puppyfit/puppyfit_v2_ws/requirements-from-setuppy.txt
```

# 更换好听的音色(可选)
```
/usr/bin/python3 -m pip install --user 'piper-tts[zh]' 'onnxruntime>=1,<2'
```
