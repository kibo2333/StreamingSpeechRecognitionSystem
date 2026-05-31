import os
import base64
from dotenv import load_dotenv

load_dotenv()

SECRET_ID = os.getenv('TENCENT_SECRET_ID')
SECRET_KEY = os.getenv('TENCENT_SECRET_KEY')

print("=" * 60)
print("腾讯云ASR API测试")
print("=" * 60)
print(f"SECRET_ID: {SECRET_ID[:10]}..." if SECRET_ID else "SECRET_ID: 未配置")
print(f"SECRET_KEY: {SECRET_KEY[:10]}..." if SECRET_KEY else "SECRET_KEY: 未配置")
print("=" * 60)

if not SECRET_ID or not SECRET_KEY:
    print("错误：API密钥未配置")
    exit(1)

try:
    from tencentcloud.common import credential
    from tencentcloud.common.profile.client_profile import ClientProfile
    from tencentcloud.common.profile.http_profile import HttpProfile
    from tencentcloud.common.exception import TencentCloudSDKException
    from tencentcloud.asr.v20190614 import asr_client, models
    
    print("[OK] 导入腾讯云SDK成功")
    
    cred = credential.Credential(SECRET_ID, SECRET_KEY)
    print("[OK] 创建Credential成功")
    
    httpProfile = HttpProfile()
    httpProfile.endpoint = "asr.tencentcloudapi.com"
    print("[OK] 创建HttpProfile成功")
    
    clientProfile = ClientProfile()
    clientProfile.httpProfile = httpProfile
    print("[OK] 创建ClientProfile成功")
    
    client = asr_client.AsrClient(cred, "ap-shanghai", clientProfile)
    print("[OK] 创建ASR客户端成功")
    
    # 创建一个简单的测试音频（静音数据）
    test_audio = bytes([0] * 32000)
    
    req = models.CreateRecTaskRequest()
    req.EngineModelType = "16k_zh"
    req.ChannelNum = 1
    req.SourceType = 1
    req.DataLen = len(test_audio)
    req.Data = base64.b64encode(test_audio).decode('utf-8')
    req.ResTextFormat = 0
    
    print("[OK] 构建请求成功")
    print("正在调用腾讯云ASR API...")
    
    resp = client.CreateRecTask(req)
    print(f"[OK] API调用成功！TaskId: {resp.Data.TaskId}")
    
except TencentCloudSDKException as e:
    print("\n[ERROR] 腾讯云SDK错误:")
    print(f"   错误代码: {e.code}")
    print(f"   错误信息: {e.message}")
    print("\n可能的原因:")
    print("1. SECRET_ID或SECRET_KEY不正确")
    print("2. 子账号没有ASR服务权限")
    print("3. 腾讯云ASR服务未开通")
    print("4. 账号余额不足")
except ImportError as e:
    print(f"[ERROR] 导入SDK失败: {e}")
except Exception as e:
    print(f"[ERROR] 其他错误: {e}")

print("=" * 60)