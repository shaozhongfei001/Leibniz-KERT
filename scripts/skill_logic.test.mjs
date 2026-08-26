// 离线单测：Skill 运行平台核心控制流（幂等/未知 skillId/JSON 解析/成功路径）
// 运行：node scripts/skill_logic.test.mjs （不依赖 DSH 运行时，mock llm/shell）
import assert from 'node:assert'

// ---- 从插件代码提取的核心逻辑（无 llm/shell/webServer 依赖）----
const SKILLS = {
  'skill-customer-outreach-script': { name: '外联脚本', version: '1.0.0' },
  'skill-customer-meeting-script': { name: '会面脚本', version: '1.0.0' },
}
const idemCache = new Map()

function parseJsonObject(text) {
  const trimmed = String(text || '').trim()
  const m = trimmed.match(/\{[\s\S]*\}/)
  const candidate = m ? m[0] : trimmed
  try {
    const obj = JSON.parse(candidate)
    if (obj && typeof obj === 'object' && !Array.isArray(obj)) return obj
  } catch { /* fallthrough */ }
  return null
}

// mock executor：成功（返回 JSON 字符串）或抛错（fail-closed）
const mockExecutorOk = { run: async () => ({ text: '{"scriptTitle":"t","sections":[]}', modelCall: { model: 'mock', inputTokens: 1, outputTokens: 1, latencyMs: 5 } }) }
const mockExecutorFail = { run: async () => { throw new Error('模型调用失败（fail-closed）') } }

async function executeSkill(payload, executor) {
  const requestId = String(payload && payload.requestId || '')
  const skillId = String(payload && payload.skillId || '')
  const req = (payload && payload.request) || {}
  const trace = []
  trace.push({ phase: 'resolve', status: 'ok', message: 'skillId=' + skillId + ' requestId=' + requestId })
  if (requestId && idemCache.has(requestId)) {
    const hit = idemCache.get(requestId)
    trace.push({ phase: 'idempotency', status: 'ok', message: '命中缓存（NO_OP）' })
    return { ...hit.result, assemblyTrace: trace.concat(hit.result.assemblyTrace || []) }
  }
  if (!executor) {
    trace.push({ phase: 'resolve', status: 'failed', message: '未知 skillId' })
    return { requestId, status: 'skill_error', data: {}, errors: [{ code: 'UNKNOWN_SKILL', message: '未知 skillId: ' + skillId }], assemblyTrace: trace, modelCalls: [] }
  }
  const noNew = null // 无新证据策略已随 R1 拜访报告 Skill 下线移除（2026-08-21）
  if (noNew) {
    trace.push({ phase: 'evidence', status: 'blocked', message: noNew })
    const result = { requestId, status: 'exit_policy_no_new_evidence', data: {}, assemblyTrace: trace, modelCalls: [] }
    if (requestId) idemCache.set(requestId, { result, ts: Date.now() })
    return result
  }
  trace.push({ phase: 'validate', status: 'ok', message: '请求校验通过' })
  try {
    const { text, modelCall } = await executor.run(req, trace)
    const data = parseJsonObject(text)
    if (!data || !Array.isArray(data.sections)) { trace.push({ phase: 'parse', status: 'failed', message: '输出结构校验失败' }); throw new Error('输出结构校验失败（fail-closed）') }
    trace.push({ phase: 'compose', status: 'ok', message: '结果组装完成' })
    const result = { requestId, status: 'ok', data: { scriptTitle: data.scriptTitle, sections: data.sections }, assemblyTrace: trace, modelCalls: [modelCall] }
    if (requestId) idemCache.set(requestId, { result, ts: Date.now() })
    return result
  } catch (err) {
    trace.push({ phase: 'compose', status: 'failed', message: String(err && err.message || err) })
    const result = { requestId, status: 'skill_error', data: {}, errors: [{ code: 'SKILL_EXECUTION_FAILED', message: String(err && err.message || err) }], assemblyTrace: trace, modelCalls: [] }
    if (requestId) idemCache.set(requestId, { result, ts: Date.now() })
    return result
  }
}

// ---- 断言 ----
let pass = 0
function check(label, cond, detail = '') {
  if (cond) pass++
  console.log(`  [${cond ? 'PASS' : 'FAIL'}] ${label}` + (cond ? '' : '  ' + detail))
}

console.log('== 未知 skillId ==')
let r = await executeSkill({ skillId: 'skill-unknown', requestId: 'u1', request: {} }, null)
check('skill_error + UNKNOWN_SKILL', r.status === 'skill_error' && r.errors[0].code === 'UNKNOWN_SKILL')

console.log('== 成功路径（ok + trace + modelCalls）==')
r = await executeSkill({ skillId: 'skill-customer-outreach-script', requestId: 'ok1', request: { customerId: 'C1' } }, mockExecutorOk)
check('status ok', r.status === 'ok')
check('data.sections 数组', Array.isArray(r.data.sections))
check('assemblyTrace 非空', Array.isArray(r.assemblyTrace) && r.assemblyTrace.length >= 3)
check('modelCalls 含 model/latencyMs/tokens', r.modelCalls[0].model === 'mock' && r.modelCalls[0].latencyMs >= 0 && r.modelCalls[0].inputTokens >= 0)

console.log('== 幂等（requestId 重放）==')
r = await executeSkill({ skillId: 'skill-customer-outreach-script', requestId: 'idem1', request: { customerId: 'C1' } }, mockExecutorOk)
r = await executeSkill({ skillId: 'skill-customer-outreach-script', requestId: 'idem1', request: { customerId: 'C1' } }, mockExecutorOk)
check('重放命中幂等 NO_OP', r.assemblyTrace.some((t) => t.phase === 'idempotency'))

console.log('== fail-closed（executor 抛错）==')
r = await executeSkill({ skillId: 'skill-customer-outreach-script', requestId: 'fail1', request: {} }, mockExecutorFail)
check('skill_error + SKILL_EXECUTION_FAILED', r.status === 'skill_error' && r.errors[0].code === 'SKILL_EXECUTION_FAILED')
check('fail-closed 无残缺 data', r.data && Object.keys(r.data).length === 0)

console.log('== JSON 解析（markdown 包裹）==')
const md = '```json\n{"scriptTitle":"外联脚本","sections":[{"heading":"开场","content":"您好"}]}\n```'
check('markdown 包 JSON 提取', parseJsonObject(md)?.scriptTitle === '外联脚本')
check('非法 JSON → null', parseJsonObject('not json at all') === null)

console.log(`\n结果: ${pass}/10 PASS`)
assert.strictEqual(pass, 10)
