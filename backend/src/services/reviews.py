import logging,uuid
import redis
from fastapi import HTTPException
from src.config.database import Session
from src.config.settings import REDIS_URL
from src.models.dataset import Dataset
from src.models.plan import Plan
from src.models.review import Review
from src.models.trace import Trace
from src.services.diffing import build_conclusion,build_ledger,canonical,compare_rows,step_descriptors
from src.services.operators import checksum,execute
from src.services.audit import log
from src.utils.serialization import record
queue=redis.Redis.from_url(REDIS_URL)
QUEUE_KEY='operator-reviews'

def _completed_baseline(s,baseline_trace_id,dataset_id):
 row=s.get(Trace,baseline_trace_id)
 if not row:raise HTTPException(404,'未找到基线执行')
 if row.status!='completed':raise HTTPException(409,'基线执行尚未完成，不能作为对账基线')
 if not row.result:raise HTTPException(409,'基线执行缺少完成结果')
 if row.dataset_id!=dataset_id:raise HTTPException(409,'基线与新执行必须来自同一数据集')
 try:step_descriptors(record(row))
 except ValueError as exc:raise HTTPException(409,str(exc))
 return row

def _requeue(item_id):
 try:queue.rpush(QUEUE_KEY,item_id)
 except redis.RedisError:raise HTTPException(503,'队列不可用，请稍后重试')

def create(data):
 with Session() as s:
  p=s.get(Plan,data.plan_id)
  if not p:raise HTTPException(404,'未找到算子计划')
  d=s.get(Dataset,p.dataset_id)
  if not d:raise HTTPException(409,'算子计划引用的数据集不存在')
  baseline=_completed_baseline(s,data.baseline_trace_id,d.id)
  if s.query(Review).filter_by(name=data.name).first():raise HTTPException(409,'复查名称已存在，请修改后重试')
  candidate=Trace(name=('%s 新执行 %s'%(data.name[:80],uuid.uuid4().hex[:6]))[:120],plan_id=p.id,dataset_id=d.id,status='queued',
   snapshot={'dataset':record(d),'plan':record(p)})
  s.add(candidate);s.flush()
  review=Review(name=data.name,dataset_id=d.id,plan_id=p.id,baseline_trace_id=baseline.id,candidate_trace_id=candidate.id,
   status='queued',progress={'completed':0,'steps_signature':canonical(p.steps)},attempts=1)
  s.add(review);s.commit();s.refresh(review);result=record(review)
 try:_requeue(result['id'])
 except HTTPException:
  with Session() as s:
   r=s.get(Review,result['id']);r.status='failed';r.error='队列不可用，请重试对账'
   c=s.get(Trace,r.candidate_trace_id);c.status='failed';c.error='队列不可用，请重试对账'
   s.commit()
  raise
 return result

def _checkpoint(review_id,message,state,attempts=None):
 with Session() as s:
  r=s.get(Review,review_id)
  if not r or r.status!='running':return
  if attempts is not None and r.attempts!=attempts:return
  r.progress=state;s.commit()

def _fail(review_id,message,attempts=None):
 with Session() as s:
  r=s.get(Review,review_id)
  if not r:return
  if r.status=='completed':return
  if attempts is not None and r.attempts!=attempts:return
  r.status='failed';r.error=message[:1000];r.result=None
  c=s.get(Trace,r.candidate_trace_id)
  if c:
   c.status='failed';c.error=message[:1000];c.result=None
  s.commit()
 log('worker','review.failed',f'{review_id}: {message[:200]}')

def run(review_id):
 with Session() as s:
  review=s.get(Review,review_id)
  if not review or review.status!='queued':return
  review.status='running';s.commit()
  candidate=s.get(Trace,review.candidate_trace_id);baseline=s.get(Trace,review.baseline_trace_id)
  attempts=review.attempts;progress=dict(review.progress or {'completed':0})
 try:
  if not candidate or not baseline:raise ValueError('复查缺少基线或新执行记录')
  if review.dataset_id!=candidate.dataset_id or review.dataset_id!=baseline.dataset_id:raise ValueError('复查数据集与执行快照不一致')
  baseline_snapshot=baseline.snapshot or {}
  if (baseline_snapshot.get('dataset') or {}).get('id')!=review.dataset_id:raise ValueError('基线快照不属于复查数据集')
  steps=(candidate.snapshot.get('plan') or {}).get('steps')
  steps_signature=canonical(steps)
  resume=None
  completed=int(progress.get('completed') or 0)
  if completed and progress.get('steps_signature')==steps_signature and len(progress.get('operators') or [])==completed:
   resume={k:progress[k] for k in ('completed','rows','operators','row_visits','elapsed_ms')}
  def checkpoint(index,message,state):
   state=dict(state);state['steps_signature']=steps_signature
   _checkpoint(review_id,message,state,attempts)
  result=execute(candidate.snapshot['dataset'],steps,resume=resume,on_step=checkpoint)
  if len(result['operators'])!=len(steps):
   raise ValueError('续跑后步骤数不完整，拒绝发布结论')
  if result['checksum']!=checksum(result['output']) or result['output_rows']!=len(result['output']):
   raise ValueError('执行结果摘要自检失败，拒绝发布结论')
  baseline_dict=record(baseline);candidate_dict=dict(record(candidate),result=result)
  baseline_output=baseline_dict['result'].get('output')
  if baseline_output is None or baseline_dict['result'].get('checksum')!=checksum(baseline_output):
   raise ValueError('基线快照输出摘要自检失败，无法据此对账')
  baseline_steps=step_descriptors(baseline_dict);candidate_steps=step_descriptors(candidate_dict)
  ledger=build_ledger(baseline_steps,candidate_steps)
  covered_b={e['baseline_index'] for e in ledger if e['baseline_index'] is not None}
  covered_n={e['new_index'] for e in ledger if e['new_index'] is not None}
  if covered_b!=set(range(len(baseline_steps))) or covered_n!=set(range(len(candidate_steps))):
   raise ValueError('对账未覆盖全部步骤，拒绝发布不完整的结论')
  output=compare_rows(baseline_output,result['output'])
  conclusion=build_conclusion({'trace_id':baseline.id,'name':baseline.name,'dataset_id':baseline.dataset_id,'plan_id':baseline.plan_id},
   {'trace_id':candidate.id,'name':candidate.name,'dataset_id':candidate.dataset_id,'plan_id':candidate.plan_id,'attempts':attempts},
   baseline_dict['result'],result,ledger,output)
  with Session() as s:
   r=s.get(Review,review_id)
   if not r:raise ValueError('复查记录已不存在，放弃发布')
   if r.status!='running' or r.attempts!=attempts:raise ValueError('复查已被续跑或取消，放弃陈旧结果')
   c=s.get(Trace,r.candidate_trace_id)
   if not c:raise ValueError('复查缺少新执行记录，放弃发布')
   r.result=conclusion;r.status='completed';r.error=None;r.progress={'completed':len(result['operators']),'steps_signature':steps_signature}
   c.result=result;c.status='completed';c.error=None
   s.commit()
  log('worker','review.completed',f'{review_id}: {conclusion["verdict"]}')
 except Exception as exc:
  logging.exception('review failed')
  _fail(review_id,str(exc),attempts)

def retry(item_id):
 with Session() as s:
  r=s.get(Review,item_id)
  if not r:raise HTTPException(404,'未找到复查记录')
  if r.status not in ('failed','running'):raise HTTPException(409,'只有失败或中断的复查可以续跑')
  r.attempts=(r.attempts or 1)+1;r.status='queued';r.error=None;r.result=None
  name=r.name
  c=s.get(Trace,r.candidate_trace_id)
  if c:c.status='queued';c.error=None;c.result=None
  s.commit();result=record(r)
 try:_requeue(result['id'])
 except HTTPException:
  with Session() as s:
   r=s.get(Review,item_id);r.status='failed';r.error='队列不可用，请稍后重试'
   c=s.get(Trace,r.candidate_trace_id)
   if c:c.status='failed';c.error='队列不可用，请稍后重试'
   s.commit()
  raise
 log('operator','review.retry',name);return result

def _summary(row):
 item=record(row);progress=dict(row.progress or {})
 item['progress']={'completed':progress.get('completed',0),'steps_signature':progress.get('steps_signature')}
 return item

def list_items():
 with Session() as s:return [_summary(r) for r in s.query(Review).order_by(Review.id.desc()).limit(100).all()]

def detail(item_id):
 with Session() as s:
  row=s.get(Review,item_id)
  if not row:raise HTTPException(404,'未找到复查记录')
  return _summary(row)
