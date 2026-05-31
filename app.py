import os
import base64
import time
import re
import struct
import io
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import yaml
from dotenv import load_dotenv

try:
    from tencentcloud.common import credential
    from tencentcloud.common.profile.client_profile import ClientProfile
    from tencentcloud.common.profile.http_profile import HttpProfile
    from tencentcloud.common.exception import TencentCloudSDKException
    from tencentcloud.asr.v20190614 import asr_client, models
    TENCENT_CLOUD_AVAILABLE = True
except ImportError:
    TENCENT_CLOUD_AVAILABLE = False
    print("[WARN] Tencent Cloud SDK not installed")

load_dotenv()

app = Flask(__name__, template_folder='templates')
CORS(app, resources={r"/api/*": {"origins": "*"}})

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

with open('config.yaml', 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

asr_config = config.get('tencentcloud-asr', {})
SERVER_CONFIG = config.get('server', {})
AUDIO_CONFIG = config.get('audio', {})
INPUT_CONFIG = config.get('input_method', {})

SECRET_ID = os.getenv("TENCENT_SECRET_ID") or asr_config.get('secret_id', '')
SECRET_KEY = os.getenv("TENCENT_SECRET_KEY") or asr_config.get('secret_key', '')

print(f"[INIT] SECRET_ID loaded: {SECRET_ID[:10]}..." if SECRET_ID else "[INIT] SECRET_ID not loaded")
print(f"[INIT] SECRET_KEY loaded: {SECRET_KEY[:10]}..." if SECRET_KEY else "[INIT] SECRET_KEY not loaded")


def create_wav_header(data_len, sample_rate=16000, bits_per_sample=16, channels=1):
    byte_rate = sample_rate * channels * bits_per_sample // 8
    block_align = channels * bits_per_sample // 8
    
    header = struct.pack(
        '<4sI4s4sIHHIIHH4sI',
        b'RIFF',
        36 + data_len,
        b'WAVE',
        b'fmt ',
        16,
        1,
        channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b'data',
        data_len
    )
    return header


def pcm_to_wav(pcm_data, sample_rate=16000, bits_per_sample=16, channels=1):
    wav_header = create_wav_header(len(pcm_data), sample_rate, bits_per_sample, channels)
    return wav_header + pcm_data


class TextProcessor:
    def __init__(self):
        self.punctuation_map = {
            '。': '.',
            '，': ',',
            '！': '!',
            '？': '?',
            '：': ':',
            '；': ';',
            '（': '(',
            '）': ')',
            '《': '<',
            '》': '>',
            '【': '[',
            '】': ']',
            '——': '--',
            '……': '...',
            '～': '~'
        }

    def convert_punctuation(self, text):
        result = []
        for char in text:
            result.append(self.punctuation_map.get(char, char))
        return ''.join(result)

    def add_spaces(self, text):
        text = re.sub(r'([,.!?;:])(\S)', r'\1 \2', text)
        text = re.sub(r'(\S)([,.!?;:])', r'\1 \2', text)
        return text

    def process(self, text, auto_space=True):
        text = re.sub(r'\[\s*\d+\s*:\s*\d+\s*\.\s*\d+\s*,\s*\d+\s*:\s*\d+\s*\.\s*\d+\s*\]\s*', '', text)
        text = re.sub(r'\[\s*[\d\s:.，,]*\]\s*', '', text)
        text = self.convert_punctuation(text)
        if auto_space:
            text = self.add_spaces(text)
        text = text.strip()
        text = re.sub(r'[.,!?;:、，。！？；：]$', '', text)
        text = text.strip()
        return text


text_processor = TextProcessor()


VOCABULARY_NAME = "auto_hotwords_dynamic"

def ensure_vocabulary_exists(client, hotwords):
    if not TENCENT_CLOUD_AVAILABLE:
        return False
    try:
        describe_req = models.DescribeVocabRequest()
        describe_req.VocabularyName = VOCABULARY_NAME
        describe_resp = client.DescribeVocab(describe_req)
        print(f"[Hotword] Vocabulary {VOCABULARY_NAME} already exists")
        return True
    except Exception as e:
        print(f"[Hotword] Vocabulary not found, creating new one: {str(e)}")
    
    try:
        create_req = models.CreateVocabRequest()
        create_req.VocabularyName = VOCABULARY_NAME
        create_req.WordWeights = "\n".join([f"{word} 1" for word in hotwords.split(',')])
        create_resp = client.CreateVocab(create_req)
        print(f"[Hotword] Created vocabulary successfully: {create_resp.Data.VocabularyName}")
        return True
    except Exception as e:
        print(f"[Hotword] Failed to create vocabulary: {str(e)}")
        return False

def update_vocabulary(client, hotwords):
    if not TENCENT_CLOUD_AVAILABLE:
        return False
    try:
        update_req = models.UpdateVocabRequest()
        update_req.VocabularyName = VOCABULARY_NAME
        update_req.WordWeights = "\n".join([f"{word} 1" for word in hotwords.split(',')])
        update_resp = client.UpdateVocab(update_req)
        print(f"[Hotword] Updated vocabulary successfully")
        return True
    except Exception as e:
        print(f"[Hotword] Failed to update vocabulary: {str(e)}")
        return False

def recognize_audio(audio_data, format='wav', hotwords=None):
    if not SECRET_ID or not SECRET_KEY:
        return {'success': False, 'error': 'API密钥未配置', 'text': '(请在.env文件中配置腾讯云ASR密钥)'}

    try:
        from tencentcloud.common import credential
        from tencentcloud.common.profile.client_profile import ClientProfile
        from tencentcloud.common.profile.http_profile import HttpProfile
        from tencentcloud.common.exception import TencentCloudSDKException
        from tencentcloud.asr.v20190614 import asr_client, models

        print(f"[DEBUG] Using SECRET_ID: {SECRET_ID[:10]}...")
        print(f"[DEBUG] Audio data length: {len(audio_data)} bytes")
        if hotwords:
            print(f"[DEBUG] Hotwords: {hotwords}")
        
        cred = credential.Credential(SECRET_ID, SECRET_KEY)
        httpProfile = HttpProfile()
        httpProfile.endpoint = "asr.tencentcloudapi.com"

        clientProfile = ClientProfile()
        clientProfile.httpProfile = httpProfile

        client = asr_client.AsrClient(cred, "ap-shanghai", clientProfile)

        if hotwords:
            ensure_vocabulary_exists(client, hotwords)
            update_vocabulary(client, hotwords)

        req = models.CreateRecTaskRequest()
        req.EngineModelType = "16k_zh"
        req.ChannelNum = 1
        req.SourceType = 1
        req.DataLen = len(audio_data)
        req.Data = base64.b64encode(audio_data).decode('utf-8')
        req.ResTextFormat = 0
        
        if hotwords:
            req.VocabularyName = VOCABULARY_NAME

        resp = client.CreateRecTask(req)
        task_id = resp.Data.TaskId

        for attempt in range(20):
            time.sleep(0.5)
            describe_req = models.DescribeTaskStatusRequest()
            describe_req.TaskId = task_id
            describe_resp = client.DescribeTaskStatus(describe_req)

            if describe_resp.Data.Status == 2:
                result = describe_resp.Data.Result
                print(f"[DEBUG] Recognition result: {result}")
                return {'success': True, 'text': result}
            elif describe_resp.Data.Status == 3:
                return {'success': False, 'error': '识别失败'}

        return {'success': False, 'error': '等待结果超时'}

    except Exception as e:
        return {'success': False, 'error': str(e)}


@app.route('/')
def index():
    return render_template('index.html', config=config)


@app.route('/api/recognize', methods=['POST'])
def recognize():
    print(f"[DEBUG] Request received at /api/recognize")

    content_type = request.headers.get('Content-Type', '')

    if 'application/json' in content_type:
        data = request.get_json()
        audio_base64 = data.get('audio', '')
        audio_format = data.get('format', 'webm')
        hotwords = data.get('hotwords', None)

        if not audio_base64:
            return jsonify({'success': False, 'error': 'No audio data'})

        audio_data = base64.b64decode(audio_base64)
        print(f"[DEBUG] Received base64 audio, length: {len(audio_data)} bytes, format: {audio_format}")

        if audio_format == 'pcm':
            audio_data = pcm_to_wav(audio_data)
            audio_format = 'wav'
            print(f"[DEBUG] Converted PCM to WAV: {len(audio_data)} bytes")

    elif 'audio' in request.files:
        file = request.files['audio']
        audio_data = file.read()
        audio_format = file.filename.split('.')[-1] if '.' in file.filename else 'wav'
        hotwords = request.form.get('hotwords', None)
        print(f"[DEBUG] Received file, length: {len(audio_data)} bytes, format: {audio_format}")
    else:
        audio_data = request.data
        audio_format = request.args.get('format', 'wav')
        hotwords = request.args.get('hotwords', None)
        print(f"[DEBUG] Received raw data, length: {len(audio_data)} bytes")

    if not audio_data:
        return jsonify({'success': False, 'error': 'No audio data'})

    result = recognize_audio(audio_data, audio_format, hotwords)

    if result.get('success'):
        processed_text = text_processor.process(
            result['text'],
            auto_space=INPUT_CONFIG.get('auto_space', True)
        )
        return jsonify({
            'success': True,
            'original': result['text'],
            'processed': processed_text
        })
    else:
        return jsonify(result), 500


@app.route('/api/type', methods=['POST'])
def type_text():
    data = request.get_json()
    text = data.get('text', '')

    if not text:
        return jsonify({'success': False, 'error': 'No text provided'})

    try:
        import pyautogui
        pyautogui.typewrite(text, interval=INPUT_CONFIG.get('default_delay', 0.05))
        return jsonify({'success': True})
    except ImportError:
        return jsonify({'success': False, 'error': 'pyautogui未安装'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/status', methods=['GET'])
def status():
    return jsonify({
        'success': True,
        'config': {
            'server': SERVER_CONFIG,
            'audio': AUDIO_CONFIG,
            'input_method': INPUT_CONFIG
        },
        'has_credentials': bool(SECRET_ID and SECRET_KEY)
    })


streaming_tasks = {}

@socketio.on('connect')
def handle_connect():
    print('[SocketIO] Client connected')
    emit('connected', {'status': 'connected'})

@socketio.on('disconnect')
def handle_disconnect():
    print('[SocketIO] Client disconnected')

@socketio.on('start_streaming')
def handle_start_streaming():
    print('[SocketIO] Start streaming requested')
    emit('streaming_started', {'status': 'started'})

@socketio.on('stop_streaming')
def handle_stop_streaming():
    print('[SocketIO] Stop streaming requested')
    emit('streaming_stopped', {'status': 'stopped'})

@socketio.on('audio_data')
def handle_audio_data(data):
    try:
        audio_base64 = data.get('audio', '')
        audio_format = data.get('format', 'pcm')

        if not audio_base64:
            emit('streaming_error', {'error': 'No audio data'})
            return

        audio_data = base64.b64decode(audio_base64)
        print(f'[SocketIO] Received audio data: {len(audio_data)} bytes, format: {audio_format}')

        if audio_format == 'pcm':
            audio_data = pcm_to_wav(audio_data)
            print(f'[SocketIO] Converted PCM to WAV: {len(audio_data)} bytes')

        result = recognize_audio(audio_data, 'wav')

        if result.get('success'):
            processed_text = text_processor.process(
                result['text'],
                auto_space=INPUT_CONFIG.get('auto_space', True)
            )
            emit('streaming_result', {
                'success': True,
                'original': result['text'],
                'processed': processed_text,
                'is_final': True
            })
        else:
            emit('streaming_error', {'error': result.get('error', 'Recognition failed')})

    except Exception as e:
        print(f'[SocketIO] Error processing audio: {str(e)}')
        emit('streaming_error', {'error': str(e)})


if __name__ == '__main__':
    print("=" * 60)
    print("[Voice Input] Starting service...")
    print("=" * 60)
    print(f"Server: http://{SERVER_CONFIG.get('host', '0.0.0.0')}:{SERVER_CONFIG.get('port', 5000)}")
    print(f"Tencent ASR: {'Configured' if (SECRET_ID and SECRET_KEY) else 'Not configured'}")
    print("=" * 60)

    socketio.run(
        app,
        host=SERVER_CONFIG.get('host', '0.0.0.0'),
        port=SERVER_CONFIG.get('port', 5000),
        debug=SERVER_CONFIG.get('debug', False),
        allow_unsafe_werkzeug=True
    )
