// 실제 로그인이나 외부 모델을 사용하지 않고 ChatGPT 경로의 요청 도구 목록을 점검한다.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { test } from "node:test";
import { codexArgs } from "./codex_engine.mjs";
import { inspectFeatures, POLICY_ARGS } from "./codex_policy.mjs";

// 로컬 두 서버와 합성 인증정보만 사용한다. 자식 프로세스는 seatbelt가 loopback 외 네트워크를 막는다.
const PROBE = String.raw`
import base64, http.server, json, os, pathlib, socket, ssl, subprocess, tempfile, threading, time

sandbox = '(version 1) (allow default) (deny network-outbound) (allow network-outbound (remote ip "localhost:*"))'
isolated = os.environ.get('CODEX_DOCKER_ISOLATED') == '1'
prefix = [] if isolated else ['sandbox-exec', '-p', sandbox]
check = subprocess.run(prefix + ['python3', '-c', 'import socket; s=socket.socket(); s.settimeout(1); print(s.connect_ex(("1.1.1.1",443)))'], capture_output=True, text=True, timeout=5)
if check.returncode != 0 or check.stdout.strip() not in ('1', '13', '101'):
    raise RuntimeError('Sandbox did not prove external network denial')

def b64(value):
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip('=')

with tempfile.TemporaryDirectory(prefix='codex-wire-test-') as tmp:
    p = pathlib.Path(tmp)
    home = p / 'home'; home.mkdir()
    subprocess.run(['openssl','req','-new','-newkey','rsa:2048','-nodes','-x509','-days','1','-subj','/CN=Mock CA','-keyout',str(p/'ca.key'),'-out',str(p/'ca.pem')], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    subprocess.run(['openssl','req','-new','-newkey','rsa:2048','-nodes','-subj','/CN=localhost','-keyout',str(p/'sv.key'),'-out',str(p/'sv.csr')], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    (p/'ext').write_text('subjectAltName=IP:127.0.0.1,DNS:localhost\nextendedKeyUsage=serverAuth\nbasicConstraints=CA:FALSE\n')
    subprocess.run(['openssl','x509','-req','-in',str(p/'sv.csr'),'-CA',str(p/'ca.pem'),'-CAkey',str(p/'ca.key'),'-CAcreateserial','-days','1','-extfile',str(p/'ext'),'-out',str(p/'sv.pem')], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    captured = []
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            if self.path.endswith('/accounts/check'):
                data = {'accounts':[{'id':'selected','workspace_backend_origin':f'https://127.0.0.1:{tls_port}','account_routing_override':'NO_CONSTRAINT'}], 'default_account_id':'selected'}
            else:
                data = {}
            self.send_response(200); self.send_header('content-type','application/json'); self.end_headers(); self.wfile.write(json.dumps(data).encode())
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get('content-length','0')))
            if self.headers.get('content-encoding') == 'zstd':
                body = subprocess.run(['zstd','-d','-q','-c'], input=body, capture_output=True, check=True).stdout
            if self.path.endswith('/responses'):
                message = json.loads(body)
                toolsets = []
                additional = []
                def scan(value, path):
                    if isinstance(value, dict):
                        if value.get('type') == 'additional_tools':
                            additional.append(path)
                            if 'tools' not in value:
                                toolsets.append({'path':path+'.tools','valid':False,'count':-1,'names':[]})
                        for key, child in value.items():
                            if key == 'tools':
                                names = [item.get('name', item.get('type','unknown')) if isinstance(item, dict) else 'invalid' for item in child] if isinstance(child,list) else []
                                toolsets.append({'path':path+'.tools','valid':isinstance(child,list),'count':len(child) if isinstance(child,list) else -1,'names':names})
                            scan(child, path+'.'+key)
                    elif isinstance(value, list):
                        for index, child in enumerate(value): scan(child, f'{path}[{index}]')
                scan(message, '$')
                captured.append({'model':message.get('model'), 'input_valid':isinstance(message.get('input'),list), 'additional_count':len(additional), 'toolsets':toolsets})
            self.send_response(400); self.send_header('content-type','application/json'); self.end_headers(); self.wfile.write(b'{"error":{"message":"synthetic stop"}}')

    secure = http.server.ThreadingHTTPServer(('127.0.0.1',0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); context.load_cert_chain(p/'sv.pem',p/'sv.key'); secure.socket = context.wrap_socket(secure.socket,server_side=True)
    tls_port = secure.server_port
    bootstrap = http.server.ThreadingHTTPServer(('127.0.0.1',0), Handler)
    for server in (secure, bootstrap): threading.Thread(target=server.serve_forever, daemon=True).start()
    env = {'PATH':os.environ['PATH'], 'HOME':str(home), 'CODEX_HOME':str(home), 'CODEX_CA_CERTIFICATE':str(p/'ca.pem'), 'SSL_CERT_FILE':str(p/'ca.pem'), 'LANG':'en_US.UTF-8', 'NO_PROXY':'*'}
    (home/'auth.json').write_text(json.dumps({'auth_mode':'chatgpt','OPENAI_API_KEY':None,'tokens':{'id_token':b64({'alg':'none','typ':'JWT'})+'.'+b64({'email':'fake@example.invalid','https://api.openai.com/auth':{'chatgpt_plan_type':'pro','chatgpt_account_id':'selected'}})+'.c2lnbmF0dXJl','access_token':'synthetic-access','refresh_token':'synthetic-refresh','account_id':'selected'},'last_refresh':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}))
    if isolated:
        catalog = json.loads(pathlib.Path('/opt/pr-review/model.json').read_text())
        model = next(item for item in catalog['models'] if item['slug']=='gpt-6-luna')
    else:
        catalog = json.loads(subprocess.check_output(prefix + ['codex','debug','models','--bundled'],env=env,text=True))
        model = next(item for item in catalog['models'] if item['slug']=='gpt-6-luna')
        model.update(apply_patch_tool_type=None,shell_type='disabled',experimental_supported_tools=[],tool_mode='direct',supports_search_tool=False,multi_agent_version='disabled')
    if (model.get('apply_patch_tool_type') is not None or model.get('shell_type') != 'disabled' or model.get('experimental_supported_tools') != [] or model.get('tool_mode') != 'direct' or model.get('supports_search_tool') is not False or model.get('multi_agent_version') != 'disabled'):
        raise RuntimeError('Unsafe model metadata')
    (p/'models.json').write_text(json.dumps({'models':[model]}))
    (p/'instructions.md').write_text('Return JSON only.')
    (p/'schema.json').write_text('{"type":"object","properties":{"ok":{"type":"boolean"}},"required":["ok"],"additionalProperties":false}')
    replacements = {'[WORK]':str(p), '[INSTRUCTIONS]':str(p/'instructions.md'), '[SCHEMA]':str(p/'schema.json'), '[LAST]':str(p/'last.json')}
    args = [next((part.replace(key,value) for key,value in replacements.items() if key in part),part) for part in json.loads(os.environ['CODEX_TEST_ARGS'])]
    i = args.index('--output-schema')
    args[i:i] = ['-c',f'chatgpt_base_url="http://127.0.0.1:{bootstrap.server_port}/backend-api/"','-c',f'model_catalog_json="{p}/models.json"']
    features = None
    try:
        if isolated:
            features = subprocess.check_output(['codex','features','list',*json.loads(os.environ['CODEX_TEST_POLICY_ARGS']),'-c',f'chatgpt_base_url="http://127.0.0.1:{bootstrap.server_port}/backend-api/"'],env=env,cwd=p,text=True,timeout=20)
        subprocess.run(prefix + ['codex',*args],env=env,cwd=p,input='synthetic prompt',capture_output=True,text=True,timeout=35)
    finally:
        secure.shutdown(); bootstrap.shutdown()
    print(json.dumps({'requests':captured,'features':features}))
`;

const args = () => codexArgs({ model: "gpt-6-luna", effort: "medium", workDir: "[WORK]", instructionsFile: "[INSTRUCTIONS]", schemaFile: "[SCHEMA]", lastFile: "[LAST]" });
function assertWire(result) {
  assert.equal(result.status, 0, result.stderr);
  const data = JSON.parse(result.stdout);
  assert.ok(data.requests.length > 0, "모의 ChatGPT 응답 엔드포인트에 요청이 도달해야 함");
  for (const request of data.requests) {
    assert.equal(request.model, "gpt-6-luna");
    assert.equal(request.input_valid, true, "실제 Responses 입력이어야 함");
    assert.ok(request.additional_count > 0, "Responses Lite의 추가 도구 구획이 있어야 함");
    for (const set of request.toolsets) {
      assert.ok(set.valid && set.count === 0, `도구 정의가 발견됨: ${set.path}: ${set.names.join(", ")}`);
    }
  }
  return data;
}

test("합성 ChatGPT 경로가 모델에 도구를 보내지 않는다", { timeout: 40_000 }, (t) => {
  if (process.platform !== "darwin") return t.skip("격리 검증은 macOS sandbox-exec에서만 실행");
  for (const bin of ["sandbox-exec", "python3", "openssl", "zstd"]) {
    if (spawnSync("which", [bin]).status !== 0) return t.skip(`${bin} 없음`);
  }
  const version = spawnSync("codex", ["--version"], { encoding: "utf8", env: { PATH: process.env.PATH } });
  if (version.status !== 0 || version.stdout.trim() !== "codex-cli 0.160.1") return t.skip("고정 Codex CLI 없음");
  const result = spawnSync("python3", ["-c", PROBE], { encoding: "utf8", env: { PATH: process.env.PATH, CODEX_TEST_ARGS: JSON.stringify(args()) }, timeout: 38_000 });
  assertWire(result);
});

test("Linux 격리 시제품에서 합성 ChatGPT 도구와 관리형 기능을 확인한다", { timeout: 150_000 }, (t) => {
  const image = process.env.CODEX_TEST_DOCKER_IMAGE;
  if (!image) return t.skip("명시적인 합성 시험 이미지가 없음");
  assert.match(image, /^sha256:[a-f0-9]{64}$/, "불변 이미지 ID 필요");
  const dockerArgs = ["run", "--rm", "--platform", "linux/amd64", "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--pids-limit", "128", "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m", "--user", "65534:65534", "-e", "CODEX_DOCKER_ISOLATED=1", "-e", `CODEX_TEST_ARGS=${JSON.stringify(args())}`, "-e", `CODEX_TEST_POLICY_ARGS=${JSON.stringify(POLICY_ARGS)}`, "--entrypoint", "python3", image, "-c", PROBE];
  const env = Object.fromEntries(["PATH", "HOME", "DOCKER_HOST", "DOCKER_CONFIG", "TMPDIR"].filter((key) => process.env[key] !== undefined).map((key) => [key, process.env[key]]));
  const result = spawnSync("docker", dockerArgs, { encoding: "utf8", env, timeout: 140_000 });
  const data = assertWire(result);
  inspectFeatures(data.features);
});
