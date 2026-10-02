"""测试统一用中文界面：从源码运行时数据目录就是仓库，作者在界面上切成英文后，prefs.json 不能影响测试结果。"""
import os

os.environ.setdefault("EASYREAD_LANG", "zh")
