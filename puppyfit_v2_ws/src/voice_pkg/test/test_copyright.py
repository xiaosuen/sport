# Copyright 2015 Open Source Robotics Foundation, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

'''
:brief ament_copyright 检查测试
:desc 调用 ament_copyright 扫描包内源码版权声明；当前用例默认 skip，待业务代码补充版权头后移除 skip。

:author ubuntu
:date 2026/03/28
:version 1.0.0
'''

from ament_copyright.main import main
import pytest


# Remove the `skip` decorator once the source file(s) have a copyright header
@pytest.mark.skip(reason='No copyright header has been placed in the generated source file.')
@pytest.mark.copyright
@pytest.mark.linter
def test_copyright():
    '''
    :brief 执行版权检查
    :return 无；断言 rc == 0
    '''
    rc = main(argv=['.', 'test'])
    assert rc == 0, 'Found errors'
